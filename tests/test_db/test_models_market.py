"""멀티마켓 컬럼(market/currency) 모델 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import (
    Portfolio,
    ScreeningResult,
    Signal,
    Trade,
    TradeType,
)


def test_models_have_market_columns() -> None:
    assert "market" in Trade.__table__.columns
    assert "currency" in Trade.__table__.columns
    assert "market" in Portfolio.__table__.columns
    assert "currency" in Portfolio.__table__.columns
    assert "market" in Signal.__table__.columns
    assert "market" in ScreeningResult.__table__.columns


def test_trade_market_currency_explicit() -> None:
    engine = create_engine("sqlite:///:memory:")
    Trade.__table__.create(engine)
    with Session(engine) as s:
        t = Trade(
            stock_code="AAPL",
            stock_name="Apple",
            market="US",
            currency="USD",
            trade_type=TradeType.BUY,
            quantity=1,
            price=150,
            total_amount=150,
            cycle_number=0,
            traded_at=datetime.now(UTC),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        assert t.market == "US"
        assert t.currency == "USD"


def test_trade_market_defaults_to_krx() -> None:
    engine = create_engine("sqlite:///:memory:")
    Trade.__table__.create(engine)
    with Session(engine) as s:
        t = Trade(
            stock_code="005930",
            stock_name="삼성전자",
            trade_type=TradeType.BUY,
            quantity=1,
            price=70000,
            total_amount=70000,
            cycle_number=0,
            traded_at=datetime.now(UTC),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        assert t.market == "KRX"  # server_default
        assert t.currency == "KRW"
