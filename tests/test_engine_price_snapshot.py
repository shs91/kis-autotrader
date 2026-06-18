"""엔진 보유종목 가격 스냅샷 enqueue 테스트."""

from __future__ import annotations

from unittest.mock import patch

from src.engine import TradingEngine
from src.market.profile import US_PROFILE


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
    assert kwargs["priority"] == 0  # 최저 우선순위 회귀 가드
    payload = kwargs["payload"]
    assert payload["stock_code"] == "005930"
    assert payload["market"] == "KRX"
    assert payload["currency"] == "KRW"
    assert payload["price"] == 70123  # KRX 정수 정규화


def test_enqueue_price_snapshot_ignores_none_return() -> None:
    """enqueue가 None을 반환해도(큐 가득참 등) 헬퍼는 정상 반환해야 한다."""
    engine = _make_engine()
    with patch.object(engine._task_queue, "enqueue", return_value=None) as mock_enq:
        # 반환값(None)에 의존하지 않고 정상 반환해야 한다.
        result = engine._enqueue_price_snapshot("005930", 70123.0)
    assert result is None
    mock_enq.assert_called_once()


def test_enqueue_price_snapshot_us_normalization() -> None:
    """US 프로파일에서 소수점 2자리 보존·시장/통화 필드 검증."""
    engine = _make_engine()
    engine._market = US_PROFILE  # KRX → US 교체

    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_price_snapshot("AAPL", 123.456)

    mock_enq.assert_called_once()
    kwargs = mock_enq.call_args.kwargs
    payload = kwargs["payload"]
    assert payload["stock_code"] == "AAPL"
    assert payload["market"] == "US"
    assert payload["currency"] == "USD"
    assert payload["price"] == 123.46  # 소수점 2자리 HALF_UP 반올림
    assert kwargs["priority"] == 0
