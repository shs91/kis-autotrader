# 보유종목 실시간 가격 vs 매수가 비교 차트 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 엔진이 이미 폴링하는 보유종목 현재가를 `price_snapshots` 시계열로 적재하고, 대시보드 신규 positions 페이지에서 실시간 가격·매수 평단가·손절/익절선·체결 마커를 Altair 차트로 비교한다.

**Architecture:** 폴링 재사용(웹소켓 X) — 엔진 사이클의 보유종목 현재가를 워커 큐로 `price_snapshots`에 INSERT(매매 루프 무차단). 대시보드는 `price_snapshots`(7일) + `portfolios`(평단가·peak) + `trades`(체결마커) + `settings`(손절/익절%)를 결합해 종목별 Altair 차트를 렌더. 일 1회 7일 초과분 정리. 신규 테이블/경로라 KRX 매매 불변.

**Tech Stack:** SQLAlchemy 2.0 + Alembic, APScheduler, Streamlit + Altair(streamlit 번들 의존성, 별도 설치 불필요), pandas, pytest.

**검증 환경:** worktree엔 venv 없음 — 메인 repo venv를 worktree cwd에서 사용:
- pytest: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest`
- mypy: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m mypy src/`
- ruff: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/ruff check <변경파일>`

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|------|------|-----------|
| `src/db/models.py` | `PriceSnapshot` ORM 모델 | 수정(append) |
| `alembic/versions/<rev>_add_price_snapshots.py` | 테이블 생성 마이그레이션 | 신규 |
| `src/db/repository.py` | `PriceSnapshotRepository`(add/get_recent/delete_older_than) | 수정(append + import) |
| `src/worker/handlers.py` | `PriceSnapshotHandler` | 수정(append) |
| `main.py` | 핸들러 등록 | 수정(1줄) |
| `src/engine.py` | 보유종목 스냅샷 enqueue | 수정(헬퍼 + 호출 1곳) |
| `src/scheduler/jobs.py` | 7일 정리 잡 | 수정(메서드 + add_job) |
| `dashboard/pages/positions.py` | 보유종목 차트 페이지 | 신규 |
| `tests/test_db/test_price_snapshot.py` | 모델·repository 테스트 | 신규 |
| `tests/test_worker/test_price_snapshot_handler.py` | 핸들러 테스트 | 신규 |
| `tests/test_engine_price_snapshot.py` | 엔진 enqueue 테스트 | 신규 |
| `dashboard/positions_data.py` | 차트 데이터 구성(순수 함수, 테스트 가능) | 신규 |
| `tests/test_dashboard/test_positions_data.py` | 차트 데이터 구성 테스트 | 신규 |

---

## Task 1: PriceSnapshot 모델 + 마이그레이션

**Files:**
- Modify: `src/db/models.py` (ScreeningResult 클래스 뒤에 append)
- Create: `alembic/versions/<rev>_add_price_snapshots.py`
- Test: `tests/test_db/test_price_snapshot.py`

- [ ] **Step 1: 실패 테스트 작성** — 모델이 import되고 컬럼을 가지는지

Create `tests/test_db/test_price_snapshot.py`:
```python
"""price_snapshots 모델·repository 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, PriceSnapshot


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_price_snapshot_columns(session: Session) -> None:
    snap = PriceSnapshot(
        stock_code="AAPL",
        market="US",
        currency="USD",
        price=145.32,
        captured_at=datetime.now(UTC),
    )
    session.add(snap)
    session.flush()
    assert snap.id is not None
    assert snap.stock_code == "AAPL"
    assert snap.market == "US"
    assert snap.currency == "USD"
    assert snap.price == 145.32
```

- [ ] **Step 2: 실패 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_db/test_price_snapshot.py -v`
Expected: FAIL — `ImportError: cannot import name 'PriceSnapshot'`

- [ ] **Step 3: 모델 구현** — `src/db/models.py`의 `ScreeningResult` 클래스 정의 끝(`__repr__` 뒤) 다음에 append:

```python
class PriceSnapshot(Base):
    """보유종목 실시간(폴링) 현재가 스냅샷 — 대시보드 가격 vs 매수가 비교용."""

    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="KRX"
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="KRW"
    )
    price: Mapped[float] = mapped_column(Numeric(18, 4, asdecimal=False), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_price_snapshots_code_time", "stock_code", "captured_at"),
        Index("ix_price_snapshots_time", "captured_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<PriceSnapshot({self.stock_code} {self.price} "
            f"@{self.captured_at})>"
        )
```

`src/db/models.py` 상단 sqlalchemy import에 `Index` 추가(이미 `Integer, Numeric, String, ...` import 블록):
```python
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
```

- [ ] **Step 4: 통과 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_db/test_price_snapshot.py::test_price_snapshot_columns -v`
Expected: PASS

- [ ] **Step 5: 마이그레이션 생성** — `alembic/versions/`에 신규 파일. 먼저 현재 head revision 확인:

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m alembic heads`
→ 출력된 head revision id를 아래 `down_revision`에 넣는다(예시값 `e5f6a7b8c9d0` — 실제 head로 교체).

Create `alembic/versions/f6a7b8c9d0e1_add_price_snapshots.py`:
```python
"""add price_snapshots table

