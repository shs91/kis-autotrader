"""엔진 _process_stock 후보 스냅샷 훅 테스트 (미보유=적재, 보유=미적재, 매매 무영향)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.engine import TradingEngine, _Quote
from src.strategy.base import Signal, SignalType


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), \
         patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), \
         patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), \
         patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        return TradingEngine(watchlist=["005930"])


def _prime_engine(engine: TradingEngine, signal: Signal) -> None:
    """_process_stock의 외부 경계 메서드를 스텁으로 대체한다(시세/전략/DB I/O 격리)."""
    engine._get_daily_df = AsyncMock(return_value=pd.DataFrame({"close": [1, 2, 3]}))  # type: ignore[method-assign]
    engine._get_current = AsyncMock(  # type: ignore[method-assign]
        return_value=_Quote("005930", "삼성전자", 70000.0)
    )
    engine._resolve_current_stock_name = MagicMock()  # type: ignore[method-assign]
    engine._observe_signal_reversal = MagicMock()  # type: ignore[method-assign]
    engine._record_signal_skip = MagicMock()  # type: ignore[method-assign]
    engine._record_signal_to_db = MagicMock()  # type: ignore[method-assign]
    engine._process_held_stock = AsyncMock()  # type: ignore[method-assign]

    strategy = MagicMock()
    strategy.name = "stub"
    strategy.analyze.return_value = signal
    engine._selector.get_strategy = MagicMock(return_value=strategy)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_non_held_enqueues_candidate_snapshot() -> None:
    """미보유 모니터링 종목이면 후보 스냅샷을 enqueue한다."""
    engine = _make_engine()
    signal = Signal(signal_type=SignalType.HOLD, confidence=0.0, reason="hold")
    _prime_engine(engine, signal)

    with patch.object(engine, "_enqueue_candidate_snapshot") as mock_cand, \
         patch.object(engine, "_enqueue_price_snapshot") as mock_price:
        await engine._process_stock("005930", deposit=1_000_000, is_held=False,
                                    holding_info=None)

    mock_cand.assert_called_once()
    args = mock_cand.call_args.args
    assert args[0] == "005930"
    assert args[1] == engine._market.market_code
    assert args[2] == 70000.0
    assert args[3] is signal
    # 미보유는 보유종목 가격 스냅샷을 적재하지 않는다.
    mock_price.assert_not_called()


@pytest.mark.asyncio
async def test_held_does_not_enqueue_candidate_snapshot() -> None:
    """보유 종목이면 후보 스냅샷을 적재하지 않고 price_snapshot만 담당한다."""
    engine = _make_engine()
    signal = Signal(signal_type=SignalType.SELL, confidence=0.5, reason="sell")
    _prime_engine(engine, signal)

    with patch.object(engine, "_enqueue_candidate_snapshot") as mock_cand, \
         patch.object(engine, "_enqueue_price_snapshot") as mock_price:
        await engine._process_stock(
            "005930", deposit=1_000_000, is_held=True,
            holding_info={"avg_price": 60000.0, "quantity": 10},
        )

    mock_cand.assert_not_called()
    mock_price.assert_called_once()
    # 보유 매도 경로(매매 분기)는 그대로 호출된다 — 훅이 흐름을 바꾸지 않음.
    engine._process_held_stock.assert_awaited_once()  # type: ignore[attr-defined]
