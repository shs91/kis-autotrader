"""체결 확인 후 기록(record-on-fill) 테스트.

주문 접수(order_no 수령)와 실제 체결을 구분: 미체결이면 트레이드/알림을 보류하고,
체결되면 실제 체결가/수량으로 기록한다. (유령 트레이드/오알림 방지)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.account import Execution
from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    return engine


def _order_result(order_no: str = "0000013289") -> MagicMock:
    r = MagicMock()
    r.order_no = order_no
    return r


def _fill(stock_code: str, qty: int, price: int, order_no: str = "0000013289") -> Execution:
    return Execution(
        order_date="20260522", order_time="100757", stock_code=stock_code,
        stock_name="테스트", side="매수", quantity=qty, price=price,
        amount=qty * price, order_no=order_no,
    )


def _telegram_payloads(enqueue: MagicMock, notify_type: str) -> list[dict]:
    out = []
    for call in enqueue.call_args_list:
        kw = call.kwargs
        if kw.get("task_type") == "telegram_notify" and \
                (kw.get("payload") or {}).get("notify_type") == notify_type:
            out.append(kw["payload"]["message_data"])
    return out


# ── 매수 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_buy_records_on_fill_with_real_price() -> None:
    """체결되면 실제 체결가/수량으로 트레이드 기록 + 매수 알림."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(return_value=_order_result())
    engine._confirm_fill = AsyncMock(return_value=_fill("069540", 147, 6610))  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_screening_match_metric = MagicMock()  # type: ignore[method-assign]

    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_buy("069540", "빛과전자", 147, 6610)

    engine._record_trade_to_db.assert_called_once()
    args = engine._record_trade_to_db.call_args
    assert args.args[3] == 147 and args.args[4] == 6610  # qty, price
    assert _telegram_payloads(enq, "buy")  # 매수 알림 발송됨
    assert engine._today_trade_count == 1


@pytest.mark.asyncio
async def test_buy_unfilled_no_trade_no_alert() -> None:
    """미체결이면 트레이드 기록·알림을 보류하고 ORDER_UNFILLED 메트릭만 남긴다."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(return_value=_order_result())
    engine._confirm_fill = AsyncMock(return_value=None)  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_metric = MagicMock()  # type: ignore[method-assign]

    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_buy("069540", "빛과전자", 147, 6610)

    engine._record_trade_to_db.assert_not_called()
    assert not _telegram_payloads(enq, "buy")
    assert engine._today_trade_count == 0
    metrics = [c.args[0] for c in engine._record_metric.call_args_list]
    assert "ORDER_UNFILLED" in metrics


# ── 매도 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sell_records_on_fill_with_real_price() -> None:
    """체결되면 실제 체결가/수량으로 트레이드 기록 + 매도 알림 + 고점 정리."""
    engine = _make_engine()
    engine._peak_prices = {"760027": 4535.0}
    engine._order.sell = AsyncMock(return_value=_order_result("0000000712"))
    engine._confirm_fill = AsyncMock(  # type: ignore[method-assign]
        return_value=_fill("760027", 942, 4500, "0000000712")
    )
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_sell("760027", 942, 0, reason="손절", avg_price=3565.0)

    engine._record_trade_to_db.assert_called_once()
    args = engine._record_trade_to_db.call_args
    assert args.args[3] == 942 and args.args[4] == 4500  # 실제 체결 수량/가격
    assert _telegram_payloads(enq, "sell")
    assert "760027" not in engine._peak_prices  # 청산 후 고점 정리


@pytest.mark.asyncio
async def test_sell_unfilled_no_trade_keeps_peak() -> None:
    """미체결이면 트레이드/알림 보류 + 고점 추적 유지(아직 보유)."""
    engine = _make_engine()
    engine._peak_prices = {"760027": 4535.0}
    engine._order.sell = AsyncMock(return_value=_order_result("0000000712"))
    engine._confirm_fill = AsyncMock(return_value=None)  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_metric = MagicMock()  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_sell("760027", 942, 0, reason="손절", avg_price=3565.0)

    engine._record_trade_to_db.assert_not_called()
    assert not _telegram_payloads(enq, "sell")
    assert engine._peak_prices.get("760027") == 4535.0  # 고점 유지
    assert "ORDER_UNFILLED" in [c.args[0] for c in engine._record_metric.call_args_list]


# ── _confirm_fill 폴링 ────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_fill_returns_fill_when_eventually_filled() -> None:
    """첫 조회 미체결이어도 재시도 중 체결되면 반환한다."""
    engine = _make_engine()
    engine._account.get_fill = AsyncMock(side_effect=[None, _fill("069540", 147, 6610)])
    with patch("src.engine.asyncio.sleep", new=AsyncMock()):
        fill = await engine._confirm_fill("0000013289", retries=3, delay=0.0)
    assert fill is not None and fill.price == 6610


@pytest.mark.asyncio
async def test_confirm_fill_returns_none_after_retries() -> None:
    """끝까지 미체결이면 None."""
    engine = _make_engine()
    engine._account.get_fill = AsyncMock(return_value=None)
    with patch("src.engine.asyncio.sleep", new=AsyncMock()):
        fill = await engine._confirm_fill("x", retries=3, delay=0.0)
    assert fill is None
    assert engine._account.get_fill.await_count == 3


@pytest.mark.asyncio
async def test_confirm_fill_swallows_query_error() -> None:
    """체결 조회가 예외를 던져도 흐름을 막지 않고 None 처리한다."""
    engine = _make_engine()
    engine._account.get_fill = AsyncMock(side_effect=Exception("api down"))
    with patch("src.engine.asyncio.sleep", new=AsyncMock()):
        fill = await engine._confirm_fill("x", retries=2, delay=0.0)
    assert fill is None
