# 앙상블 가중투표 SELL 편향 수정

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-17
- 상태: implemented
- 우선순위: high
- 카테고리: refactor
- 관련파일: src/strategy/ensemble.py

## 현상 분석

W16(2026-04-13~04-17) 주간 데이터 분석 결과, 앙상블 전략이 구조적으로 SELL만 출력하는 문제가 확인되었다.

**데이터 근거**:
- ENSEMBLE 시그널 8,054건 중 **BUY 0건, SELL 8,054건** (100% SELL)
- SELL 내역: 미보유종목 SELL 5,903건(skip_reason=null) + sell_without_position 2,151건
- 앙상블 경유 매수가 0건이므로, 이번 주 유일한 매수는 MA 단독 시그널(골든크로스)로 발생
- 앙상블 confidence 분포: 0.10~0.19 (4,128건, 51.2%), 0.20~0.29 (3,254건, 40.4%), 0.30~0.39 (672건, 8.3%)
- BUY 0건이므로 confidence 값 자체가 무의미

**원인 분석** (`src/strategy/ensemble.py` `_weighted_vote` L141-173):

현재 가중투표 로직:
```python
buy_w = sum(s.confidence for s in signals if s.signal_type == SignalType.BUY)
sell_w = sum(s.confidence for s in signals if s.signal_type == SignalType.SELL)
```

횡보장에서 교차 전략(MA, MACD)은 대부분 HOLD(confidence=0)를 출력한다. 이때 RSI나 볼린저 중 하나라도 SELL(과매수 영역)이면:
- `buy_w = 0.0`, `sell_w > 0.0` → 앙상블 = SELL

HOLD 투표가 "기권"으로 처리되어 소수의 SELL 투표만으로 전체 결과가 SELL로 확정된다. BUY가 출력되려면 BUY 투표의 confidence 합이 SELL 합보다 커야 하는데, 횡보장에서 BUY를 생성하는 전략(골든크로스)이 극히 드물기 때문에 앙상블은 구조적으로 SELL 편향에 빠진다.

## 제안 내용

HOLD 투표를 단순 기권이 아닌 **활성 투표**로 취급하여, 비매매 합의(consensus for inaction)가 있을 때 앙상블이 HOLD를 출력하도록 개선한다.

**변경 로직**: HOLD 전략 비율이 과반(전체 전략의 50% 초과)이면 앙상블도 HOLD를 반환한다. 이를 통해 4개 전략 중 3개가 HOLD일 때 나머지 1개의 SELL이 전체를 지배하는 현상을 방지한다.

이 변경은 `_weighted_vote`에만 적용한다. `_majority_vote`는 이미 non-hold만 집계하므로 동일한 문제가 덜 하지만, weighted가 현재 기본 설정이므로 우선 weighted만 수정한다.

## 변경 스펙

### 파일별 변경사항

- `src/strategy/ensemble.py`: `_weighted_vote` 메서드에 HOLD 과반 가드 추가

**변경 전** (L141-147):
```python
def _weighted_vote(self, signals: list[Signal]) -> Signal:
    """가중 투표를 수행한다."""
    buy_w = sum(s.confidence for s in signals if s.signal_type == SignalType.BUY)
    sell_w = sum(s.confidence for s in signals if s.signal_type == SignalType.SELL)

    if buy_w == 0.0 and sell_w == 0.0:
        return Signal(
```

**변경 후**:
```python
def _weighted_vote(self, signals: list[Signal]) -> Signal:
    """가중 투표를 수행한다."""
    hold_count = sum(1 for s in signals if s.signal_type == SignalType.HOLD)
    if hold_count > len(signals) / 2:
        return Signal(
            signal_type=SignalType.HOLD, confidence=0.0,
            reason=f"앙상블 가중투표: HOLD 과반 ({hold_count}/{len(signals)})",
        )

    buy_w = sum(s.confidence for s in signals if s.signal_type == SignalType.BUY)
    sell_w = sum(s.confidence for s in signals if s.signal_type == SignalType.SELL)

    if buy_w == 0.0 and sell_w == 0.0:
        return Signal(
```

- `tests/test_strategy/test_ensemble.py`: HOLD 과반 테스트 케이스 추가

**추가 테스트**:
```python
def test_weighted_hold_majority_guard(self):
    """HOLD 과반 시 가중투표가 HOLD를 반환하는지 확인한다."""
    # 3개 전략 중 2개 HOLD, 1개 SELL → HOLD 반환
    signals = [
        Signal(signal_type=SignalType.HOLD, confidence=0.0, reason="MA HOLD"),
        Signal(signal_type=SignalType.HOLD, confidence=0.0, reason="RSI HOLD"),
        Signal(signal_type=SignalType.SELL, confidence=0.8, reason="MACD SELL"),
    ]
    # ...앙상블이 HOLD를 반환하는지 검증
```

### 변경 파일 수 (2개)
1. `src/strategy/ensemble.py` — HOLD 과반 가드 추가
2. `tests/test_strategy/test_ensemble.py` — 테스트 추가

## 기대 효과

- **SELL 편향 제거**: HOLD 과반 시 앙상블이 SELL 대신 HOLD를 출력하여, 미보유 종목에 대한 무의미한 SELL 시그널(주간 8,054건) 대폭 감소
- **시그널 DB 부하 감소**: HOLD 시그널은 DB에 기록되지 않으므로(`_record_signal_to_db`에서 HOLD 스킵) signals 테이블 적재량 감소
- **BUY 시그널 경로 보존**: 이 변경은 SELL 편향만 차단하며, 복수 전략이 BUY에 합의할 때의 매수 시그널 생성에는 영향 없음
- **정량적 추정**: W16 기준 ENSEMBLE 시그널 8,054건 중 HOLD 과반에 해당하는 비율을 제거, 약 5,000~7,000건의 불필요한 SELL 시그널 제거 예상

## 롤백

`src/strategy/ensemble.py`의 `_weighted_vote` 메서드에서 HOLD 과반 가드 블록(6줄)을 제거하면 원래 로직으로 복원된다. 테스트 파일의 추가 테스트 케이스는 삭제해도 기존 테스트에 영향 없음.
