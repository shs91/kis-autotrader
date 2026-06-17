"""TradingEngine 멀티마켓 생성 구조 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.engine import TradingEngine


def test_default_engine_is_krx() -> None:
    e = TradingEngine()
    assert e._market.market_code == "KRX"
    assert str(e._tz) == "Asia/Seoul"


def test_create_for_market_krx() -> None:
    e = TradingEngine.create_for_market("KRX")
    assert e._market.market_code == "KRX"
    assert str(e._tz) == "Asia/Seoul"


def test_create_for_market_us_profile_and_tz() -> None:
    e = TradingEngine.create_for_market("US")
    assert e._market.market_code == "US"
    assert str(e._tz) == "America/New_York"


def test_injected_providers_used() -> None:
    q = MagicMock()
    e = TradingEngine(quote=q)
    assert e._quote is q
