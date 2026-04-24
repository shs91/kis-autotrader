# 앙상블 HOLD 과반 가드 임계값 완화 — 매매 교착 해소

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-24
- 상태: implemented
- 우선순위: critical
- 카테고리: refactor
- 관련파일: src/strategy/ensemble.py

## 현상 분석

4/15 이후 **10일 연속 매매 0건**. W17 주간 9,069 사이클에서 15,918건의 SIGNAL_SKIP이 발생했으며, 전부 `hold_action`(앙상블 HOLD)이다.

원인은 4/17에 구현된 HOLD 과반 가드(`_weighted_vote` 내 `hold_count > len(signals) / 2`)와 일봉 캐시 구조의 조합이다.

현재 앙상블은 4개 서브전략(MA·RSI·MACD·BB)으로 구성된다. 일봉 기반 교차 전략 특성상 대부분의 거래일에 3~4개 전략이 HOLD을 반환한다. `hold_count > 2.0` 조건에 의해 HOLD 3개 이상이면 앙상블이 즉시 HOLD을 반환하므로, BUY 시그널 1개가 발생해도 무시된다.

4주간 시그널 통계:
- GOLDEN_CROSS: 9,331건 생성, 5건만 action_taken (0.05%)
- ENSEMBLE: 8,054건 중 BUY 0건 (100% SELL 또는 HOLD)
- RSI_SIGNAL: 0건

4/17 이전에는 앙상블이 SELL 편향 문제가 있어 HOLD 과반 가드를 도입한 것이 올바른 판단이었다. 그러나 가드가 BUY 시그널까지 차단하는 부작용이 발생했다.

## 제안 내용

HOLD 과반 가드의 임계값을 `len(signals) / 2` (50%)에서 `len(signals) * 3 / 4` (75%)로 상향한다.

효과:
- 4개 전략 기준: `hold_count > 3.0` → **4개 모두 HOLD일 때만** 앙상블 HOLD
- 3 HOLD + 1 BUY → weighted vote로 진행 (약한 BUY 허용)
- 3 HOLD + 1 SELL → weighted vote로 진행 (약한 SELL 허용)
- 4 HOLD → 앙상블 HOLD (현재와 동일)

이 변경은 매매 빈도를 회복하면서도, 기존 리스크 관리 체계(MAX_LOSS_RATE 3%, MAX_POSITION_RATIO 20%, MIN_CONFIDENCE 0.1)가 역추세 매수 리스크를 제어한다.

## 변경 스펙

### 파일별 변경사항

- `src/strategy/ensemble.py`: `_weighted_vote` 메서드 내 HOLD 과반 가드 임계값 변경

변경 전 (144행):
```python
if hold_count > len(signals) / 2:
```

변경 후:
```python
if hold_count > len(signals) * 3 / 4:
```

reason 문자열도 함께 변경 (148행):
```python
reason=f"앙상블 가중투표: HOLD 과반 ({hold_count}/{len(signals)})",
```
→
```python
reason=f"앙상블 가중투표: HOLD 대다수 ({hold_count}/{len(signals)})",
```

- `tests/test_strategy/test_ensemble.py`: 기존 HOLD 과반 테스트 수정 + 새 임계값 경계 테스트 추가

수정할 테스트: HOLD 과반 가드 테스트에서 기대값 조정
- 3 HOLD + 1 BUY (4개 전략): 기존 기대 HOLD → 새 기대 BUY (weighted vote 진행)
- 4 HOLD: HOLD 유지 (가드 작동)

추가 테스트:
- `test_weighted_vote_hold_3_of_4_passes_through`: 3 HOLD + 1 BUY → BUY 통과 확인
- `test_weighted_vote_hold_4_of_4_blocks`: 4 HOLD → HOLD 확인

### 추가 테스트 (필요 시)

```python
def test_weighted_vote_hold_3_of_4_passes_through(ensemble_weighted):
    """3/4 HOLD + 1 BUY → weighted vote로 진행하여 BUY 반환."""
    # 3개 전략 HOLD, 1개 전략 BUY(confidence=0.5)
    # 기대: BUY (confidence = 0.5/4 = 0.125)

def test_weighted_vote_hold_4_of_4_blocks(ensemble_weighted):
    """4/4 HOLD → 앙상블 HOLD 반환."""
    # 4개 전략 전부 HOLD
    # 기대: HOLD
```

## 기대 효과

- MA 골든크로스 또는 RSI 과매도 시그널 1개만 발생해도 앙상블이 BUY로 전환 가능
- 예상 BUY 시그널 빈도: W15 수준(주 5~8건)으로 회복
- MIN_CONFIDENCE(0.1) 필터를 통과하려면 서브전략 confidence ≥ 0.4 필요 (confidence/4 ≥ 0.1)
- 기존 손절(3%)/익절(5%)/MDD/연패 안전장치에 의한 리스크 제어 유지

## 롤백

`src/strategy/ensemble.py` 144행의 `len(signals) * 3 / 4`를 `len(signals) / 2`로 복원.
테스트 파일도 기존 기대값으로 원복.
