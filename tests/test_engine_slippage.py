"""실체결 슬리피지 계측 테스트(소액 실전 캘리브레이션용 FILL_SLIPPAGE 메트릭)."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._record_metric = MagicMock()  # type: ignore[method-assign]
    return engine


@contextmanager
def _force_flag(name: str, value: object):
    from src.config import settings

    original = getattr(settings.trading, name)
    object.__setattr__(settings.trading, name, value)
    try:
        yield
    finally:
        object.__setattr__(settings.trading, name, original)


# ── _record_fill_slippage 계산 ─────────────────────────

def test_buy_slippage_adverse_when_paid_more() -> None:
    engine = _make_engine()
    engine._record_fill_slippage("BUY", "005930", 70000.0, 70140.0, 3)
    engine._record_metric.assert_called_once()
    mtype, payload = engine._record_metric.call_args[0]
    assert mtype == "FILL_SLIPPAGE"
    assert payload["side"] == "BUY"
    assert payload["slippage_bps"] == 20.0
    assert payload["adverse_bps"] == 20.0  # 더 비싸게 매수 = 비용
    assert payload["expected"] == 70000
    assert payload["realized"] == 70140.0


def test_sell_slippage_adverse_when_sold_lower() -> None:
    engine = _make_engine()
    engine._record_fill_slippage("SELL", "005930", 70000.0, 69860.0, 3)
    payload = engine._record_metric.call_args[0][1]
    assert payload["slippage_bps"] == -20.0
    assert payload["adverse_bps"] == 20.0  # 더 싸게 매도 = 비용


def test_slippage_favorable_negative_adverse() -> None:
    engine = _make_engine()
    engine._record_fill_slippage("BUY", "005930", 70000.0, 69930.0, 1)  # 더 싸게 매수
    payload = engine._record_metric.call_args[0][1]
    assert payload["adverse_bps"] == -10.0  # 비용 음수(유리)


def test_slippage_disabled_no_record() -> None:
    engine = _make_engine()
    with _force_flag("measure_fill_slippage", False):
        engine._record_fill_slippage("BUY", "005930", 70000.0, 70140.0, 1)
    engine._record_metric.assert_not_called()


def test_slippage_skips_invalid_prices() -> None:
    engine = _make_engine()
    engine._record_fill_slippage("BUY", "005930", 0.0, 70000.0, 1)
    engine._record_fill_slippage("BUY", "005930", 70000.0, 0.0, 1)
    engine._record_metric.assert_not_called()


# ── 실체결가 조회 헬퍼 ─────────────────────────────────

@pytest.mark.asyncio
async def test_holding_avg_price_reads_cached_balance() -> None:
    engine = _make_engine()
    bal = MagicMock()
    bal.holdings = [SimpleNamespace(stock_code="005930", avg_price=70150.0)]
    engine._get_balance = AsyncMock(return_value=bal)  # type: ignore[method-assign]
    assert await engine._holding_avg_price("005930") == 70150.0
    assert await engine._holding_avg_price("000660") == 0.0


@pytest.mark.asyncio
async def test_realized_price_via_executions() -> None:
    engine = _make_engine()
    e1 = SimpleNamespace(order_no="O1", stock_code="005930", price=69900)
    e2 = SimpleNamespace(order_no="O2", stock_code="005930", price=69800)
    engine._account.get_executions = AsyncMock(return_value=[e1, e2])
    assert await engine._realized_price_via_executions("005930", "O2") == 69800.0
    # order_no 미매칭 → 종목 최근 체결 폴백
    assert await engine._realized_price_via_executions("005930", "X") == 69800.0
    # 체결 없음 → None
    engine._account.get_executions = AsyncMock(return_value=[])
    assert await engine._realized_price_via_executions("005930", "O1") is None
    # 예외 → None
    engine._account.get_executions = AsyncMock(side_effect=Exception("api down"))
    assert await engine._realized_price_via_executions("005930", "O1") is None


# ── 매수 흐름 통합 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_buy_flow_records_slippage_for_new_position() -> None:
    engine = _make_engine()
    r = MagicMock()
    r.order_no = "ODNO"
    engine._order.buy = AsyncMock(return_value=r)
    engine._confirm_fill = AsyncMock(return_value=3)  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_screening_match_metric = MagicMock()  # type: ignore[method-assign]
    engine._holding_avg_price = AsyncMock(return_value=70140.0)  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_check_disclosure_risk_block", return_value=None), \
         patch.object(engine, "_holding_quantity", new=AsyncMock(return_value=0)), \
         patch.object(engine._task_queue, "enqueue"), patch("src.engine.log_trade"):
        await engine._execute_buy("005930", "삼성전자", 3, 70000)
    recorded = [c[0][0] for c in engine._record_metric.call_args_list]
    assert "FILL_SLIPPAGE" in recorded
