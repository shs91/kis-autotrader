"""트레일링 스톱 + 마감 게이트 엔진 통합 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._risk.is_near_market_close = lambda *a, **kw: False  # type: ignore[method-assign]
    return engine


def test_peak_prices_initialized_empty() -> None:
    engine = _make_engine()
    assert engine._peak_prices == {}


def test_enqueue_sync_portfolio_includes_peak_price() -> None:
    engine = _make_engine()
    engine._peak_prices = {"760027": 5000.0}
    balance = MagicMock()
    h = MagicMock()
    h.stock_code = "760027"
    h.stock_name = "ETN"
    h.quantity = 100
    h.avg_price = 3565.0
    h.current_price = 4535.0
    balance.holdings = [h]
    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_sync_portfolio(balance)
        payload = mock_enq.call_args.kwargs["payload"]
        assert payload["holdings"][0]["peak_price"] == 5000.0


def test_enqueue_sync_portfolio_peak_none_when_absent() -> None:
    engine = _make_engine()
    engine._peak_prices = {}
    balance = MagicMock()
    h = MagicMock()
    h.stock_code = "005930"
    h.stock_name = "삼성"
    h.quantity = 10
    h.avg_price = 70000.0
    h.current_price = 71000.0
    balance.holdings = [h]
    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_sync_portfolio(balance)
        payload = mock_enq.call_args.kwargs["payload"]
        assert payload["holdings"][0]["peak_price"] is None
