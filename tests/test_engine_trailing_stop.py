"""트레일링 스톱 + 마감 게이트 엔진 통합 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _stub(engine: TradingEngine, price: int, name: str = "ETN") -> None:
    """현재가 응답을 스텁한다."""
    cur = MagicMock()
    cur.current_price = price
    cur.stock_name = name
    engine._quote.get_current_price = AsyncMock(return_value=cur)  # type: ignore[method-assign]


async def _run_held(
    engine: TradingEngine, code: str, avg: float, qty: int = 100
) -> AsyncMock:
    """보유 종목 처리 헬퍼 — _execute_sell 모의객체를 반환한다."""
    engine._get_daily_df = AsyncMock(return_value=None)  # type: ignore[method-assign]
    engine._execute_sell = AsyncMock()  # type: ignore[method-assign]
    with patch.object(engine._task_queue, "enqueue"), \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code=code, deposit=1_000_000, is_held=True,
            holding_info={"avg_price": avg, "quantity": qty},
        )
    return engine._execute_sell  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_trailing_fires_on_pullback() -> None:
    engine = _make_engine()
    engine._peak_prices = {"760027": 12_700.0}  # 고점 +27%
    _stub(engine, 12_000)  # 고점 대비 -5.5% → 트레일 발동
    sell = await _run_held(engine, "760027", 10_000.0)
    sell.assert_awaited_once()
    assert sell.call_args.kwargs["reason"] == "트레일링"


@pytest.mark.asyncio
async def test_trailing_not_fire_dead_zone() -> None:
    engine = _make_engine()
    engine._peak_prices = {"760027": 12_700.0}
    _stub(engine, 12_600)  # 고점 대비 -0.8% → 미발동
    sell = await _run_held(engine, "760027", 10_000.0)
    sell.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_close_gate_fires_on_profit() -> None:
    engine = _make_engine()
    engine._risk.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
    engine._peak_prices = {"760027": 10_200.0}  # 미무장(+2%)
    _stub(engine, 10_200)  # +2% >= 1.5% → 마감 게이트
    sell = await _run_held(engine, "760027", 10_000.0)
    sell.assert_awaited_once()
    assert sell.call_args.kwargs["reason"] == "마감청산"


@pytest.mark.asyncio
async def test_market_close_gate_excludes_loss_stop_loss_fires() -> None:
    engine = _make_engine()
    engine._risk.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
    engine._peak_prices = {"760027": 10_000.0}
    _stub(engine, 9_500)  # -5% 손실 → 게이트 제외, 손절(-3%) 발동
    sell = await _run_held(engine, "760027", 10_000.0)
    assert sell.call_args.kwargs["reason"] == "손절"


@pytest.mark.asyncio
async def test_stop_loss_priority_over_gate() -> None:
    engine = _make_engine()
    engine._risk.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
    engine._peak_prices = {"005930": 70_000.0}
    _stub(engine, 67_000, "삼성")  # -4.3% → 손절 우선
    sell = await _run_held(engine, "005930", 70_000.0)
    assert sell.call_args.kwargs["reason"] == "손절"


@pytest.mark.asyncio
async def test_take_profit_fallback_when_trailing_disabled() -> None:
    """TRAILING_STOP_ENABLED=false면 트레일링 대신 기존 고정 익절(+5%)이 발동한다."""
    from src.config import settings as _settings

    engine = _make_engine()
    engine._peak_prices = {"760027": 10_000.0}
    _stub(engine, 10_600)  # +6% >= 5% 익절선 (트레일링 비활성)
    original = _settings.strategy.trailing_stop_enabled
    object.__setattr__(_settings.strategy, "trailing_stop_enabled", False)
    try:
        sell = await _run_held(engine, "760027", 10_000.0)
    finally:
        object.__setattr__(_settings.strategy, "trailing_stop_enabled", original)
    sell.assert_awaited_once()
    assert sell.call_args.kwargs["reason"] == "익절"


@pytest.mark.asyncio
async def test_zero_price_skips_sell() -> None:
    """현재가 0(개장 직후 미체결 등)이면 손절이 오발동하지 않고 매도 평가를 스킵한다."""
    engine = _make_engine()
    engine._peak_prices = {"760027": 4_535.0}
    _stub(engine, 0)  # 비정상 시세 0 — 손실률 -100%로 손절 오발동하면 안 됨
    sell = await _run_held(engine, "760027", 3_565.0, qty=942)
    sell.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_price_skips_sell() -> None:
    """음수 시세도 매도 평가를 스킵한다."""
    engine = _make_engine()
    _stub(engine, -1)
    sell = await _run_held(engine, "760027", 3_565.0, qty=942)
    sell.assert_not_awaited()
