# TIMESTAMPTZ 컬럼에 naive datetime 저장 버그 수정 + 회귀 방지 listener + 스크리너 매매시간 가드

## 메타데이터
- 작성: Claude Code (사용자 지시 기반)
- 일자: 2026-05-12
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/engine.py, src/worker/screener.py, src/db/session.py, tests/test_db/test_timezone_validation.py, tests/test_worker/test_screener.py

> 본 제안서는 자동 파이프라인 대신 사용자 세션에서 직접 적용됨 — screening_results의 24/7 작동 정황까지 함께 발견되어 매매시간 가드를 추가 포함. 실 DB의 손상 row는 별도 runbook(`docs/runbooks/2026-05-12_timestamp-utc-backfill.md`)로 처리. screening_results는 전수 TRUNCATE.

## 현상 분석

2026-05-12 일간 분석가가 `trades.traded_at`·`screening_results.screened_at`의 KST 변환 결과가 실제 매매시간과 일치하지 않는 정황을 보고했음. 분석가가 본 표현:

> 체결 시각 18:00~20:03 (실제 장 마감 후), screening 데이터에 미래 일자 2026-05-13 포함

실 DB 검증으로 가설 확정:

| trades.id | 실제 매매(추정) | DB 절대값(UTC) | epoch | AT TIME ZONE 'KST' |
|-----------|----------------|---------------|-------|--------------------|
| 39 | KST 15:11 (장 마감 직전) | 2026-05-12 15:11:55 UTC | 1778598715 | 2026-05-13 00:11:55 |
| 38 | KST 11:03 | 2026-05-12 11:03:53 UTC | 1778583833 | 2026-05-12 20:03:53 |
| 37 | KST 11:03 | 2026-05-12 11:03:13 UTC | 1778583793 | 2026-05-12 20:03:13 |

리포트의 "18:00~20:03"은 실제 KST 09:00~11:03 매매가 "09:00~11:03 UTC"로 박힌 뒤 KST로 다시 변환되어 +9 추가된 결과.

### 근본 원인

- 컬럼 타입: `DateTime(timezone=True)` (PostgreSQL TIMESTAMPTZ)
- DB 세션 timezone = `UTC` (`SELECT current_setting('TimeZone')` 확인)
- write 코드: `datetime.now()` (인자 없음) → naive datetime (시스템 TZ = KST)
- psycopg2가 naive datetime을 TIMESTAMPTZ 컬럼에 INSERT 시 → 세션 timezone(UTC)로 해석해 저장
- 결과: KST 값이 UTC로 박혀 절대 시각이 의도보다 +9시간 큰 값으로 영구 기록

### 영향

- 신규 row 계속 손상 중 (오늘 cycle 33까지 진행 중)
- daily/weekly 리포트의 KST 변환에서 매매시간이 18:00~24:30으로 표시
- 일자 경계 misclassification — 일부 거래가 다음 영업일로 집계됨 → 룰 트리거(전환율, drawdown 일별 집계) 신뢰성 직접 손상
- 분석가가 미래 일자(2026-05-13) row를 발견한 이유

### 모범 패턴이 이미 코드에 존재

`src/worker/queue.py:49,105,143,180,201`은 일관되게 `datetime.now(UTC)` (aware UTC)를 사용 — 이 컬럼들은 손상 없음. 즉 같은 코드베이스 안에 올바른 레퍼런스가 있음.

## 제안 내용

1. **write 경로 3곳을 aware UTC로 변경** — `datetime.now()` → `datetime.now(UTC)`. 기존 worker/queue.py 패턴과 일관.
2. **SQLAlchemy `before_flush` 이벤트 리스너로 회귀 차단** — TIMESTAMPTZ 컬럼에 naive datetime이 매핑되면 ValueError 발생. 향후 같은 패턴이 코드에 재유입돼도 런타임에 즉시 차단.

## 변경 스펙

### 파일별 변경사항

- `src/engine.py`:
  - L6 import: `from datetime import date, datetime` → `from datetime import UTC, date, datetime`
  - L969: `"traded_at": datetime.now().isoformat()` → `"traded_at": datetime.now(UTC).isoformat()`
  - L999: `screened_at=datetime.now()` → `screened_at=datetime.now(UTC)`

- `src/worker/screener.py`:
  - L28 import: `from datetime import date, datetime` → `from datetime import UTC, date, datetime`
  - L204: `screened_at=datetime.now()` → `screened_at=datetime.now(UTC)`

- `src/db/session.py`:
  - SQLAlchemy `before_flush` 이벤트 리스너를 모듈 로드 시점에 등록.
  - 동작: `session.new`(INSERT)와 `session.dirty`(UPDATE)의 모든 매핑 객체에 대해, `inspect(obj).mapper.columns`를 순회하며 컬럼 타입이 `DateTime` AND `timezone=True`인데 매핑된 값이 naive datetime(`tzinfo is None`)이면 `ValueError` raise.
  - 에러 메시지: `"Naive datetime in TIMESTAMPTZ column {table}.{column}: use datetime.now(UTC) or aware datetime"`
  - 이는 컬럼 default(`datetime.utcnow`)에서 채워지는 naive UTC 값도 동일하게 잡힘 — 단, 본 제안의 변경 직후에는 `datetime.utcnow` default들이 여전히 naive이므로, 리스너는 **명시적으로 사용자 코드가 set한 값에만 적용**되도록 `obj.__dict__`에 키가 존재하는 경우만 검사(서버 default/ORM default가 아직 적용되지 않은 상태 보호). 검증은 `tests/test_db/test_timezone_validation.py`에서 행함.

### 추가 테스트

- `tests/test_db/test_timezone_validation.py` (신규):
  - `test_naive_datetime_rejected_in_timestamptz`: Trade 인스턴스를 naive `traded_at`으로 생성하고 `session.flush()` 시 `ValueError` 발생 확인
  - `test_aware_utc_datetime_accepted`: `datetime.now(UTC)`로 생성한 Trade가 정상 flush·commit
  - `test_aware_kst_datetime_accepted`: `datetime.now(ZoneInfo("Asia/Seoul"))`도 정상 동작 (psycopg2가 UTC로 변환해 저장)
  - 픽스처: SQLite in-memory 또는 conftest의 테스트 PostgreSQL

## 기대 효과

- 신규 row의 `traded_at`·`screened_at`이 절대 시각 기준으로 정확히 저장됨
- daily report의 "체결 시각 18:00~20:03" 비정상 표시 해소 → 실제 매매시간 09:00~15:30 표시 복원
- 일자 경계 misclassification 해소 → 룰 A/B/C/D 트리거 판정 신뢰성 회복
- listener로 향후 같은 패턴 회귀 차단 (defense-in-depth)
- 기존 손상 row는 본 제안 범위 외 — 별도 runbook(`docs/runbooks/2026-05-12_timestamp-utc-backfill.md`)에서 수동 백필

## 롤백

- `git revert <commit>` — 코드 수정과 리스너 모두 한 번에 원복
- 손상 데이터는 그대로 유지 (롤백 자체로 데이터 추가 손상 없음)
- 리스너가 다른 정상 경로의 INSERT를 잘못 차단할 경우, 리스너만 등록 해제하는 hotfix 가능 (`src/db/session.py`에서 `event.remove(...)`)
