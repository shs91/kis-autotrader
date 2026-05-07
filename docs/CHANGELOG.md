# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (68건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-07] 스크리닝 최소 점수 하향 — 전환율 0% 장기화 해소
- 제안서: docs/proposals/2026-05-07_screening-min-score-reduction.md
- 카테고리: param_tuning
- 변경 파일:
  - config_overrides.json: `SCREENING_MIN_SCORE` 0.25(기본값) → 0.15 하향 추가. 7일 연속 전환율 0% 교착 해소 목적.
- 검증 결과: pytest ✅ (424 passed, 5 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만

---

## [2026-05-07] 시그널 최소 신뢰도 상향 조정 — 저신뢰 시그널 필터링
- 제안서: docs/proposals/2026-05-07_min-confidence-upward-adjustment.md
- 카테고리: param_tuning
- 변경 파일:
  - config_overrides.json: `STRATEGY_MIN_CONFIDENCE` 0.05 → 0.15 상향. 시그널 act_rate 29.5% 개선 및 노이즈 시그널 제거 목적.
- 검증 결과: pytest ✅ (424 passed, 5 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만

---

## [2026-05-06] 엔진 일봉 데이터 최소 요구량 하향 — 매매 교착 해소
- 제안서: docs/proposals/2026-05-06_engine-daily-data-threshold-reduction.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: 일봉 데이터 최소 요구 건수를 하드코딩 36에서 `settings.strategy.ma_long_period + 2` (기본 22)로 변경. KIS API가 최대 30건 반환하므로 MA/RSI/Bollinger 전략 정상 평가 가능.
  - tests/test_engine_db_integration.py: DAILY_DATA_INSUFFICIENT 테스트를 새 임계값 기준으로 수정.
- 검증 결과: pytest ✅ (425 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만

---

## [2026-05-04] 일봉 데이터 부족 / 평가 조기 종료 진단 메트릭 추가
- 제안서: docs/proposals/2026-05-02_daily-data-insufficient-metric.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `_get_daily_df()`에서 일봉 부족 시 `DAILY_DATA_INSUFFICIENT` 메트릭 적재 (종목코드·반환건수·최소요구건수·사이클). `_process_stock()`에서 일봉 부족 조기 종료 시 `EVAL_SKIP` 메트릭 적재 (종목코드·사유·사이클).
  - tests/test_engine_db_integration.py: `TestDailyDataInsufficientMetric` 클래스 추가 (DAILY_DATA_INSUFFICIENT 적재 검증, EVAL_SKIP 적재 검증 — 2개 테스트).
- 검증 결과: pytest ✅ (425 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-05-01] 시그널 저장 필터 임계값 하향 — STRATEGY_MIN_CONFIDENCE 0.08→0.05
- 제안서: docs/proposals/2026-05-01_signal-confidence-threshold-lowering.md
- 카테고리: param_tuning
- 변경 파일:
  - config_overrides.json: `STRATEGY_MIN_CONFIDENCE` 0.08 → 0.05 하향 (BRIDGE_SPEC 허용 최솟값). 14일 연속 시그널 0건 상태 해소 목적.
- 검증 결과: pytest ✅ (423 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만
