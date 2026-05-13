# repository.py의 datetime.utcnow() 제거 (Python 3.12 deprecation 대응)

## 메타데이터
- 작성: Cowork (사용자 지시 기반)
- 일자: 2026-05-12
- 상태: implemented
- 우선순위: low
- 카테고리: refactor
- 관련파일: src/db/repository.py

## 현상 분석

Python 3.12에서 `datetime.utcnow()`는 deprecated이며, 향후 버전에서 제거 예정.
`src/db/repository.py`에 7곳이 남아 있어 실행 시 `DeprecationWarning`이 발생한다.

| Line | 코드 | 컬럼 | 컬럼 타입 |
|------|------|------|-----------|
| 182 | `order.updated_at = datetime.utcnow()` | Order.updated_at | `DateTime` (naive) |
| 205 | `today_start = datetime.utcnow().replace(hour=0, ...)` | (비교 필터) | — |
| 262 | `today_start = datetime.utcnow().replace(hour=0, ...)` | (비교 필터) | — |
| 313 | `portfolio.updated_at = datetime.utcnow()` | Portfolio.updated_at | `DateTime` (naive) |
| 513 | `stock.updated_at = datetime.utcnow()` | Stock.updated_at | `DateTime` (naive) |
| 534 | `stock.updated_at = datetime.utcnow()` | Stock.updated_at | `DateTime` (naive) |
| 884 | `recorded_at=recorded_at or datetime.utcnow()` | SystemMetric.recorded_at | `DateTime(timezone=True)` |

### 현재 동작은 정상
- 위 컬럼들 중 SystemMetric.recorded_at만 TIMESTAMPTZ. 나머지 5곳은 `DateTime` (timezone 없음) 컬럼이므로 `datetime.utcnow()`가 반환하는 naive UTC가 그대로 저장되어 일관성에 문제 없음.
- 비교 필터 2곳(L205/L262)도 naive UTC 끼리 비교하므로 결과는 의도대로.
- L884의 SystemMetric.recorded_at은 TIMESTAMPTZ이지만 `session.py`의 `validate_timezone_aware` 리스너가 작동할 경우 ValueError를 던지는 잠재 위험이 있다 — 현재 `record()` 호출 빈도가 낮아 표면화되지 않은 것으로 추정.

### 2026-05-12_timestamp-naive-to-aware-utc 제안서와의 관계
- 그 제안서는 `engine.py`·`worker/screener.py`의 **TIMESTAMPTZ 컬럼 쓰기 3곳**만 대상으로 함.
- 본 제안서는 `repository.py` 전체의 `datetime.utcnow()` deprecation을 정리하는 후속 작업.

## 제안 내용

`datetime.utcnow()` 호출 전부를 다음 두 패턴으로 일괄 치환:

1. **TIMESTAMPTZ 컬럼에 쓰는 1곳 (L884)** → `datetime.now(UTC)` (aware UTC)
   - `session.py` 리스너의 잠재 ValueError 회피
   - 다른 모듈(`engine.py`, `worker/queue.py`)의 모범 패턴과 일치
2. **naive `DateTime` 컬럼에 쓰는 4곳 (L182, L313, L513, L534)** 및 **비교 필터 2곳 (L205, L262)** → `datetime.now(UTC).replace(tzinfo=None)`
   - 동작 변화 0: 결과 datetime은 기존과 동일한 naive UTC
   - deprecation warning만 제거

> 추가 비고: 장기적으로 `Stock`/`Order`/`Portfolio`의 `updated_at`도 TIMESTAMPTZ로 통일하는 것이 바람직하나, 이는 `alembic` 마이그레이션이 필요해 BRIDGE_SPEC의 금지 영역(`alembic/versions/`)에 해당. **본 제안서 범위 외** — 별도 사용자 승인 게이트로 진행.

## 변경 스펙

### 파일별 변경사항

- `src/db/repository.py`:
  - **import 라인 수정** (L5): `from datetime import date, datetime, timedelta` → `from datetime import UTC, date, datetime, timedelta`
  - **L182**: `order.updated_at = datetime.utcnow()` → `order.updated_at = datetime.now(UTC).replace(tzinfo=None)`
  - **L205**: `today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)` → `today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)`
  - **L262**: `today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)` → `today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)`
  - **L313**: `portfolio.updated_at = datetime.utcnow()` → `portfolio.updated_at = datetime.now(UTC).replace(tzinfo=None)`
  - **L513**: `stock.updated_at = datetime.utcnow()` → `stock.updated_at = datetime.now(UTC).replace(tzinfo=None)`
  - **L534**: `stock.updated_at = datetime.utcnow()` → `stock.updated_at = datetime.now(UTC).replace(tzinfo=None)`
  - **L884**: `recorded_at=recorded_at or datetime.utcnow()` → `recorded_at=recorded_at or datetime.now(UTC)` *(TIMESTAMPTZ이므로 aware 유지)*

### 추가 테스트
- 기존 테스트가 모두 통과하면 충분 (동작 변화 없음).
- 선택: `tests/test_db/test_repository.py`에 `import warnings; warnings.filterwarnings("error", category=DeprecationWarning)` 컨텍스트로 한 번 import → 호출 → DeprecationWarning이 더 이상 발생하지 않는지 검증.

### 검증 명령
```bash
# 1. 변경 후 deprecation warning이 사라졌는지 확인
python -W error::DeprecationWarning -c "from src.db import repository; print('ok')"

# 2. 회귀 테스트
pytest tests/test_db/ -v

# 3. 타입체크/린트
python -m mypy src/db/repository.py
ruff check src/db/repository.py
```

## 기대 효과

- Python 3.12 `DeprecationWarning` 7건 제거
- Python 3.13+ 업그레이드 시 `datetime.utcnow()` 제거에 대한 대비
- `datetime.now(UTC)` 사용 일관화 → 코드베이스 단일 패턴 정착 (engine.py, worker/queue.py, worker/screener.py와 정합)
- L884의 SystemMetric.recorded_at에 대한 잠재 ValueError 위험 사전 차단

## 롤백

- `git revert <commit>` — 단일 파일 변경이므로 영향 범위 좁음
- 데이터 마이그레이션 없음 — 저장되는 절대 시각은 변경 전후 동일

## 후속 작업 (본 제안서 범위 외)

1. **`src/db/models.py`의 컬럼 default 정리** — `default=datetime.utcnow` 라인 3건도 동일 deprecation. SQLAlchemy 콜러블 default는 함수 객체를 등록하는 방식이라 호출 시점에 deprecation warning. `default=lambda: datetime.now(UTC).replace(tzinfo=None)`로 변경 필요.
2. **`Stock`/`Order`/`Portfolio`의 `updated_at` 컬럼 TIMESTAMPTZ로 마이그레이션** — alembic 마이그레이션 + listener와의 정합성 검증 필요. 사용자 승인 게이트로 진행.
