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

---

# [2026-05-13 추가] 🔴 핫픽스 사이클 (사용자 지시)

## 요약

| 항목 | 값 |
|------|----|
| 처리 제안서 | 1건 |
| implemented | 1건 |
| 버전 변화 | v0.2.3 → **v0.2.4** (patch) |
| 트리거 | 사용자 지시 (오전 사이클 직후 일일 리포트의 critical 항목 핫픽스) |

## 제안서 처리 결과

### ✅ 2026-05-13_engine-metric-signal-naive-timestamp-fix.md (bug_fix, v0.2.4)

- **상태**: ready → implemented
- **카테고리**: bug_fix
- **우선순위**: critical

#### 배경
일일 리포트(2026-05-13_daily.md)에서 system_metrics가 2026-05-12 15:20:17 KST 이후 완전 단절(16+ 시간) 감지. 리포트는 `repository.py:884`를 원인으로 지목했으나, 사용자/Claude 협업 조사 결과 **해당 라인은 같은 날 오전 c44dade에서 이미 정리됨**. 실제 차단 지점은 상류의 큐 적재부였음 — 동일 원인이 같은 일자 signals 0건 anomaly도 설명.

#### 진짜 원인
`src/engine.py:1079` (시그널 enqueue) + `src/engine.py:1102` (메트릭 enqueue)의 `datetime.now().isoformat()` → naive 로컬타임(KST) ISO 문자열을 큐에 적재 → worker handler가 `datetime.fromisoformat()`로 naive 복원 → `Signal.detected_at` / `SystemMetric.recorded_at` (TIMESTAMPTZ)에 명시 set → 2026-05-12 fb7b548에서 도입된 `validate_timezone_aware` `before_flush` 리스너가 ValueError로 차단 → rollback.

#### 변경 파일 (2개)
- `src/engine.py`:
  - L1079: `"detected_at": datetime.now().isoformat()` → `datetime.now(UTC).isoformat()`
  - L1102: `"recorded_at": datetime.now().isoformat()` → `datetime.now(UTC).isoformat()`
  - `UTC`는 L6에서 이미 import되어 있어 추가 import 불필요
- `tests/test_engine_db_integration.py`:
  - `from datetime import datetime` 추가
  - `TestRecordMetric.test_recorded_at_is_timezone_aware` 회귀 테스트 추가 (engine.py:1102)
  - `TestRecordSignalToDb.test_detected_at_is_timezone_aware` 회귀 테스트 추가 (engine.py:1079)

#### 검증 결과
- pytest 회귀 테스트 2건 ✅ 2 passed
- pytest 전체: 410 passed, 5 pre-existing fail (KST 17시대 시간대 의존 — `장 마감 임박` 가드), 10 pre-existing errors (SQLite JSONB 호환성) — 모두 stash로 사전 존재 확인
- ruff `src/engine.py` + `tests/test_engine_db_integration.py` ✅ All checks passed
- mypy 변경 라인 에러 없음 (전체 79건은 사전 존재)

## 큐 데이터로 본 영향 (PostgreSQL `task_queue`, 최근 2일)

| task_type | COMPLETED | DEAD | 마지막 성공 (KST) | 마지막 실패 (KST) |
|-----------|-----------|------|-------------------|-------------------|
| record_metric | 7,279 | **8,778** | 2026-05-12 15:20:17 | 2026-05-13 15:19:59 |
| record_signal | 4,334 | **4,124** | 2026-05-12 15:20:17 | 2026-05-13 15:19:59 |

→ 2026-05-13 거래일 분 메트릭 8,778건 + 시그널 4,124건이 DEAD 누적. **소급 복구 불가** (원천 데이터 없음).

## 배포

- 커밋: `ba83cfb` (main 브랜치 push 완료)
- 태그: `v0.2.4` annotated tag push 완료
- 서비스 재시작: `launchctl stop` + `sleep 5` + `launchctl start` → PID 98318 (23:31:40 KST)
- 워커 핸들러 등록 확인: `record_trade` / `record_signal` / `record_metric` (logs/autotrader.log)

## 최종 운영 검증 — 보류

장 마감(15:30 KST) 이후 핫픽스 배포로 실시간 메트릭 enqueue 없음.
**2026-05-14 09:00 KST 시장 개장 후 30분 내 검증 필요**:

```sql
SELECT metric_type, recorded_at AT TIME ZONE 'Asia/Seoul' AS recorded_kst
FROM system_metrics ORDER BY recorded_at DESC LIMIT 10;
-- 기대: 2026-05-14 09:xx KST의 CYCLE_START 1건 이상
```

## 후속 작업 (핫픽스 범위 외)

1. **누락 구간 명시**: 일일/주간 리포트 분석 측이 2026-05-12 15:20 ~ 2026-05-13 15:20 KST 구간의 룰 평가를 제외하도록 인지.
2. **`datetime.now()` 사용처 일제 점검**: DB·큐 영속화 경로의 동일 패턴 감사 (`grep -rn "datetime\.now()" src/`).
3. **린트 룰 검토**: ruff `DTZ` 룰셋(`flake8-datetimez`)으로 `datetime.now()` 무인자 호출 차단 검토.
4. **사전 존재 테스트 실패**: 시간대 의존 5건 + SQLite JSONB 10건은 별도 제안서로 분리.
