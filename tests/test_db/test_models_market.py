"""멀티마켓 컬럼(market/currency) 모델 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Numeric, create_engine
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


# ── P3c-3: 가격/금액 Numeric(18,4) 전환 ──────────────────────


def test_trade_price_columns_are_numeric() -> None:
    cols = Trade.__table__.columns
    assert isinstance(cols["price"].type, Numeric)
    assert isinstance(cols["total_amount"].type, Numeric)
    assert isinstance(cols["profit_loss_amount"].type, Numeric)
    assert cols["price"].type.precision == 18
    assert cols["price"].type.scale == 4


def test_trade_preserves_us_cents() -> None:
    engine = create_engine("sqlite:///:memory:")
    Trade.__table__.create(engine)
    with Session(engine) as s:
        t = Trade(
            stock_code="AAPL",
            stock_name="AAPL",
            market="US",
            currency="USD",
            trade_type=TradeType.SELL,
            quantity=3,
            price=150.25,
            total_amount=450.75,
            profit_loss_amount=12.34,
            cycle_number=0,
            traded_at=datetime.now(UTC),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        # 센트(소수 둘째 자리) 무손실 보존 + float 읽기(asdecimal=False)
        assert t.price == 150.25
        assert t.total_amount == 450.75
        assert t.profit_loss_amount == 12.34
        assert isinstance(t.price, float)


def test_trade_krx_integer_roundtrip() -> None:
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
        # KRX 정수값 무손실(70000.0 == 70000)
        assert t.price == 70000
        assert t.total_amount == 70000
