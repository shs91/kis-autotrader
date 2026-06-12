# 단독 BUY 허용 + 보유중 BUY 관측 수정 설계

- 날짜: 2026-06-12
- 상태: 승인됨 (데이터 검증 후 사용자 승인)
- 성격: 실전 매매 직접 영향(앙상블) + 관측 개선(매매 무변경)

## 1. 배경 — 데이터로 확정된 진단

이번 주 0매매의 원인을 system_metrics.SIGNAL_SKIP.vote_meta로 정량 검증:

- **개별 BUY 투표는 많았다**(이번주: MACD 4,504 · RSI 4,686 · MA 2,250). BUY를 끄는 건 MACD·RSI.
- **그러나 같은 종목·봉에서 BUY표 2개가 한 번도 안 겹쳤다** — `n_buy=2` 사이클 **0건**, `n_buy=1` 11,440건. 앙상블 `n_win≥2` 단독표 억제로 전부 HOLD → BUY 0 → 매매 0.
- **강한 단독 BUY 종목**: 084650(conf 0.862), 093370 후성(conf 1.000). 약한 단독(003280 0.231, 027360 0.040)은 HOLD가 옳음.
- 기대효과는 제한적(084650 +1.25%, 093370 +7.25% 일봉 종가 기준; 6/2 실거래 -3.67% 손절). forward 검증엔 일중가 필요하나 DB엔 일봉만 → **소액 시작**.

별도로, 보유중 종목의 BUY 신호가 `skip_reason=NULL`로 기록되는 관측 결함 발견(대한해운 4,524건).

## 2. 변경 A — 보유중 BUY 관측 수정 (매매 로직 무변경)

`src/engine.py:874-887` 보유 종목 처리 블록. 현재 `skip_reason`이 SELL일 때만 설정 → BUY는 NULL.
```python
# 현재 (877):
if not will_act and signal.signal_type == SignalType.SELL:
    skip_reason = "low_confidence_sell"
# 수정:
if not will_act:
    if signal.signal_type == SignalType.SELL:
        skip_reason = "low_confidence_sell"
    elif signal.signal_type == SignalType.BUY:
        skip_reason = "held_skip_buy"   # 보유 종목 추가매수 안 함(피라미딩 X)
```
`will_act` 불변 → 매수 동작 그대로. signals에 "보유중 BUY 차단" 사유가 남아 관측 투명화.

## 3. 변경 B — 앙상블 단독 BUY 조건부 허용 (옵션2)

### 3.1 `src/config.py` `StrategyConfig` (min_confidence 인접)
```python
# 단독 BUY 허용 최소 신뢰도 (n_win=1이라도 이 이상이면 BUY 전환). 1.01=비활성
solo_buy_min_confidence: float = field(
    default_factory=lambda: _env_float("STRATEGY_SOLO_BUY_MIN_CONFIDENCE", 0.7)
)
```

### 3.2 `src/strategy/ensemble.py`
`__init__`에 인자 추가(default 1.01 = 단독표 억제 유지, 안전):
```python
def __init__(self, strategies, method=MAJORITY, strategy_weights=None,
             solo_buy_min_confidence: float = 1.01) -> None:
    ...
    self._solo_buy_min_confidence = solo_buy_min_confidence
```
`_weighted_vote`의 `n_win<2 → HOLD`(186-191)를 BUY 한정 완화:
```python
if n_win < 2:
    if winner_type == SignalType.BUY:
        base = winner_weight / n_win
        opp = winner_weight / (winner_weight + loser_weight)
        solo_conf = min(base * opp, 1.0)
        if solo_conf >= self._solo_buy_min_confidence:
            return Signal(SignalType.BUY, solo_conf,
                          reason=f"앙상블 가중투표: 단독 BUY 허용 (conf={solo_conf:.2f}, n_win=1)")
    return Signal(SignalType.HOLD, 0.0,
                  reason=f"앙상블 가중투표: 승자표 부족 (n_win={n_win}) → HOLD")
```

### 3.3 `src/strategy/registry.py:75`
```python
EnsembleStrategy(
    strategies=[ma, rsi, macd, bollinger],
    method=settings.strategy.ensemble_method,
    solo_buy_min_confidence=settings.strategy.solo_buy_min_confidence,
)
```

## 4. 유지되는 안전장치 (불변)
단독 BUY가 앙상블 통과해도 매수 게이트 재적용: `min_confidence(0.20)` · 위험종목 배제 · 가격하한 · 예수금 · 종목별/일일 한도. 손절은 `risk.py`.

## 5. 측정 게이트
C 진단 알림이 매수 N건/차단 분포 표시. 소액(예수금 ~45만, 종목당 ~9만). 며칠 → 승률 확인 → 임계 조정/롤백(`config_overrides`에서 `STRATEGY_SOLO_BUY_MIN_CONFIDENCE=1.01`).

## 6. 테스트 (TDD)
- **ensemble**(`tests/test_strategy/test_ensemble.py`): 단독 BUY conf≥0.7→BUY / conf<0.7→HOLD / 단독 SELL→HOLD / n_win≥2→기존 / default(1.01)면 단독 BUY→HOLD(억제 유지)
- **engine 관측**: 보유중 BUY → `skip_reason="held_skip_buy"`, `action_taken=False`

## 7. 리스크
효과 제한적(일봉 +1.25%/+7.25%) + forward 검증 일중가 부재. 소액 + 즉시 롤백. 추격매수(이미 오른 종목)는 위험게이트·소액으로 제한.
