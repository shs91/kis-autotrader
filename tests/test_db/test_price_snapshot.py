"""price_snapshots 모델·repository 테스트."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import PriceSnapshot


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    """SQLite in-memory 세션을 생성한다."""
    engine = create_engine("sqlite:///:memory:")
    # price_snapshots 테이블만 생성 (Base 전체는 JSONB 의존으로 SQLite 불가)
    PriceSnapshot.__table__.create(engine)
    sess = Session(engine)
    yield sess  # type: ignore[misc]
    sess.close()
    engine.dispose()


def test_price_snapshot_columns(session: Session) -> None:
    """명시적으로 전달한 컬럼 값이 DB에 저장된다."""
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
    assert snap.captured_at is not None


def test_price_snapshot_server_defaults(session: Session) -> None:
    """market/currency 생략 시 DB server_default('KRX'/'KRW')가 적용된다.

    SQLite는 DDL에 DEFAULT 절을 지원하므로 server_default가 실제로 동작한다.
    flush 후 session.refresh()로 DB 값을 재로드하여 검증한다.
    """
    snap = PriceSnapshot(
        stock_code="005930",
        price=70000.0,
        captured_at=datetime.now(UTC),
    )
    session.add(snap)
    session.flush()
    session.refresh(snap)
    assert snap.market == "KRX"
    assert snap.currency == "KRW"


def test_price_snapshot_captured_at_python_default(session: Session) -> None:
    """captured_at 생략 시 python default(datetime.now(UTC))가 자동 적용된다."""
    snap = PriceSnapshot(
        stock_code="AAPL",
        market="US",
        currency="USD",
        price=145.32,
    )
    session.add(snap)
    session.flush()
    assert snap.captured_at is not None


def test_price_snapshot_repr(session: Session) -> None:
    """PriceSnapshot의 repr이 stock_code와 id를 포함한다."""
    snap = PriceSnapshot(
        stock_code="AAPL",
        market="US",
        currency="USD",
        price=145.32,
        captured_at=datetime.now(UTC),
    )
    session.add(snap)
    session.flush()
    result = repr(snap)
    assert "AAPL" in result
    assert str(snap.id) in result
