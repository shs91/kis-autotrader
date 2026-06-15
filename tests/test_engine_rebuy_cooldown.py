"""재매수 쿨다운 게이트 테스트.

매도 후 N분 내 동일 종목 재매수를 차단(휩쏘 방지). 2026-06-15 HL만도
+6.4% 익절 직후 고가 재매수 → −2.2% 손절 사례 대응.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    df = pd.DataFrame([{"close": 70000.0, "date": "2026-06-15"}])
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
async def test_recent_sell_blocks_rebuy() -> None:
    """매도 직후(쿨다운 내) 동일 종목 재매수 차단 → REBUY_COOLDOWN."""
    engine = _make_engine()
    engine._last_sell_at["005930"] = datetime.now(UTC)  # 방금 매도
    mock_enqueue = await _process_buy(engine, "005930")
    rejects = [
        r for r in _extract_buy_reject_calls(mock_enqueue)
        if r["detail"]["reason"] == "REBUY_COOLDOWN"
    ]
    assert len(rejects) == 1
    assert (
        rejects[0]["detail"]["context"]["cooldown_min"]
        == settings.trading.buy_cooldown_after_sell_min
    )


@pytest.mark.asyncio
async def test_expired_cooldown_allows_rebuy() -> None:
    """쿨다운 경과 후엔 차단하지 않는다(REBUY_COOLDOWN 없음)."""
    engine = _make_engine()
    cd = settings.trading.buy_cooldown_after_sell_min
    engine._last_sell_at["005930"] = datetime.now(UTC) - timedelta(minutes=cd + 10)
    mock_enqueue = await _process_buy(engine, "005930")
    rejects = [
        r for r in _extract_buy_reject_calls(mock_enqueue)
        if r["detail"]["reason"] == "REBUY_COOLDOWN"
    ]
    assert rejects == []


@pytest.mark.asyncio
async def test_other_stock_not_blocked() -> None:
    """한 종목 매도가 다른 종목 매수를 막지 않는다."""
    engine = _make_engine()
    engine._last_sell_at["005930"] = datetime.now(UTC)
    mock_enqueue = await _process_buy(engine, "000660")
    rejects = [
        r for r in _extract_buy_reject_calls(mock_enqueue)
        if r["detail"]["reason"] == "REBUY_COOLDOWN"
    ]
    assert rejects == []