Revision ID: f6a7b8c9d0e1
Revises: <ACTUAL_HEAD_REVISION>
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = '<ACTUAL_HEAD_REVISION>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'price_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('stock_code', sa.String(length=20), nullable=False),
        sa.Column('market', sa.String(length=10), server_default='KRX', nullable=False),
        sa.Column('currency', sa.String(length=8), server_default='KRW', nullable=False),
        sa.Column('price', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_price_snapshots_code_time', 'price_snapshots', ['stock_code', 'captured_at'], unique=False)
    op.create_index('ix_price_snapshots_time', 'price_snapshots', ['captured_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_price_snapshots_time', table_name='price_snapshots')
    op.drop_index('ix_price_snapshots_code_time', table_name='price_snapshots')
    op.drop_table('price_snapshots')
```

- [ ] **Step 6: 마이그레이션 검증(오프라인 SQL 생성으로 문법 확인)**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m alembic upgrade head --sql > /tmp/mig.sql 2>&1; tail -20 /tmp/mig.sql`
Expected: `CREATE TABLE price_snapshots` SQL이 에러 없이 생성됨. (실제 DB 적용 `alembic upgrade head`는 운영자 액션 — Task 7에서 안내.)

- [ ] **Step 7: 커밋**

```bash
git add src/db/models.py alembic/versions/f6a7b8c9d0e1_add_price_snapshots.py tests/test_db/test_price_snapshot.py
git commit -m "feat(db): price_snapshots 모델 + 마이그레이션 (보유종목 가격 스냅샷)"
```

---

## Task 2: PriceSnapshotRepository (add / get_recent / delete_older_than)

**Files:**
- Modify: `src/db/repository.py` (파일 끝에 클래스 append + import)
- Test: `tests/test_db/test_price_snapshot.py` (append)

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_db/test_price_snapshot.py`에 append:

```python
def test_repository_add_and_get_recent(session: Session) -> None:
    from src.db.repository import PriceSnapshotRepository

    repo = PriceSnapshotRepository(session)
    now = datetime.now(UTC)
    repo.add("AAPL", "US", "USD", 145.0, captured_at=now - timedelta(hours=2))
    repo.add("AAPL", "US", "USD", 146.5, captured_at=now - timedelta(hours=1))
    repo.add("MSFT", "US", "USD", 300.0, captured_at=now)  # 다른 종목

    rows = repo.get_recent("AAPL", since=now - timedelta(days=1))
    assert len(rows) == 2
    assert [r.price for r in rows] == [145.0, 146.5]  # captured_at 오름차순


def test_repository_get_recent_filters_since(session: Session) -> None:
    from src.db.repository import PriceSnapshotRepository

    repo = PriceSnapshotRepository(session)
    now = datetime.now(UTC)
    repo.add("AAPL", "US", "USD", 100.0, captured_at=now - timedelta(days=10))  # 범위 밖
    repo.add("AAPL", "US", "USD", 200.0, captured_at=now - timedelta(hours=1))

    rows = repo.get_recent("AAPL", since=now - timedelta(days=7))
    assert len(rows) == 1
    assert rows[0].price == 200.0


def test_repository_delete_older_than(session: Session) -> None:
    from src.db.repository import PriceSnapshotRepository

    repo = PriceSnapshotRepository(session)
    now = datetime.now(UTC)
    repo.add("AAPL", "US", "USD", 100.0, captured_at=now - timedelta(days=10))
    repo.add("AAPL", "US", "USD", 200.0, captured_at=now - timedelta(days=1))
    session.flush()

    deleted = repo.delete_older_than(now - timedelta(days=7))
    assert deleted == 1
    assert len(repo.get_recent("AAPL", since=now - timedelta(days=30))) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_db/test_price_snapshot.py -v`
Expected: FAIL — `ImportError: cannot import name 'PriceSnapshotRepository'`

- [ ] **Step 3: Repository 구현** — `src/db/repository.py` 끝에 append:

```python
class PriceSnapshotRepository:
    """보유종목 가격 스냅샷 CRUD."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        stock_code: str,
        market: str,
        currency: str,
        price: float,
        captured_at: datetime | None = None,
    ) -> PriceSnapshot:
        """스냅샷 1건을 적재한다."""
        snap = PriceSnapshot(
            stock_code=stock_code,
            market=market,
            currency=currency,
            price=price,
            captured_at=captured_at or datetime.now(UTC),
        )
        self._session.add(snap)
        self._session.flush()
        return snap

    def get_recent(self, stock_code: str, since: datetime) -> list[PriceSnapshot]:
        """종목의 since 이후 스냅샷을 captured_at 오름차순으로 반환한다."""
        stmt = (
            select(PriceSnapshot)
            .where(
                PriceSnapshot.stock_code == stock_code,
                PriceSnapshot.captured_at >= since,
            )
            .order_by(PriceSnapshot.captured_at)
        )
        return list(self._session.execute(stmt).scalars().all())

    def delete_older_than(self, cutoff: datetime) -> int:
        """cutoff 이전 스냅샷을 삭제하고 삭제 행 수를 반환한다(7일 롤링 정리)."""
        result = self._session.execute(
            delete(PriceSnapshot).where(PriceSnapshot.captured_at < cutoff)
        )
        return result.rowcount or 0
```

`src/db/repository.py` 상단 import 확인/추가:
- `PriceSnapshot`를 models import에 추가(기존 `from src.db.models import (...)` 블록에 `PriceSnapshot,` 추가).
- sqlalchemy import에 `delete` 추가(기존 `from sqlalchemy import select, ...`에 `delete` 추가; 없으면 `from sqlalchemy import delete, select`).
- `datetime`, `UTC`가 import되어 있는지 확인(없으면 `from datetime import UTC, datetime` 추가).

- [ ] **Step 4: 통과 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_db/test_price_snapshot.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/db/repository.py tests/test_db/test_price_snapshot.py
git commit -m "feat(db): PriceSnapshotRepository add/get_recent/delete_older_than"
```

---

## Task 3: PriceSnapshotHandler (워커) + 등록

**Files:**
- Modify: `src/worker/handlers.py` (append)
- Modify: `main.py` (핸들러 등록 1줄)
- Test: `tests/test_worker/test_price_snapshot_handler.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_worker/test_price_snapshot_handler.py`:
```python
"""PriceSnapshotHandler 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.worker.handlers import PriceSnapshotHandler


@pytest.mark.asyncio
async def test_handler_inserts_snapshot() -> None:
    fake_repo = MagicMock()
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with patch("src.db.session.get_session", return_value=fake_session), \
         patch("src.db.repository.PriceSnapshotRepository", return_value=fake_repo):
        handler = PriceSnapshotHandler()
        await handler.execute({
            "stock_code": "AAPL",
            "market": "US",
            "currency": "USD",
            "price": 145.32,
        })

    fake_repo.add.assert_called_once_with(
        stock_code="AAPL", market="US", currency="USD", price=145.32,
    )
```

- [ ] **Step 2: 실패 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_worker/test_price_snapshot_handler.py -v`
Expected: FAIL — `ImportError: cannot import name 'PriceSnapshotHandler'`

- [ ] **Step 3: 핸들러 구현** — `src/worker/handlers.py` 끝에 append:

```python
class PriceSnapshotHandler(TaskHandler):
    """보유종목 가격 스냅샷 INSERT 핸들러."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """payload: stock_code, market, currency, price."""
        from src.db.repository import PriceSnapshotRepository
        from src.db.session import get_session

        with get_session() as session:
            PriceSnapshotRepository(session).add(
                stock_code=payload["stock_code"],
                market=payload.get("market", "KRX"),
                currency=payload.get("currency", "KRW"),
                price=payload["price"],
            )
```

- [ ] **Step 4: 통과 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_worker/test_price_snapshot_handler.py -v`
Expected: PASS

- [ ] **Step 5: 핸들러 등록** — `main.py`의 핸들러 등록 블록(`worker.register_handler("record_metric", RecordMetricHandler())` 줄 뒤)에 추가:

```python
    worker.register_handler("price_snapshot", PriceSnapshotHandler())
```

`main.py`의 handlers import 블록에 `PriceSnapshotHandler` 추가(기존 `from src.worker.handlers import (...)`).

- [ ] **Step 6: import·등록 검증**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -c "import main"`
Expected: 에러 없음(import 성공)

- [ ] **Step 7: 커밋**

```bash
git add src/worker/handlers.py main.py tests/test_worker/test_price_snapshot_handler.py
git commit -m "feat(worker): PriceSnapshotHandler + 등록"
```

---

## Task 4: 엔진 — 보유종목 스냅샷 enqueue

**Files:**
- Modify: `src/engine.py` (헬퍼 메서드 + 보유 처리 직전 호출)
- Test: `tests/test_engine_price_snapshot.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_engine_price_snapshot.py`:
```python
"""엔진 보유종목 가격 스냅샷 enqueue 테스트."""

from __future__ import annotations

from unittest.mock import patch

from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), \
         patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), \
         patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), \
         patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        return TradingEngine(watchlist=["005930"])


def test_enqueue_price_snapshot_payload() -> None:
    engine = _make_engine()
    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_price_snapshot("005930", 70123.0)

    mock_enq.assert_called_once()
    kwargs = mock_enq.call_args.kwargs
    assert kwargs["task_type"] == "price_snapshot"
    payload = kwargs["payload"]
    assert payload["stock_code"] == "005930"
    assert payload["market"] == "KRX"
    assert payload["currency"] == "KRW"
    assert payload["price"] == 70123  # KRX 정수 정규화


def test_enqueue_price_snapshot_swallows_error() -> None:
    engine = _make_engine()
    with patch.object(engine._task_queue, "enqueue", side_effect=Exception("q down")):
        # 예외가 매매 흐름으로 전파되면 안 된다.
        engine._enqueue_price_snapshot("005930", 70123.0)
```

- [ ] **Step 2: 실패 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_engine_price_snapshot.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_enqueue_price_snapshot'`

- [ ] **Step 3: 헬퍼 구현** — `src/engine.py`의 `_enqueue_calendar_event` 메서드 정의 바로 앞(또는 enqueue 메서드들이 모인 `# ── Worker Queue enqueue 메서드 ──` 섹션)에 추가:

```python
    def _enqueue_price_snapshot(self, stock_code: str, price: float) -> None:
        """보유종목 현재가를 price_snapshots에 적재하도록 Worker Queue에 enqueue한다.

        대시보드의 '실시간 가격 vs 매수가' 비교 차트용 시계열. 추가 API 호출 없이
        매매 사이클이 이미 조회한 현재가를 재사용한다. enqueue 실패는 매매 흐름에
        영향을 주지 않도록 삼킨다(시계열 누락만 발생).
        """
        try:
            self._task_queue.enqueue(
                task_type="price_snapshot",
                payload={
                    "stock_code": stock_code,
                    "market": self._market.market_code,
                    "currency": self._market.currency,
                    "price": self._norm_price(price),
                },
                priority=0,  # 최저 우선순위 — 매매 태스크에 양보
            )
        except Exception:
            logger.exception("가격 스냅샷 enqueue 실패 %s (매매 무영향)", stock_code)
```

- [ ] **Step 4: 헬퍼 단위 테스트 통과 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_engine_price_snapshot.py -v`
Expected: 2 passed

- [ ] **Step 5: 보유 처리 분기에서 호출** — `src/engine.py` `_process_stock`의 보유 분기(`if is_held and holding_info is not None:` 블록 내, `_process_held_stock` 호출 직전)에 스냅샷 enqueue 추가:

찾을 코드(보유 분기):
```python
        if is_held and holding_info is not None:
```
그 블록에서 `await self._process_held_stock(...)` 호출 **직전**에 한 줄 추가:
```python
            # 보유종목 현재가를 대시보드 비교 차트용 시계열로 적재(매매 무영향).
            self._enqueue_price_snapshot(stock_code, current.current_price)
```

- [ ] **Step 6: 전체 엔진 테스트 회귀 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_engine_price_snapshot.py tests/test_engine_db_integration.py -q`
Expected: all passed (기존 사이클 테스트 무회귀)

- [ ] **Step 7: 커밋**

```bash
git add src/engine.py tests/test_engine_price_snapshot.py
git commit -m "feat(engine): 보유종목 가격 스냅샷 enqueue (대시보드 비교 차트용)"
```

---

## Task 5: 7일 롤링 정리 잡

**Files:**
- Modify: `src/scheduler/jobs.py` (메서드 + add_job)
- Test: `tests/test_scheduler/test_price_snapshot_cleanup.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_scheduler/test_price_snapshot_cleanup.py`:
```python
"""가격 스냅샷 정리 잡 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_cleanup_job_deletes_old(make_jobs) -> None:
    # make_jobs: 기존 conftest의 TradingJobs 팩토리(없으면 아래 인라인 생성 참조)
    jobs = make_jobs()
    fake_repo = MagicMock()
    fake_repo.delete_older_than.return_value = 5
    fake_session = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    with patch("src.db.session.get_session", return_value=fake_session), \
         patch("src.db.repository.PriceSnapshotRepository", return_value=fake_repo):
        jobs.cleanup_price_snapshots_job()

    fake_repo.delete_older_than.assert_called_once()
```

> **주의:** `make_jobs` 픽스처가 기존 `tests/test_scheduler/conftest.py`에 없으면, 해당 디렉토리의 다른 테스트(`test_jobs_market.py`)가 `TradingJobs`를 어떻게 생성하는지 보고 동일 패턴으로 인라인 생성하라. TradingJobs는 보통 `TradingJobs(engine=MagicMock(), market_profile=...)` 형태다 — 실제 시그니처는 `src/scheduler/jobs.py`의 `__init__`을 확인.

- [ ] **Step 2: 실패 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_scheduler/test_price_snapshot_cleanup.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'cleanup_price_snapshots_job'`

- [ ] **Step 3: 정리 잡 메서드 구현** — `src/scheduler/jobs.py`의 `summarize_daily_job` 메서드 뒤에 추가:

```python
    def cleanup_price_snapshots_job(self) -> None:
        """7일 초과 가격 스냅샷을 삭제한다(롤링 정리). 시장 무관(공유 테이블)."""
        try:
            from datetime import UTC, timedelta

            from src.db.repository import PriceSnapshotRepository
            from src.db.session import get_session

            cutoff = datetime.now(UTC) - timedelta(days=7)
            with get_session() as session:
                deleted = PriceSnapshotRepository(session).delete_older_than(cutoff)
            logger.info("가격 스냅샷 정리: %d행 삭제 (7일 초과)", deleted)
        except Exception:
            logger.exception("가격 스냅샷 정리 실패 (매매에 영향 없음)")
```

> `datetime`은 jobs.py 상단에 이미 import됨(`from datetime import datetime`). `UTC`/`timedelta`는 위 메서드 내 지역 import로 처리(파일 상단 import를 건드리지 않음).

- [ ] **Step 4: 통과 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_scheduler/test_price_snapshot_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: add_job 등록** — `src/scheduler/jobs.py`에서 잡들을 등록하는 메서드(예: `setup_jobs`/`register_jobs` — `summarize_daily_job`를 add_job하는 블록과 같은 곳)에 cron 잡 추가:

```python
        self._scheduler.add_job(
            func=self.cleanup_price_snapshots_job,
            trigger="cron",
            hour=4,
            minute=30,
            id="cleanup_price_snapshots",
            name="가격 스냅샷 7일 정리",
            replace_existing=True,
        )
```

> 시각(04:30)은 양 시장 휴장대라 무난. `summarize_daily_job`의 add_job 호출부 바로 뒤에 둔다.

- [ ] **Step 6: 등록 회귀 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_scheduler/ -q`
Expected: all passed

- [ ] **Step 7: 커밋**

```bash
git add src/scheduler/jobs.py tests/test_scheduler/test_price_snapshot_cleanup.py
git commit -m "feat(scheduler): 가격 스냅샷 7일 롤링 정리 잡"
```

---

## Task 6: 대시보드 차트 데이터 구성(순수 함수) + 테스트

**Files:**
- Create: `dashboard/positions_data.py`
- Test: `tests/test_dashboard/test_positions_data.py`

차트 렌더(Streamlit/Altair)는 수동 확인하고, **데이터 구성 로직만 순수 함수로 분리해 테스트**한다.

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_dashboard/test_positions_data.py`:
```python
"""positions 차트 데이터 구성 테스트."""

from __future__ import annotations

import pandas as pd

from dashboard.positions_data import build_reference_levels


def test_reference_levels_computes_stop_take() -> None:
    levels = build_reference_levels(
        avg_price=100.0, peak_price=120.0,
        max_loss_rate=0.03, take_profit_ratio=0.05,
    )
    assert levels["평단가"] == 100.0
    assert levels["손절선"] == 97.0   # 100*(1-0.03)
    assert levels["익절선"] == 105.0  # 100*(1+0.05)
    assert levels["peak"] == 120.0


def test_reference_levels_omits_peak_when_none() -> None:
    levels = build_reference_levels(
        avg_price=100.0, peak_price=None,
        max_loss_rate=0.03, take_profit_ratio=0.05,
    )
    assert "peak" not in levels


def test_markers_dataframe_from_trades() -> None:
    from dashboard.positions_data import build_markers_df

    trades = pd.DataFrame({
        "traded_at": pd.to_datetime(["2026-06-18 10:00", "2026-06-18 12:00"]),
        "price": [98.0, 103.0],
        "trade_type": ["BUY", "SELL"],
        "quantity": [10, 10],
    })
    markers = build_markers_df(trades)
    assert list(markers["marker"]) == ["▲", "▼"]
    assert markers.loc[markers["trade_type"] == "BUY", "price"].iloc[0] == 98.0
```

- [ ] **Step 2: 실패 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_dashboard/test_positions_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.positions_data'`

(필요 시 `tests/test_dashboard/__init__.py` 빈 파일 생성.)

- [ ] **Step 3: 순수 함수 구현**

Create `dashboard/positions_data.py`:
```python
"""positions 페이지 차트 데이터 구성(순수 함수 — 렌더와 분리해 테스트 가능)."""

from __future__ import annotations

import pandas as pd


def build_reference_levels(
    avg_price: float,
    peak_price: float | None,
    max_loss_rate: float,
    take_profit_ratio: float,
) -> dict[str, float]:
    """차트 수평 기준선 값들을 계산한다(평단가·손절선·익절선·peak)."""
    levels: dict[str, float] = {
        "평단가": avg_price,
        "손절선": avg_price * (1.0 - max_loss_rate),
        "익절선": avg_price * (1.0 + take_profit_ratio),
    }
    if peak_price is not None and peak_price > 0:
        levels["peak"] = peak_price
    return levels


def build_markers_df(trades: pd.DataFrame) -> pd.DataFrame:
    """trades(traded_at, price, trade_type, quantity)를 차트 마커 DataFrame으로.

    매수=▲, 매도=▼.
    """
    if trades.empty:
        return pd.DataFrame(columns=["traded_at", "price", "trade_type", "quantity", "marker"])
    out = trades.copy()
    out["marker"] = out["trade_type"].map(lambda t: "▲" if t == "BUY" else "▼")
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest tests/test_dashboard/test_positions_data.py -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add dashboard/positions_data.py tests/test_dashboard/test_positions_data.py
git commit -m "feat(dashboard): positions 차트 데이터 구성 순수 함수 + 테스트"
```

---

## Task 7: 대시보드 positions 페이지(렌더) + 배선 검증

**Files:**
- Create: `dashboard/pages/positions.py`

렌더 코드는 자동 테스트 대신 import 가능성·구조를 검증하고 수동 확인.

- [ ] **Step 1: 페이지 구현**

Create `dashboard/pages/positions.py` (기존 `dashboard/pages/risk.py`의 DB 접근 패턴 — `@st.cache_resource` + `create_engine` + `text` + `pd.read_sql` — 을 따른다):
```python
"""보유종목 실시간 가격 vs 매수가 비교 차트 페이지."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

from dashboard.positions_data import build_markers_df, build_reference_levels

DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost/kis_trader")


@st.cache_resource
def get_engine():  # type: ignore[no-untyped-def]
    return create_engine(DB_URL, pool_pre_ping=True)


def load_holdings() -> pd.DataFrame:
    """현재 보유종목(portfolios, 수량>0)."""
    query = text(
        """
        SELECT p.stock_code, s.name AS stock_name, p.market, p.currency,
               p.quantity, p.avg_price, p.current_price, p.peak_price
        FROM portfolios p
        LEFT JOIN stocks s ON s.code = p.stock_code
        WHERE p.quantity > 0
        ORDER BY p.market, p.stock_code
        """
    )
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn)


def load_snapshots(stock_code: str, days: int) -> pd.DataFrame:
    since = datetime.now(UTC) - timedelta(days=days)
    query = text(
        """
        SELECT captured_at, price
        FROM price_snapshots
        WHERE stock_code = :code AND captured_at >= :since
        ORDER BY captured_at
        """
    )
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"code": stock_code, "since": since})


def load_trade_markers(stock_code: str, days: int) -> pd.DataFrame:
    since = datetime.now(UTC) - timedelta(days=days)
    query = text(
        """
        SELECT traded_at, price, trade_type, quantity
        FROM trades
        WHERE stock_code = :code AND traded_at >= :since
        ORDER BY traded_at
        """
    )
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"code": stock_code, "since": since})


st.title("\U0001f4c8 보유종목 가격 vs 매수가")

holdings = load_holdings()
if holdings.empty:
    st.info("현재 보유 종목이 없습니다.")
    st.stop()

# 보유 요약 표
summary = holdings.copy()
summary["손익률%"] = (
    (summary["current_price"] - summary["avg_price"]) / summary["avg_price"] * 100.0
).round(2)
st.dataframe(
    summary[["stock_code", "stock_name", "market", "quantity",
             "avg_price", "current_price", "손익률%"]],
    use_container_width=True,
)

# 종목 선택
codes = holdings["stock_code"].tolist()
selected = st.selectbox("종목 선택", codes)
row = holdings[holdings["stock_code"] == selected].iloc[0]
days = st.selectbox("기간(일)", [1, 3, 7], index=2)

snaps = load_snapshots(selected, days)
if snaps.empty:
    st.info("아직 수집된 가격 스냅샷이 없습니다(장 시작 후 수집됩니다).")
    st.stop()

# settings에서 손절/익절 비율
try:
    from src.config import settings
    max_loss_rate = settings.trading.max_loss_rate
    take_profit_ratio = settings.strategy.take_profit_ratio
except Exception:
    max_loss_rate, take_profit_ratio = 0.03, 0.05

levels = build_reference_levels(
    avg_price=float(row["avg_price"]),
    peak_price=float(row["peak_price"]) if pd.notna(row["peak_price"]) else None,
    max_loss_rate=max_loss_rate,
    take_profit_ratio=take_profit_ratio,
)

# 통화 라벨
cur = row["currency"]
unit = "$" if cur == "USD" else "₩"

# 가격 line
price_line = (
    alt.Chart(snaps)
    .mark_line(color="#2196F3")
    .encode(x=alt.X("captured_at:T", title="시각"), y=alt.Y("price:Q", title=f"가격({unit})", scale=alt.Scale(zero=False)))
)

# 수평 기준선
rule_rows = pd.DataFrame(
    [{"label": k, "value": v} for k, v in levels.items()]
)
color_map = {"평단가": "#9E9E9E", "손절선": "#F44336", "익절선": "#4CAF50", "peak": "#FF9800"}
rules = (
    alt.Chart(rule_rows)
    .mark_rule(strokeDash=[4, 4])
    .encode(
        y="value:Q",
        color=alt.Color("label:N", scale=alt.Scale(
            domain=list(color_map.keys()), range=list(color_map.values())), title="기준선"),
    )
)

# 체결 마커
markers = build_markers_df(load_trade_markers(selected, days))
layers = [price_line, rules]
if not markers.empty:
    marker_chart = (
        alt.Chart(markers)
        .mark_point(size=120, filled=True)
        .encode(
            x="traded_at:T",
            y="price:Q",
            shape=alt.Shape("trade_type:N", title="체결"),
            color=alt.Color("trade_type:N", scale=alt.Scale(
                domain=["BUY", "SELL"], range=["#E53935", "#1E88E5"])),
            tooltip=["traded_at:T", "trade_type:N", "price:Q", "quantity:Q"],
        )
    )
    layers.append(marker_chart)

pl_pct = (float(row["current_price"]) - float(row["avg_price"])) / float(row["avg_price"]) * 100.0
st.metric(
    f"{selected} 손익률",
    f"{pl_pct:+.2f}%",
    delta=f"현재 {unit}{float(row['current_price']):,.2f} / 평단 {unit}{float(row['avg_price']):,.2f}",
)
st.altair_chart(alt.layer(*layers).resolve_scale(y="shared").interactive(), use_container_width=True)
```

- [ ] **Step 2: import 검증**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -c "import ast; ast.parse(open('dashboard/pages/positions.py').read()); print('OK')"`
Expected: `OK` (문법 검증 — Streamlit 페이지는 `st.title` 등이 import-time 실행되므로 `import`로는 직접 검증 불가, ast.parse로 문법만 확인)

- [ ] **Step 3: altair 가용 확인**

Run: `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -c "import altair; print(altair.__version__)"`
Expected: 버전 출력(streamlit 번들 의존성). 만약 ModuleNotFoundError면 운영자 액션에 `pip install altair` 추가.

- [ ] **Step 4: 커밋**

```bash
git add dashboard/pages/positions.py
git commit -m "feat(dashboard): 보유종목 가격 vs 매수가 비교 페이지(Altair)"
```

---

## Task 8: 전체 검증 + 문서 + 운영자 액션

- [ ] **Step 1: 전체 게이트**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader/.claude/worktrees/us-stock-trading-impl
V=/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin
$V/python -m pytest tests/ -q
$V/python -m mypy src/
$V/ruff check src/db/models.py src/db/repository.py src/worker/handlers.py src/engine.py src/scheduler/jobs.py main.py
```
Expected: pytest all passed(신규 ~12건) · mypy Success · ruff clean(변경분).

- [ ] **Step 2: 버전 bump + CHANGELOG** — `pyproject.toml` version `0.20.0` → `0.21.0`. `docs/CHANGELOG.md` 상단에 신규 엔트리 추가 + 가장 오래된 엔트리 제거(rolling 5). `scripts/record_implementation.py` 실행(DB 기록).

- [ ] **Step 3: README 업데이트** — DB 스키마 섹션에 `price_snapshots` 추가, 대시보드 페이지 목록에 positions 추가.

- [ ] **Step 4: 커밋 + 푸시 + PR**

```bash
git add -A && git commit -m "chore: v0.21.0 — 보유종목 가격 차트 (CHANGELOG/README/version)"
git push -u origin feat/positions-realtime-chart
gh pr create --base main --title "feat: 보유종목 실시간 가격 vs 매수가 비교 차트 (v0.21.0)" --body "..."
```

- [ ] **운영자 액션(PR 머지 후):**
  1. main pull
  2. `alembic upgrade head` (price_snapshots 테이블 생성) — **DB 변경 있음**
  3. `com.kis.autotrader`·`com.kis.autotrader.us` 재시작(스냅샷 수집·정리 잡 시작)
  4. 대시보드에 altair 없으면 `pip install altair`(보통 streamlit과 함께 설치됨)
  5. 대시보드 positions 페이지 확인(장중 ~10초 단위로 스냅샷 누적)

---

## Self-Review 체크

- **Spec 커버리지**: §3 모델→Task1, §4 쓰기→Task3·4, §5 읽기/UI→Task6·7, §6 보존→Task5, §7 모듈경계→파일구조 일치. 전 항목 태스크 존재.
- **타입 일관성**: `PriceSnapshot`(model)·`PriceSnapshotRepository.add(stock_code,market,currency,price,captured_at)`·핸들러 payload 키(stock_code/market/currency/price)·엔진 enqueue payload·대시보드 쿼리 컬럼 모두 일치.
- **비범위 준수**: 웹소켓·평단가 계단선·알림·일봉 백필 제외(스펙 §9).
- **운영자 액션 분리**: alembic·재시작은 운영자 단계로 명시([[feedback_pr_split_policy]] — DB 변경 동반이라 PR 1건이되 운영자 액션 문서화).
</content>
