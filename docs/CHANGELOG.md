# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (66건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

---

## [2026-04-30 21:00] 스크리닝 DB 조회 타임존 불일치 수정 — get_by_date KST 명시
- 제안서: docs/proposals/2026-04-30_screening-query-timezone-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/db/repository.py: `get_by_date()`에서 naive datetime → KST timezone-aware datetime으로 변경. `datetime.combine(target_date, ..., tzinfo=kst)` 적용.
  - tests/test_db/test_repository.py: KST 타임존 기반 get_by_date 테스트 2건 추가 (조회 검증, 타 날짜 제외 검증).
- 검증 결과: pytest ✅ (423 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만

---

## [2026-04-29 17:00] auto-implement 후 서비스 재시작 누락 수정
- 제안서: docs/proposals/2026-04-29_auto-implement-service-restart.md
- 카테고리: bug_fix
- 변경 파일:
  - scripts/run_auto_implement.sh: Claude Code 실행 후 로그에서 `implemented` 감지 시 `launchctl stop/start com.kis.autotrader` 재시작 로직 추가. 10초 후 프로세스 상태 확인. 미구현 시 재시작 스킵.
- 검증 결과: pytest ✅ (421 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff: pre-existing 에러만

