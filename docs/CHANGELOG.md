# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (63건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

---

## [2026-04-27 21:00] 시그널 가뭄 진단 정보 DB 적재 — SIGNAL_SUMMARY 메트릭
- 제안서: docs/proposals/2026-04-27_signal-diagnosis-db-persistence.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: 사이클 종료 시 `_record_metric("SIGNAL_SUMMARY", {...})` 호출 추가. cycle/evaluated/buy_count/sell_count/hold_count/max_confidence/screened_count를 system_metrics 테이블에 기록.
  - tests/test_engine_db_integration.py: `TestSignalSummaryMetric` 클래스 추가 (사이클 후 SIGNAL_SUMMARY 기록 검증, 필수 키 존재 검증, 평가 0건 시 미기록 검증 — 3개 테스트).
- 검증 결과: pytest ✅ (414 passed, 4 pre-existing failures) | mypy: pre-existing 에러만 | ruff ✅

---

## [2026-04-30] 자동 진단/복구 파이프라인 (Auto-Heal) 추가
- 카테고리: feature
- 변경 파일:
  - scripts/watchdog.sh: 반복 재시작 감지 로직 추가 — 30분 내 3회 이상 재시작 시 `auto_heal.sh` 트리거. `increment_restart_count()`, `trigger_auto_heal()` 함수 추가. 하루 1회 실행 제한. 장외/주말/공휴일 카운터 초기화.
  - scripts/auto_heal.sh: (신규) 에러로그 + 시스템 상태(DB, 디스크, 메모리, 헬스체크, git) 수집 → Claude Code 진단 세션 호출. 성공(HEAL_SUCCESS) 시 서비스 재시작, 실패(HEAL_FAILED) 시 Telegram 수동 개입 알림.
  - scripts/auto_heal_prompt.txt: (신규) Claude Code SRE 진단/수정 프롬프트. BRIDGE_SPEC 안전 게이트 준수, 최소 변경 원칙, pytest/mypy/ruff 검증 필수.
