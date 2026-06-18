"""price_snapshots 모델·repository 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import PriceSnapshot


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    # price_snapshots 테이블만 생성 (Base 전체는 JSONB 의존으로 SQLite 불가)
    PriceSnapshot.__table__.create(engine)
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
