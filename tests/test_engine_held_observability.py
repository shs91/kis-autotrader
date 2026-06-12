"""보유 종목 BUY 관측 (held_skip_buy) 테스트.

보유 종목에 BUY 신호가 나면 추가매수하지 않으며(피라미딩 X), 그 사유가
signals에 ``skip_reason="held_skip_buy"``로 기록되는지 검증한다. 매매 동작
(``action_taken=False``)은 불변이고, skip_reason만 추가된 관측 개선이다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.strategy.base import Signal, SignalType
from tests.test_engine_buy_gate_metric import _make_engine


@pytest.mark.asyncio
async def test_held_buy_records_held_skip_buy() -> None:
    """보유 종목 + BUY 신호 → action_taken=False, skip_reason='held_skip_buy'."""
    engine = _make_engine()
    df = pd.DataFrame([{"close": 70000.0, "date": "2026-06-12"}])
    engine._get_daily_df = AsyncMock(return_value=df)

    current_mock = MagicMock()
    current_mock.current_price = 70_000
    current_mock.stock_name = "삼성전자"
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)

    signal = Signal(signal_type=SignalType.BUY, confidence=0.8, reason="golden")
    strategy_stub = MagicMock()
    strategy_stub.name = "ma"
    strategy_stub.analyze = MagicMock(return_value=signal)
    engine._selector.get_strategy = MagicMock(return_value=strategy_stub)

    holding = MagicMock()
    with (
        patch.object(engine, "_record_signal_to_db") as mock_record,
        patch.object(engine, "_process_held_stock", new=AsyncMock()),
        patch.object(engine, "_resolve_current_stock_name"),
        patch.object(engine, "_observe_signal_reversal"),
    ):
        await engine._process_stock(
            stock_code="005930",
            deposit=1_000_000,
            is_held=True,
            holding_info=holding,
        )

    mock_record.assert_called_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs.get("action_taken") is False
    assert kwargs.get("skip_reason") == "held_skip_buy"


@pytest.mark.asyncio
async def test_held_low_conf_sell_unchanged() -> None:
    """보유 종목 + 저신뢰 SELL → 기존대로 skip_reason='low_confidence_sell' (회귀)."""
    engine = _make_engine()
    df = pd.DataFrame([{"close": 70000.0, "date": "2026-06-12"}])
    engine._get_daily_df = AsyncMock(return_value=df)

    current_mock = MagicMock()
    current_mock.current_price = 70_000
    current_mock.stock_name = "삼성전자"
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)

    signal = Signal(signal_type=SignalType.SELL, confidence=0.05, reason="weak sell")
    strategy_stub = MagicMock()
    strategy_stub.name = "ma"
    strategy_stub.analyze = MagicMock(return_value=signal)
    engine._selector.get_strategy = MagicMock(return_value=strategy_stub)

    holding = MagicMock()
    with (
        patch.object(engine, "_record_signal_to_db") as mock_record,
        patch.object(engine, "_process_held_stock", new=AsyncMock()),
        patch.object(engine, "_resolve_current_stock_name"),
        patch.object(engine, "_observe_signal_reversal"),
    ):
        await engine._process_stock(
            stock_code="005930",
            deposit=1_000_000,
            is_held=True,
            holding_info=holding,
        )

    kwargs = mock_record.call_args.kwargs
    assert kwargs.get("action_taken") is False
    assert kwargs.get("skip_reason") == "low_confidence_sell"
