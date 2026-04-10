# 기본 전략을 앙상블로 변경하여 다중 전략 활성화

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-10
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/strategy/selector.py, src/engine.py

## 현상 분석

### DB 근거 (전체 기간)
signals 테이블의 signal_type 분포:
- **GOLDEN_CROSS: 9,032건 (100%)**
- DEAD_CROSS: 0건
- RSI_SIGNAL: 0건
- MACD 관련: 0건
- 볼린저 관련: 0건

### 7일 rolling (쿼리 10~11)
- 최근 7일 GOLDEN_CROSS만 9,032건, 그 외 시그널 타입 0건
- RSI 시그널: 0건 (쿼리 11)

### 원인 분석
`src/strategy/selector.py`의 `StrategySelector.__init__()` 기본 전략이 `"moving_average"`로 고정되어 있다.
종목별 매핑이 별도 설정되지 않은 한, **모든 종목이 이동평균 전략만 사용**한다.

Phase 3(2026-04-09)에서 MACD, 볼린저밴드 전략이 `registry.py`에 등록되고 앙상블에 "performance" 투표 모드가 추가되었으나, selector의 기본값이 변경되지 않아 **실질적으로 비활성 상태**이다.

결과적으로:
1. 앙상블 투표가 동작하지 않음 (단일 전략만 호출)
2. `get_strategy_win_rates()`로 전략 비교 불가 (MA 외 데이터 없음)
3. 멀티타임프레임 전략(2026-04-28 예정)의 전제 조건("4개 전략 모두 20영업일 데이터") 충족 불가

## 제안 내용

기본 전략을 `"moving_average"` → `"ensemble"`로 변경하여 모든 등록된 전략(MA, RSI, MACD, Bollinger)이 앙상블 투표에 참여하도록 한다.

아울러, 볼린저밴드 시그널이 DB에 적절한 signal_type으로 기록되도록 엔진의 signal_type 매핑을 보완한다.

## 변경 스펙

### 파일별 변경사항

#### 1. `src/strategy/selector.py` (L32)

변경 전:
```python
default_strategy: str = "moving_average",
```

변경 후:
```python
default_strategy: str = "ensemble",
```

#### 2. `src/engine.py` — `_record_signal_to_db()` 메서드 내 signal_type 매핑

변경 전 (약 L826~L834):
```python
signal_type_str = "UNKNOWN"
if "골든크로스" in signal.reason:
    signal_type_str = "GOLDEN_CROSS"
elif "데드크로스" in signal.reason:
    signal_type_str = "DEAD_CROSS"
elif "RSI" in signal.reason.upper():
    signal_type_str = "RSI_SIGNAL"
else:
    signal_type_str = signal.reason[:50] if signal.reason else "UNKNOWN"
```

변경 후:
```python
signal_type_str = "UNKNOWN"
if "골든크로스" in signal.reason:
    signal_type_str = "GOLDEN_CROSS"
elif "데드크로스" in signal.reason:
    signal_type_str = "DEAD_CROSS"
elif "RSI" in signal.reason.upper() or "과매도" in signal.reason or "과매수" in signal.reason:
    signal_type_str = "RSI_SIGNAL"
elif "MACD" in signal.reason.upper():
    signal_type_str = "MACD_SIGNAL"
elif "볼린저" in signal.reason:
    signal_type_str = "BOLLINGER_SIGNAL"
elif "앙상블" in signal.reason or "ensemble" in signal.reason.lower():
    signal_type_str = "ENSEMBLE"
else:
    signal_type_str = signal.reason[:50] if signal.reason else "UNKNOWN"
```

### 추가 테스트 (필요 시)

기존 `tests/test_strategy/test_selector.py` 테스트에서 기본 전략 확인 테스트가 있다면 `"ensemble"`로 기대값을 변경해야 한다. 해당 파일의 `"moving_average"` 기대값을 `"ensemble"`로 수정한다.

## 기대 효과

- 4개 전략(MA, RSI, MACD, 볼린저)이 모두 앙상블에 참여하여 시그널 다양성 확보
- signals 테이블에 GOLDEN_CROSS 외 RSI_SIGNAL, MACD_SIGNAL, BOLLINGER_SIGNAL, DEAD_CROSS 등 다양한 signal_type 기록 시작
- `get_strategy_win_rates()` 함수로 전략별 성과 비교 가능
- 멀티타임프레임 전략(2026-04-28 예정)의 전제 조건 충족을 위한 데이터 축적 시작
- 앙상블 투표를 통한 시그널 품질 향상 기대 (단일 전략 대비 false positive 감소)

## 롤백

1. `src/strategy/selector.py` L32: `default_strategy: str = "ensemble"` → `"moving_average"` 복원
2. `src/engine.py`: signal_type 매핑은 하위 호환이므로 롤백 불필요 (새 타입 추가만 했으므로 기존 동작 영향 없음)
