"""일봉 데이터 부재 시 보유 종목의 현재가 기준 손절/익절 평가 테스트.

ETN(예: 760027)처럼 일봉 조회가 0건이라 ``_get_daily_df``가 None을 반환하는
경우에도 보유 종목은 현재가 vs 평균단가 기준으로 손절/익절을 평가해야 한다.

검증 포인트:
1. 보유 종목 + df None + 손절 조건 → 매도 실행
2. 보유 종목 + df None + 익절 조건 → 매도 실행
3. 보유 종목 + df None + 데드존(손절·익절 모두 미달) → 매도 없음
4. 미보유 종목 + df None → EVAL_SKIP, 매도 없음
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    """최소 mock으로 TradingEngine 생성 (마감임박 False 고정)."""
    with patch("src.engine.KISClient"), \
         patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), \
         patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), \
         patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._risk.is_near_market_close = (  # type: ignore[method-assign]
        lambda *a, **kw: False
    )
    return engine


def _stub_current_price(engine: TradingEngine, price: int, name: str = "테스트") -> None:
    """현재가 조회 mock 주입."""
    current_mock = MagicMock()
    current_mock.current_price = price
    current_mock.stock_name = name
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)


@pytest.mark.asyncio
async def test_held_no_daily_triggers_stop_loss() -> None:
    """일봉 None + 손절 조건이면 매도가 실행된다."""
    engine = _make_engine()
    engine._get_daily_df = AsyncMock(return_value=None)  # type: ignore[method-assign]
    # 평균단가 10,000 대비 -5% (손절 한도 3% 초과)
    _stub_current_price(engine, price=9_500)
    engine._execute_sell = AsyncMock()  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue"), \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="760027",
            deposit=1_000_000,
            is_held=True,
            holding_info={"avg_price": 10_000.0, "quantity": 100},
        )

    engine._execute_sell.assert_awaited_once()
    assert engine._execute_sell.call_args.kwargs["reason"] == "손절"


@pytest.mark.asyncio
async def test_held_no_daily_triggers_take_profit() -> None:
    """일봉 None + 익절 조건이면 매도가 실행된다."""
    engine = _make_engine()
    engine._get_daily_df = AsyncMock(return_value=None)  # type: ignore[method-assign]
    # 평균단가 10,000 대비 +27% (익절 한도 5% 초과)
    _stub_current_price(engine, price=12_700)
    engine._execute_sell = AsyncMock()  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue"), \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="760027",
            deposit=1_000_000,
            is_held=True,
            holding_info={"avg_price": 10_000.0, "quantity": 100},
        )

    engine._execute_sell.assert_awaited_once()
    assert engine._execute_sell.call_args.kwargs["reason"] == "익절"


@pytest.mark.asyncio
async def test_held_no_daily_dead_zone_no_sell() -> None:
    """일봉 None + 손절·익절 모두 미달이면 매도하지 않는다."""
    engine = _make_engine()
    engine._get_daily_df = AsyncMock(return_value=None)  # type: ignore[method-assign]
    # 평균단가 10,000 대비 +1% (손절·익절 모두 미달)
    _stub_current_price(engine, price=10_100)
    engine._execute_sell = AsyncMock()  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue"), \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="760027",
            deposit=1_000_000,
            is_held=True,
            holding_info={"avg_price": 10_000.0, "quantity": 100},
        )

    engine._execute_sell.assert_not_awaited()


@pytest.mark.asyncio
async def test_not_held_no_daily_skips() -> None:
    """미보유 종목은 일봉 None이면 EVAL_SKIP — 현재가 조회/매도 없음."""
    engine = _make_engine()
    engine._get_daily_df = AsyncMock(return_value=None)  # type: ignore[method-assign]
    engine._quote.get_current_price = AsyncMock()
    engine._execute_sell = AsyncMock()  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue"):
        await engine._process_stock(
            stock_code="005930",
            deposit=1_000_000,
            is_held=False,
            holding_info=None,
        )

    engine._quote.get_current_price.assert_not_awaited()
    engine._execute_sell.assert_not_awaited()
