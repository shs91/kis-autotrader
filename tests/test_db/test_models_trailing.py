"""트레일링 관련 모델 변경 검증."""

from __future__ import annotations

from src.db.models import Portfolio, SellReason


def test_sell_reason_has_trailing_and_market_close() -> None:
    assert SellReason.TRAILING_STOP.value == "TRAILING_STOP"
    assert SellReason.MARKET_CLOSE.value == "MARKET_CLOSE"


def test_portfolio_has_peak_price_column() -> None:
    assert "peak_price" in Portfolio.__table__.columns
    assert Portfolio.__table__.columns["peak_price"].nullable is True
