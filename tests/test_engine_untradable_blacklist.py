"""매매불가 종목 당일 블랙리스트 테스트.

KIS가 매수 주문을 'rt_cd=1 매매불가 종목'으로 거부하면, 같은 거래일 동안 해당 종목의
매수 재시도를 차단한다. (무한 주문 재시도 → 사이클 블로킹/API 낭비 방지)
매도(청산)는 차단 대상이 아니다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine import TradingEngine
from src.utils.exceptions import OrderError


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    # 주문 직전 보유 조회·중복억제는 본 테스트 관심사 밖 — 무력화
    engine._holding_quantity = AsyncMock(return_value=0)  # type: ignore[method-assign]
    engine._suppress_or_replace_pending = AsyncMock(return_value=False)  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_metric = MagicMock()  # type: ignore[method-assign]
    return engine


@pytest.mark.asyncio
async def test_buy_blacklists_untradable_stock() -> None:
    """매매불가 거부 시 종목을 당일 블랙리스트에 넣고 트레이드는 기록하지 않는다."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(  # type: ignore[method-assign]
        side_effect=OrderError(
            "주문 실패 (rt_cd=1): 모의투자 주문처리가 안되었습니다(매매불가 종목)",
            rt_cd="1",
            msg1="모의투자 주문처리가 안되었습니다(매매불가 종목)",
        )
    )
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("230980", "비유테크놀러지", 100, 4000)

    assert "230980" in engine._untradable_today
    engine._record_trade_to_db.assert_not_called()
    metric_types = [c.args[0] for c in engine._record_metric.call_args_list]
    assert "BUY_UNTRADABLE" in metric_types


@pytest.mark.asyncio
async def test_blacklisted_stock_skips_order() -> None:
    """이미 블랙리스트에 오른 종목은 주문 API를 호출하지 않고 즉시 스킵한다."""
    engine = _make_engine()
    engine._untradable_today.add("230980")
    engine._order.buy = AsyncMock()  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("230980", "비유테크놀러지", 100, 4000)

    engine._order.buy.assert_not_awaited()
    engine._record_trade_to_db.assert_not_called()


@pytest.mark.asyncio
async def test_generic_order_error_not_blacklisted() -> None:
    """매매불가가 아닌 일반 주문 실패는 블랙리스트에 넣지 않는다(일시 오류 재시도 허용)."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(  # type: ignore[method-assign]
        side_effect=OrderError("주문 실패 (rt_cd=1): 초당 거래건수를 초과하였습니다", rt_cd="1")
    )
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("005930", "삼성전자", 10, 70000)

    assert "005930" not in engine._untradable_today
    metric_types = [c.args[0] for c in engine._record_metric.call_args_list]
    assert "BUY_UNTRADABLE" not in metric_types


@pytest.mark.asyncio
async def test_pre_market_clears_blacklist() -> None:
    """거래일이 바뀌면(pre_market) 블랙리스트가 초기화된다.

    리셋은 외부 I/O(토큰/스크리닝) 이전 동기 구간에서 일어난다. 토큰 조회를 실패시켜
    이후 본문을 단락시키되(pre_market은 내부에서 예외를 삼킴) 리셋 결과만 검증한다.
    """
    engine = _make_engine()
    engine._untradable_today.add("230980")
    engine._client._auth.get_access_token = AsyncMock(  # type: ignore[attr-defined]
        side_effect=Exception("stop after resets")
    )
    with patch.object(engine, "_load_peak_prices", return_value={}):
        await engine.pre_market()

    assert "230980" not in engine._untradable_today


def test_order_error_carries_rt_cd_and_msg() -> None:
    """OrderError가 rt_cd/msg1을 보존해 호출부가 거부 사유를 식별할 수 있다."""
    exc = OrderError("주문 실패", rt_cd="1", msg1="매매불가 종목")
    assert exc.rt_cd == "1"
    assert exc.msg1 == "매매불가 종목"
