# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (78건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-13] engine.py의 메트릭·시그널 큐 적재 시 naive timestamp 차단 버그 수정 (v0.2.4) — 🔴 핫픽스
- 제안서: docs/proposals/2026-05-13_engine-metric-signal-naive-timestamp-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `_record_signal_to_db`(L1079) + `_record_metric`(L1102)의 `datetime.now().isoformat()` → `datetime.now(UTC).isoformat()`. naive ISO 문자열이 worker handler를 거쳐 `Signal.detected_at`·`SystemMetric.recorded_at` (TIMESTAMPTZ) 컬럼에 명시 set되면서 `validate_timezone_aware` listener에 의해 ValueError로 차단되던 흐름을 해소.
  - tests/test_engine_db_integration.py: 회귀 테스트 2건 추가 — `TestRecordMetric.test_recorded_at_is_timezone_aware`, `TestRecordSignalToDb.test_detected_at_is_timezone_aware`.
- 배경: 2026-05-12 fb7b548에서 도입된 `before_flush` 리스너가 큐 경유 적재 경로의 naive timestamp를 막아 2026-05-12 15:20 UTC 이후 system_metrics·signals 영속화가 16+ 시간 단절. 일일 리포트는 `repository.py:884`를 원인으로 지목했으나 해당 라인은 c44dade에서 이미 정리됨 — 실제 차단 지점은 상류의 큐 적재부.
- 영향: system_metrics·signals 영속화 즉시 복구. 자동 파이프라인 안전 게이트 룰 C(에러)·룰 D(사이클) 트리거 신뢰성 회복. 일일/주간 리포트의 시그널 정확도·signal_performance 분석 데이터 기반 회복.
- 검증 결과: pytest 변경 회귀 테스트 ✅ 2 passed | 전체 410 passed, 5 pre-existing fail (KST 17시대 시간대 의존) + 10 pre-existing errors (SQLite JSONB 호환성) — 모두 본 변경 무관 stash 검증 완료 | ruff src/engine.py + tests ✅ | mypy 변경 라인 에러 없음.

---

## [2026-05-13] 분석 프롬프트의 signals 시간축을 detected_at으로 통일 (v0.2.3, bump 없음)
- 제안서: docs/proposals/2026-05-12_signals-time-axis-unify.md
- 카테고리: docs
- 변경 파일:
  - docs/prompts/_common_rules.md: 시간 필터 정책 한 줄 추가 — signals는 항상 `detected_at` 사용.
  - docs/prompts/daily_routine.md: signal_performance(L87), rolling_7d_signals(L178) 쿼리의 `created_at` → `detected_at`.
  - docs/prompts/weekly_routine.md: signal_performance(L65) 쿼리의 `created_at` → `detected_at`.
- 영향: 분석 시간축이 비즈니스 이벤트 시점(`detected_at`)으로 일관화. 일자 경계 근처 트랜잭션 지연으로 인한 미세한 일자 누수 차단. 후속 프롬프트 작성 시 혼용 재발 방지.
- 검증 결과: 문서 변경 only, pytest 영향 없음 (record_implementation `--category docs`로 bump 없음).

---

## [2026-05-13] repository.py의 datetime.utcnow() 제거 (Python 3.12 deprecation 대응, v0.2.3)
- 제안서: docs/proposals/2026-05-12_repository-datetime-utcnow-deprecation.md
- 카테고리: refactor
- 변경 파일:
  - src/db/repository.py: `datetime.utcnow()` 7곳을 `datetime.now(UTC)` 패턴으로 치환. TIMESTAMPTZ 컬럼(SystemMetric.recorded_at, L884)은 aware UTC 유지, naive `DateTime` 컬럼(Order/Portfolio/Stock.updated_at 4곳)과 비교 필터 2곳은 `.replace(tzinfo=None)` 으로 동작 동일.
- 영향: Python 3.12 DeprecationWarning 7건 제거. `datetime.now(UTC)` 패턴 일관화. `engine.py`/`worker/queue.py`/`worker/screener.py`와 정합. L884의 TIMESTAMPTZ listener ValueError 잠재 위험 사전 차단.
- 검증 결과: pytest ✅ (452 passed, 5 pre-existing fail, 10 pre-existing model errors) | mypy: pre-existing 4 errors만 | ruff ✅ | `python -W error::DeprecationWarning -c "from src.db import repository"` ✅

---

## [2026-05-13] DEAD 태스크 알림의 notify_error 시그니처 불일치 수정 (v0.2.2)
- 제안서: docs/proposals/2026-05-12_notify-error-signature-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/worker/runner.py: `_notify_dead_task`가 `notify_error`를 (context, error) 두 인자로 호출하도록 수정. 호출 측 `error[:200]` truncate 제거 (책임을 `format_error`로 위임).
  - tests/test_worker/test_runner.py: `test_notify_dead_task_uses_correct_signature` 회귀 테스트 1건 추가.
- 영향: DEAD 태스크 발생 시 `TypeError`로 swallow되던 Telegram 알림이 정상 전송됨. 모니터링 사각지대 해소.
- 검증 결과: pytest ✅ (462 passed, 5 pre-existing fail) | mypy: pre-existing 에러만 | ruff: pre-existing 미사용 import만

---

## [2026-05-12] TIMESTAMPTZ에 naive datetime 저장 버그 수정 + listener + 스크리너 매매시간 가드 (v0.2.1)
- 제안서: docs/proposals/2026-05-12_timestamp-naive-to-aware-utc.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `datetime.now()` 2곳 `datetime.now(UTC)`로 교체 + UTC import.
  - src/worker/screener.py: `_is_trading_window()` 가드 추가 (휴장일/매매시간 외 스킵), `datetime.now()` → `datetime.now(UTC)`.
  - src/db/session.py: `before_flush` 리스너로 TIMESTAMPTZ 컬럼에 명시 set된 naive datetime 거부.
  - tests/test_db/test_timezone_validation.py: 신규 3 케이스 (naive 거부, aware UTC/KST 허용).
  - tests/test_worker/test_screener.py: 가드 우회 mock 추가.
- 데이터 처리: `screening_results` 전수 TRUNCATE (24/7 작동 누적 + 시간 어긋남 row 폐기). 손상 trades/signals는 사용자가 별도 백필 완료.
- 영향: 신규 row의 timestamp 절대 시각 정확. 일자 경계 misclassification 해소. 휴장일 INSERT 차단. 회귀 시 ValueError 즉시 발생.
- 검증 결과: pytest 461 passed (5 pre-existing) | mypy: pre-existing 에러만 | ruff ✅

---

