"""체결 확인 후 기록(record-on-fill) 테스트 — 잔고 변동 기반.

모의투자 일별주문체결조회가 당일 체결 자료를 주지 않으므로, 체결 확인은 주문 전후
보유 수량 변화(get_balance)로 판정한다. 미체결이면 트레이드/알림을 보류한다.
(유령 트레이드/오알림 방지)
"""

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
    return engine


def _order_result(order_no: str = "0000013289") -> MagicMock:
    r = MagicMock()
    r.order_no = order_no
    return r


def _balance(holdings: dict[str, int]) -> MagicMock:
    """{종목코드: 수량} → Balance mock."""
    bal = MagicMock()
    hs = []
    for code, qty in holdings.items():
        h = MagicMock()
        h.stock_code = code
        h.quantity = qty
        hs.append(h)
    bal.holdings = hs
    return bal


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
async def test_buy_records_when_holding_increases() -> None:
    """주문 후 보유 수량이 늘면 체결로 보고 기록 + 매수 알림."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(return_value=_order_result())
    # 주문 전 0주(force=False) → 주문 후 147주(force=True)
    engine._get_balance = AsyncMock(side_effect=[  # type: ignore[method-assign]
        _balance({}), _balance({"069540": 147}),
    ])
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_screening_match_metric = MagicMock()  # type: ignore[method-assign]

    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_buy("069540", "빛과전자", 147, 6610)

    engine._record_trade_to_db.assert_called_once()
    args = engine._record_trade_to_db.call_args
    assert args.args[3] == 147 and args.args[4] == 6610  # 체결수량(증가분), 현재가
    assert _telegram_payloads(enq, "buy")
    assert engine._today_trade_count == 1


@pytest.mark.asyncio
async def test_buy_unfilled_no_trade_no_alert() -> None:
    """보유 수량이 그대로면 미체결 → 트레이드/알림 보류 + ORDER_UNFILLED."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(return_value=_order_result())
    # 주문 전후 모두 0주 (미체결)
    engine._get_balance = AsyncMock(return_value=_balance({}))  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_metric = MagicMock()  # type: ignore[method-assign]

    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch("src.engine.asyncio.sleep", new=AsyncMock()), \
         patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_buy("069540", "빛과전자", 147, 6610)

    engine._record_trade_to_db.assert_not_called()
    assert not _telegram_payloads(enq, "buy")
    assert engine._today_trade_count == 0
    assert "ORDER_UNFILLED" in [c.args[0] for c in engine._record_metric.call_args_list]


# ── 매도 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sell_records_when_holding_decreases() -> None:
    """주문 후 보유 수량이 줄면 체결로 보고 기록 + 매도 알림 + 고점 정리."""
    engine = _make_engine()
    engine._peak_prices = {"760027": 4535.0}
    engine._order.sell = AsyncMock(return_value=_order_result("0000000712"))
    # 주문 전 942주 → 주문 후 0주 (전량 체결)
    engine._get_balance = AsyncMock(side_effect=[  # type: ignore[method-assign]
        _balance({"760027": 942}), _balance({}),
    ])
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_sell("760027", 942, 4226, reason="손절", avg_price=3565.0)

    engine._record_trade_to_db.assert_called_once()
    args = engine._record_trade_to_db.call_args
    assert args.args[3] == 942 and args.args[4] == 4226  # 체결수량(감소분), 현재가
    assert _telegram_payloads(enq, "sell")
    assert "760027" not in engine._peak_prices


@pytest.mark.asyncio
async def test_sell_unfilled_no_trade_keeps_peak() -> None:
    """보유 수량이 그대로면 미체결 → 트레이드/알림 보류 + 고점 추적 유지."""
    engine = _make_engine()
    engine._peak_prices = {"760027": 4535.0}
    engine._order.sell = AsyncMock(return_value=_order_result("0000000712"))
    # 주문 전후 모두 942주 (미체결)
    engine._get_balance = AsyncMock(return_value=_balance({"760027": 942}))  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_metric = MagicMock()  # type: ignore[method-assign]

    with patch("src.engine.asyncio.sleep", new=AsyncMock()), \
         patch.object(engine._task_queue, "enqueue") as enq:
        await engine._execute_sell("760027", 942, 4226, reason="손절", avg_price=3565.0)

    engine._record_trade_to_db.assert_not_called()
    assert not _telegram_payloads(enq, "sell")
    assert engine._peak_prices.get("760027") == 4535.0
    assert "ORDER_UNFILLED" in [c.args[0] for c in engine._record_metric.call_args_list]


# ── _confirm_fill 폴링 (잔고 기반) ────────────────────

@pytest.mark.asyncio
async def test_confirm_fill_buy_detects_increase_after_retry() -> None:
    """첫 조회 미반영이어도 재시도 중 보유가 늘면 체결 수량 반환."""
    engine = _make_engine()
    engine._holding_quantity = AsyncMock(side_effect=[0, 147])  # type: ignore[method-assign]
    with patch("src.engine.asyncio.sleep", new=AsyncMock()):
        filled = await engine._confirm_fill("069540", "BUY", 0, retries=3, delay=0.0)
    assert filled == 147


@pytest.mark.asyncio
async def test_confirm_fill_returns_zero_when_no_change() -> None:
    """끝까지 보유 변화 없으면 0(미체결)."""
    engine = _make_engine()
    engine._holding_quantity = AsyncMock(return_value=942)  # type: ignore[method-assign]
    with patch("src.engine.asyncio.sleep", new=AsyncMock()):
        filled = await engine._confirm_fill("760027", "SELL", 942, retries=3, delay=0.0)
    assert filled == 0
    assert engine._holding_quantity.await_count == 3


@pytest.mark.asyncio
async def test_confirm_fill_swallows_balance_error() -> None:
    """잔고 조회가 예외를 던져도 흐름을 막지 않고 0(미체결) 처리."""
    engine = _make_engine()
    engine._holding_quantity = AsyncMock(side_effect=Exception("api down"))  # type: ignore[method-assign]
    with patch("src.engine.asyncio.sleep", new=AsyncMock()):
        filled = await engine._confirm_fill("760027", "SELL", 942, retries=2, delay=0.0)
    assert filled == 0
