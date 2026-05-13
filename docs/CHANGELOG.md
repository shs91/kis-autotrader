# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (74건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

## [2026-05-12] 자동 SemVer 버저닝 시스템 도입 (v0.1.0 → v0.2.0)
- 카테고리: feature
- 변경 파일:
  - src/__version__.py: 단일 버전 출처 신설.
  - src/utils/versioning.py: 카테고리→bump 매핑, SemVer 파싱/bump, `__version__.py`+`pyproject.toml` 동시 갱신.
  - scripts/record_implementation.py: 검증 통과 시점 자동 bump + `VERSION=v0.x.x` stdout 출력 (`--no-bump` 플래그 지원).
  - src/notify/formatter.py & telegram.py: 일일 결산 헤더에 `[vX.Y.Z]` + 당일 bump 내역 섹션 자동 노출.
  - src/db/models.py + src/db/repository.py + alembic/versions/edb0690663bb_*.py: `implementation_logs.version` 컬럼 추가.
  - scripts/auto_implement_prompt.txt & auto_heal_prompt.txt: `git tag -a $VERSION` 단계 명시.
  - docs/BRIDGE_SPEC.md: 자동 버저닝 규칙 명문화.
  - tests/test_versioning.py + tests/test_notify/test_formatter.py: 단위 테스트 31건 추가.
- 영향: 검증 통과 시점에만 annotated tag 부여 → 알려진 정상 지점 목록 확보. 결산 헤더에 버전 노출. 롤백은 `git checkout v0.x.y && launchctl restart`.
- 검증 결과: pytest ✅ (468 passed, 1 pre-existing analytics fail) | mypy: pre-existing 에러만 | ruff (신규 파일) ✅ | end-to-end: 자체 변경 기록 시 0.1.0 → 0.2.0 (minor bump) 정상 동작.

---

