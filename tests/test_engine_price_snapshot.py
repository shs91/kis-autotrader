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
