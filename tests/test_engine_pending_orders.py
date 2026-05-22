"""미체결 주문 추적·중복 억제·잔류 정리 테스트.

주문 접수 후 미체결이면 PendingOrder로 추적한다. 동일 종목 신규 주문은 타임아웃
이내면 억제, 타임아웃 초과면 기존 주문 취소 후 재주문. 사이클마다 오래된 미체결을
취소하고, 장 마감에 전부 취소한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine import PendingOrder, TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._record_metric = MagicMock()  # type: ignore[method-assign]
    return engine


def _pending(order_no: str, side: str, qty: int, cycle: int) -> PendingOrder:
    return PendingOrder(order_no=order_no, side=side, quantity=qty,
                        placed_cycle=cycle, stock_name="테스트")


def test_config_default_timeout() -> None:
    from src.config import StrategyConfig
    assert StrategyConfig().order_pending_timeout_cycles == 3


# ── 중복 억제 / 취소-재주문 ───────────────────────────

@pytest.mark.asyncio
async def test_suppress_within_timeout() -> None:
    """타임아웃 이내 미체결 주문이 있으면 신규 주문을 억제한다."""
    engine = _make_engine()
    engine._cycle_count = 11
    engine._pending_orders["069540"] = _pending("A1", "BUY", 147, 10)  # age 1 < 3
    engine._order.cancel = AsyncMock()
    suppress = await engine._suppress_or_replace_pending("069540", "BUY")
    assert suppress is True
    engine._order.cancel.assert_not_awaited()
    assert "069540" in engine._pending_orders


@pytest.mark.asyncio
async def test_replace_after_timeout() -> None:
    """타임아웃 초과 미체결 주문은 취소하고 신규 주문을 허용한다."""
    engine = _make_engine()
    engine._cycle_count = 14
    engine._pending_orders["069540"] = _pending("A1", "BUY", 147, 10)  # age 4 >= 3
    engine._order.cancel = AsyncMock()
    suppress = await engine._suppress_or_replace_pending("069540", "BUY")
    assert suppress is False
    engine._order.cancel.assert_awaited_once()
    assert "069540" not in engine._pending_orders


@pytest.mark.asyncio
async def test_no_pending_proceeds() -> None:
    engine = _make_engine()
    engine._cycle_count = 5
    assert await engine._suppress_or_replace_pending("005930", "BUY") is False


# ── 정리 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_cancels_only_stale() -> None:
    """사이클 정리는 타임아웃 초과 미체결만 취소한다."""
    engine = _make_engine()
    engine._cycle_count = 13
    engine._pending_orders = {
        "069540": _pending("A1", "BUY", 147, 9),    # age 4 >= 3 → 취소
        "005930": _pending("B2", "SELL", 10, 12),   # age 1 < 3 → 유지
    }
    engine._order.cancel = AsyncMock()
    await engine._cleanup_stale_pending_orders()
    engine._order.cancel.assert_awaited_once()
    assert "069540" not in engine._pending_orders
    assert "005930" in engine._pending_orders


@pytest.mark.asyncio
async def test_cancel_all_pending() -> None:
    """마감 정리는 미체결 전부 취소한다."""
    engine = _make_engine()
    engine._pending_orders = {
        "069540": _pending("A1", "BUY", 147, 9),
        "005930": _pending("B2", "SELL", 10, 12),
    }
    engine._order.cancel = AsyncMock()
    await engine._cancel_all_pending_orders()
    assert engine._order.cancel.await_count == 2
    assert engine._pending_orders == {}


@pytest.mark.asyncio
async def test_cancel_failure_still_removes() -> None:
    """취소 API 실패해도 추적에서 제거한다(흐름 유지)."""
    engine = _make_engine()
    engine._pending_orders["069540"] = _pending("A1", "BUY", 147, 9)
    engine._order.cancel = AsyncMock(side_effect=Exception("cancel fail"))
    await engine._cancel_all_pending_orders()
    assert engine._pending_orders == {}


# ── _execute_buy 통합: 등록 / 해제 / 억제 ──────────────

@pytest.mark.asyncio
async def test_buy_unfilled_registers_pending() -> None:
    engine = _make_engine()
    engine._cycle_count = 7
    r = MagicMock()
    r.order_no = "ODNO1"
    engine._order.buy = AsyncMock(return_value=r)
    engine._confirm_fill = AsyncMock(return_value=0)  # 미체결  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_holding_quantity", new=AsyncMock(return_value=0)), \
         patch.object(engine._task_queue, "enqueue"):
        await engine._execute_buy("069540", "빛과전자", 147, 6610)
    p = engine._pending_orders.get("069540")
    assert p is not None and p.order_no == "ODNO1" and p.placed_cycle == 7


@pytest.mark.asyncio
async def test_buy_filled_clears_pending() -> None:
    engine = _make_engine()
    engine._pending_orders["069540"] = _pending("OLD", "BUY", 147, 1)
    r = MagicMock()
    r.order_no = "ODNO2"
    engine._order.buy = AsyncMock(return_value=r)
    engine._confirm_fill = AsyncMock(return_value=147)  # 체결  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_screening_match_metric = MagicMock()  # type: ignore[method-assign]
    # 억제되지 않도록 cycle을 타임아웃 초과로(취소-재주문 경로) 두고 cancel 모킹
    engine._cycle_count = 10
    engine._order.cancel = AsyncMock()
    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_holding_quantity", new=AsyncMock(return_value=0)), \
         patch.object(engine._task_queue, "enqueue"):
        await engine._execute_buy("069540", "빛과전자", 147, 6610)
    assert "069540" not in engine._pending_orders


@pytest.mark.asyncio
async def test_execute_buy_suppressed_does_not_order() -> None:
    """억제 시 주문 자체를 내지 않는다."""
    engine = _make_engine()
    engine._cycle_count = 11
    engine._pending_orders["069540"] = _pending("A1", "BUY", 147, 10)  # age 1 < 3
    engine._order.buy = AsyncMock()
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("069540", "빛과전자", 147, 6610)
    engine._order.buy.assert_not_awaited()
