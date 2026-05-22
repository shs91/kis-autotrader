"""PortfolioRepository peak_price 영속/조회 검증."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.db.repository import PortfolioRepository, StockRepository


@pytest.fixture()
def session() -> Session:
    """SQLite in-memory 세션을 생성한다.

    JSONB 컬럼을 SQLite에서도 동작하도록 JSON으로 렌더링한다.
    """
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess  # type: ignore[misc]
    sess.close()
    engine.dispose()


def test_upsert_persists_peak_price(session: Session) -> None:
    stock = StockRepository(session).create("760027", "ETN", "KOSPI")
    repo = PortfolioRepository(session)
    repo.upsert(stock_id=stock.id, quantity=100, avg_price=3565.0,
                current_price=4535.0, peak_price=5000.0)
    p = repo.get_by_stock(stock.id)
    assert p is not None
    assert p.peak_price == 5000.0


def test_upsert_update_preserves_existing_peak_when_none(session: Session) -> None:
    stock = StockRepository(session).create("760027", "ETN", "KOSPI")
    repo = PortfolioRepository(session)
    repo.upsert(stock_id=stock.id, quantity=100, avg_price=3565.0,
                current_price=4535.0, peak_price=5000.0)
    # 이후 갱신에서 peak_price 미지정(None) → 기존 고점 보존
    repo.upsert(stock_id=stock.id, quantity=100, avg_price=3565.0,
                current_price=4600.0)
    p = repo.get_by_stock(stock.id)
    assert p is not None
    assert p.peak_price == 5000.0


def test_get_peak_prices_returns_code_map(session: Session) -> None:
    stock = StockRepository(session).create("760027", "ETN", "KOSPI")
    repo = PortfolioRepository(session)
    repo.upsert(stock_id=stock.id, quantity=100, avg_price=3565.0,
                current_price=4535.0, peak_price=5000.0)
    assert repo.get_peak_prices() == {"760027": 5000.0}


def test_get_peak_prices_skips_null(session: Session) -> None:
    stock = StockRepository(session).create("005930", "삼성", "KOSPI")
    repo = PortfolioRepository(session)
    repo.upsert(stock_id=stock.id, quantity=10, avg_price=70000.0,
                current_price=71000.0)  # peak_price 미지정 → NULL
    assert repo.get_peak_prices() == {}
