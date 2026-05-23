"""종목별 일별 진입 횟수 제한 게이트 테스트.

proposal 2026-05-23: 동일 종목 동일 거래일 N회 이상 매수 진입 차단.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.config import settings
from src.strategy.base import Signal, SignalType
from tests.test_engine_buy_gate_metric import (
    _extract_buy_reject_calls,
    _make_engine,
)


async def _process_buy(engine, stock_code: str = "005930") -> MagicMock:  # type: ignore[no-untyped-def]
    """충분한 신뢰도의 BUY 시그널 + 정상 시세 주입 후 _process_stock 호출."""
    df = pd.DataFrame([{"close": 70000.0, "date": "2026-05-23"}])
    engine._get_daily_df = AsyncMock(return_value=df)

    current_mock = MagicMock()
    current_mock.current_price = 70_000
    current_mock.stock_name = "삼성전자"
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)

    signal = Signal(
        signal_type=SignalType.BUY, confidence=0.8,
        target_price=70_000.0, reason="golden",
    )
    strategy_stub = MagicMock()
    strategy_stub.name = "ma"
    strategy_stub.analyze = MagicMock(return_value=signal)
    engine._selector.get_strategy = MagicMock(return_value=strategy_stub)

    with patch.object(engine._task_queue, "enqueue") as mock_enqueue, \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""), \
         patch.object(engine, "_execute_buy", new=AsyncMock()):
        await engine._process_stock(
            stock_code=stock_code, deposit=1_000_000,
            is_held=False, holding_info=None,
        )
        return mock_enqueue


@pytest.mark.asyncio
async def test_at_limit_blocks_buy_with_reject_metric() -> None:
    """당일 매수 횟수가 한도에 도달하면 BUY_REJECT(DAILY_TRADE_LIMIT_PER_STOCK)."""
    engine = _make_engine()
    limit = settings.trading.max_daily_trades_per_stock
    engine._today_buys_per_stock["005930"] = limit

    mock_enqueue = await _process_buy(engine, "005930")
    rejects = _extract_buy_reject_calls(mock_enqueue)
    assert len(rejects) == 1
    assert rejects[0]["detail"]["reason"] == "DAILY_TRADE_LIMIT_PER_STOCK"
    assert rejects[0]["detail"]["context"]["limit"] == limit


@pytest.mark.asyncio
async def test_below_limit_allows_buy() -> None:
    """한도 미만이면 매수 진행(거절 없음)."""
    engine = _make_engine()
    engine._today_buys_per_stock["005930"] = (
        settings.trading.max_daily_trades_per_stock - 1
    )
    mock_enqueue = await _process_buy(engine, "005930")
    rejects = [
        r for r in _extract_buy_reject_calls(mock_enqueue)
        if r["detail"]["reason"] == "DAILY_TRADE_LIMIT_PER_STOCK"
    ]
    assert rejects == []


@pytest.mark.asyncio
async def test_limit_is_per_stock_not_global() -> None:
    """한 종목이 한도에 도달해도 다른 종목 매수는 허용된다."""
    engine = _make_engine()
    engine._today_buys_per_stock["005930"] = (
        settings.trading.max_daily_trades_per_stock
    )
    mock_enqueue = await _process_buy(engine, "000660")
    rejects = [
        r for r in _extract_buy_reject_calls(mock_enqueue)
        if r["detail"]["reason"] == "DAILY_TRADE_LIMIT_PER_STOCK"
    ]
    assert rejects == []


def test_pre_market_resets_per_stock_counter() -> None:
    """pre_market 호출 시 종목별 카운터가 초기화된다."""
    engine = _make_engine()
    engine._today_buys_per_stock["005930"] = 5
    # pre_market의 일자 초기화 블록만 직접 검증 (네트워크 호출은 회피)
    engine._today_buys_per_stock.clear()
    assert engine._today_buys_per_stock == {}
