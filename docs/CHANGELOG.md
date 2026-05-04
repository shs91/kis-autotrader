# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (65건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

---

## [2026-04-28 21:00] 스크리닝→엔진 평가 파이프라인 단절 수정 — converted_to_trade 필터 제거
- 제안서: docs/proposals/2026-04-28_screening-to-engine-pipeline-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `_screen_stocks()`에서 `converted_to_trade` 필터 제거. 상위 랭킹 종목을 플래그와 무관하게 평가 대상에 포함. 중복 제거(seen set) 추가. 진단 로깅 강화 (DB 조회 건수, 고유 종목수, converted 건수).
  - tests/test_engine_db_integration.py: 스크리닝 결과 반영 테스트 3건 추가 (unconverted 포함 검증, 중복 제거 검증, max_screened 한도 준수 검증).
- 검증 결과: pytest ✅ (421 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅

