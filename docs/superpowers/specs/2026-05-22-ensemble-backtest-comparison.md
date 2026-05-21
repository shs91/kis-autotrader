# Ensemble 산출식 변경 — 검증 결정 (백테스트 대체)

- 작성일: 2026-05-22
- 관련: `docs/superpowers/plans/2026-05-22-ensemble-confidence-formula.md` Task 4
- 결정자: 사용자 (2026-05-22, "라이브 관찰 게이트로 머지")

## 1. 사전 백테스트가 불가능한 이유 (실측)

- `scripts/run_backtest.py`는 **`MovingAverageStrategy`만** 인스턴스화한다(`scripts/run_backtest.py:49`).
  ensemble을 실행하지 않으므로 신/구 `_weighted_vote` 비교 시 **결과가 동일** → 무의미.
- ensemble 전용 하니스를 짜도 입력 데이터가 없다:
  - 저장소에 과거 OHLC CSV 없음.
  - DB에 캔들/가격 이력 테이블 없음(`daily_performances`, `daily_summary`, `market_actions`만 존재).
    시스템은 시세를 실시간 조회하고 bar를 영속화하지 않는다.
  - 유일한 경로는 `--api`(라이브 KIS 인증) — rate-limit 민감 + 프로덕션 접촉이라 제외.
- `system_metrics`의 BUY_REJECT는 최종 confidence만 저장하고 투표 분해(n_win, W, L)가 없어
  과거 데이터로 사전 영향 추정도 불가.

## 2. 채택한 검증 게이트 (사전 백테스트 대체)

1. **단위 테스트**: Case A~E + 경계(동수/단독표/clamp/무반대) green. 전체 846 테스트 통과.
2. **하위 리스크 게이트**: 본 변경은 신뢰도 산출만 바꾸며, 임계값(`STRATEGY_MIN_CONFIDENCE` 0.20)과
   하위 게이트(손절/익절, POSITION_RATIO, MAX_DAILY_DRAWDOWN, MAX_CONSECUTIVE_LOSSES)는 불변.
   비정상 매수는 2차 게이트가 흡수.
3. **머지 후 1주 라이브 관찰** (수용 기준):
   - act_rate(action_taken/signals) 추이.
   - LOW_CONFIDENCE 거절 → HOLD 전환 및 BUY_REJECT 사유 분포 변화.
   - 손실률/MDD가 한도(MAX_LOSS_RATE 0.03, MAX_DAILY_DRAWDOWN) 내 유지 — **초과 시 즉시 롤백**.
   - trade 수 / 실현손익 추이.

## 3. 후속 과제 (별도)

- `scripts/run_backtest.py`에 전략 선택 인자(`--strategy ensemble` 등) 추가 + ensemble 하니스.
- OHLC bar 영속화(또는 백테스트용 데이터 적재 경로) — 향후 전략 변경의 사전 백테스트 가능하게.
- `_weighted_vote` 진단을 위해 signal/BUY_REJECT 메트릭에 n_win·W·L 기록 추가(데이터 기반 튜닝용).
