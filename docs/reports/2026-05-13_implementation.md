# [2026-05-13] 구현 리포트

## 요약

| 항목 | 값 |
|------|----|
| 처리 제안서 | 3건 |
| implemented | 3건 |
| failed | 0건 |
| skipped | 0건 |
| 버전 변화 | v0.2.1 → v0.2.3 (patch ×2, docs ×1) |

## 제안서 처리 결과

### 1. ✅ 2026-05-12_notify-error-signature-fix.md (bug_fix, v0.2.2)

- **상태**: ready → implemented
- **카테고리**: bug_fix
- **변경 파일** (2개):
  - `src/worker/runner.py`: `_notify_dead_task`의 `notify_error` 호출을 (context, error) 2개 인자로 수정. 호출 측 `error[:200]` truncate 제거.
  - `tests/test_worker/test_runner.py`: 시그니처 회귀 테스트 1건 (`test_notify_dead_task_uses_correct_signature`) 추가.
- **테스트**: `tests/test_worker/test_runner.py` 6 passed. 전체 462 passed (5 pre-existing fail).
- **mypy/ruff**: pre-existing 에러만, 신규 위반 없음.

### 2. ✅ 2026-05-12_repository-datetime-utcnow-deprecation.md (refactor, v0.2.3)

- **상태**: ready → implemented
- **카테고리**: refactor
- **변경 파일** (1개):
  - `src/db/repository.py`: `datetime.utcnow()` 7곳 모두 제거.
    - L884 (TIMESTAMPTZ, `SystemMetric.recorded_at`): `datetime.now(UTC)` (aware 유지).
    - L182/313/513/534 (naive `DateTime` updated_at) + L205/262 (비교 필터): `datetime.now(UTC).replace(tzinfo=None)` (동작 동일, deprecation만 제거).
    - import: `from datetime import UTC, date, datetime, timedelta`.
- **테스트**: pytest 452 passed (5 pre-existing fail, 10 pre-existing model errors). DB/integration 테스트 영향 없음. `python -W error::DeprecationWarning -c "from src.db import repository"` ✅.
- **mypy/ruff**: pre-existing 4 errors만, ruff ✅.

### 3. ✅ 2026-05-12_signals-time-axis-unify.md (docs, v0.2.3, bump 없음)

- **상태**: ready → implemented
- **카테고리**: docs
- **변경 파일** (3개):
  - `docs/prompts/_common_rules.md`: signals 시간 필터 정책 1줄 추가 — `detected_at` 사용 명문화.
  - `docs/prompts/daily_routine.md`: `signal_performance`(L87) + `rolling_7d_signals`(L178) 쿼리의 `created_at` → `detected_at`.
  - `docs/prompts/weekly_routine.md`: `signal_performance`(L65) 쿼리의 `created_at` → `detected_at`.
- **테스트**: 문서 변경 only — pytest 영향 없음.
- **버저닝**: `--category docs`로 bump 없음 (DB ImplementationLog만 기록).

## 안전 게이트 검증

| 항목 | 결과 |
|------|------|
| 금지 영역 (.env, credentials.json, alembic/versions, KIS_ENV) | 침범 없음 |
| 파라미터 변경 (config_overrides.json) | 해당 없음 |
| 한 제안서당 변경 파일 ≤ 5 | 2 / 1 / 3 — 모두 통과 |
| pytest 회귀 (내 변경에 의한 신규 fail) | 없음 |

## Pre-existing 이슈 (이번 변경과 무관)

- `tests/test_strategy/test_risk.py` 4건 fail + `tests/test_analytics.py::test_get_optimal_risk_params` 1건 fail = 5건 (이전 커밋부터 존재)
- `tests/test_db/test_models.py` 10건 ERROR (SQLite의 JSONB 미지원, pre-existing)
- `tests/test_worker/test_runner.py`의 `import asyncio` ruff F401 (pre-existing)
- `src/db/repository.py` mypy 4 errors (`type-arg`, pre-existing)
- `src/worker/runner.py` mypy 3 errors (line 96-98, pre-existing)

## 배포

- git commit + `git tag -a v0.2.3 -m ...` + `git push origin main --tags`
- Mac Mini 자동 pull & restart 설정에 따라 배포 진행 (또는 수동)
- v0.2.2 (bug_fix) → v0.2.3 (refactor) — Proposal 3(docs)은 bump 없음, 최종 v0.2.3
