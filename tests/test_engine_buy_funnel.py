"""BUY_OUTCOME 퍼널 메트릭 테스트 (proposal 2026-05-30).

``_execute_buy``의 8개 종단 분기 각각이 정확히 1건의 ``BUY_OUTCOME`` 메트릭을
대응 outcome 코드로 적재하는지 검증한다. 매매 경로는 변경 없이 메트릭 적재만
관측하는 순수 관측 변경이므로, 한 번의 호출은 종단 상호배타로 정확히 1건만 남긴다.

기존 ``tests/test_engine_untradable_blacklist.py``·``tests/test_engine_disclosure_risk_gate.py``의
``_execute_buy`` 모킹 패턴(주문 API·체결확인 모킹)을 따른다.
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
    # 주문 직전 보유 조회·중복억제는 본 테스트 관심사 밖 — 기본 무력화
    engine._holding_quantity = AsyncMock(return_value=0)  # type: ignore[method-assign]
    engine._suppress_or_replace_pending = AsyncMock(return_value=False)  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_metric = MagicMock()  # type: ignore[method-assign]
    engine._record_screening_match_metric = MagicMock()  # type: ignore[method-assign]
    engine._invalidate_balance_cache = MagicMock()  # type: ignore[method-assign]
    # 공시 리스크 게이트는 본 테스트 관심사 밖(DB 의존) — 기본 통과
    engine._check_disclosure_risk_block = MagicMock(return_value=None)  # type: ignore[method-assign]
    return engine


def _order_result(order_no: str = "0000013289") -> MagicMock:
    r = MagicMock()
    r.order_no = order_no
    return r


def _buy_outcomes(engine: TradingEngine) -> list[str]:
    """기록된 BUY_OUTCOME 메트릭의 outcome 코드 목록."""
    out: list[str] = []
    for call in engine._record_metric.call_args_list:  # type: ignore[attr-defined]
        if call.args and call.args[0] == "BUY_OUTCOME":
            detail = call.args[1] if len(call.args) > 1 else {}
            out.append(detail.get("outcome"))
    return out


# 1. 정상 체결 경로 → FILLED 1건
@pytest.mark.asyncio
async def test_outcome_filled_on_successful_fill() -> None:
    """주문 후 잔고 증가(체결)면 outcome=FILLED 1건."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(return_value=_order_result())  # type: ignore[method-assign]
    engine._confirm_fill = AsyncMock(return_value=147)  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine._task_queue, "enqueue"):
        await engine._execute_buy("069540", "빛과전자", 147, 6610)

    assert _buy_outcomes(engine) == ["FILLED"]
    engine._record_trade_to_db.assert_called_once()


# 2. 당일 매매불가 블랙리스트 종목 → SKIP_UNTRADABLE_TODAY
@pytest.mark.asyncio
async def test_outcome_skip_untradable_today() -> None:
    """이미 블랙리스트에 오른 종목은 주문 없이 SKIP_UNTRADABLE_TODAY."""
    engine = _make_engine()
    engine._untradable_today.add("230980")
    engine._order.buy = AsyncMock()  # type: ignore[method-assign]
    await engine._execute_buy("230980", "비유테크놀러지", 100, 4000)

    engine._order.buy.assert_not_awaited()
    assert _buy_outcomes(engine) == ["SKIP_UNTRADABLE_TODAY"]


# (보강) 종목마스터 시장조치 차단 → BLOCK_MARKET_ACTION
@pytest.mark.asyncio
async def test_outcome_block_market_action() -> None:
    """시장조치(거래정지 등) 차단 시 BLOCK_MARKET_ACTION."""
    engine = _make_engine()
    engine._order.buy = AsyncMock()  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=["거래정지"]):
        await engine._execute_buy("005930", "삼성전자", 10, 70000)

    engine._order.buy.assert_not_awaited()
    assert _buy_outcomes(engine) == ["BLOCK_MARKET_ACTION"]


# 3. 치명 공시 차단 → BLOCK_DISCLOSURE (+ 기존 BUY_DISCLOSURE_BLOCK 유지)
@pytest.mark.asyncio
async def test_outcome_block_disclosure_keeps_legacy_metric() -> None:
    """치명 공시 차단 시 BLOCK_DISCLOSURE 1건 + 기존 BUY_DISCLOSURE_BLOCK 병행 유지."""
    engine = _make_engine()
    engine._order.buy = AsyncMock()  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_check_disclosure_risk_block",
                      return_value="주권매매거래정지 (상장폐지 사유발생)"):
        await engine._execute_buy("464680", "테스트종목", 100, 4000)

    engine._order.buy.assert_not_awaited()
    assert _buy_outcomes(engine) == ["BLOCK_DISCLOSURE"]
    metric_types = [c.args[0] for c in engine._record_metric.call_args_list]  # type: ignore[attr-defined]
    assert "BUY_DISCLOSURE_BLOCK" in metric_types  # 하위호환 메트릭 유지


# (보강) 미체결 주문 중복 억제 → SUPPRESS_PENDING
@pytest.mark.asyncio
async def test_outcome_suppress_pending() -> None:
    """동일 종목 미체결 주문 존재 시 SUPPRESS_PENDING."""
    engine = _make_engine()
    engine._suppress_or_replace_pending = AsyncMock(return_value=True)  # type: ignore[method-assign]
    engine._order.buy = AsyncMock()  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("005930", "삼성전자", 10, 70000)

    engine._order.buy.assert_not_awaited()
    assert _buy_outcomes(engine) == ["SUPPRESS_PENDING"]


# 4. 매매불가 주문 거부 → ORDER_UNTRADABLE (+ 기존 BUY_UNTRADABLE 유지)
@pytest.mark.asyncio
async def test_outcome_order_untradable_keeps_legacy_metric() -> None:
    """매매불가 거부 시 ORDER_UNTRADABLE 1건 + 기존 BUY_UNTRADABLE 병행 유지."""
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

    assert _buy_outcomes(engine) == ["ORDER_UNTRADABLE"]
    metric_types = [c.args[0] for c in engine._record_metric.call_args_list]  # type: ignore[attr-defined]
    assert "BUY_UNTRADABLE" in metric_types  # 하위호환 메트릭 유지


# (보강) 일반 주문 실패/예외 → ORDER_FAIL
@pytest.mark.asyncio
async def test_outcome_order_fail_on_generic_error() -> None:
    """매매불가가 아닌 일반 주문 실패는 ORDER_FAIL."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(  # type: ignore[method-assign]
        side_effect=OrderError("주문 실패 (rt_cd=1): 초당 거래건수를 초과하였습니다", rt_cd="1")
    )
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("005930", "삼성전자", 10, 70000)

    assert _buy_outcomes(engine) == ["ORDER_FAIL"]


@pytest.mark.asyncio
async def test_outcome_order_fail_on_unexpected_exception() -> None:
    """OrderError 외 예외도 ORDER_FAIL로 종단된다."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("005930", "삼성전자", 10, 70000)

    assert _buy_outcomes(engine) == ["ORDER_FAIL"]


# 5. 체결 미확인 → UNFILLED (+ 기존 ORDER_UNFILLED 유지)
@pytest.mark.asyncio
async def test_outcome_unfilled_keeps_legacy_metric() -> None:
    """접수됐으나 잔고 무변동(미체결)이면 UNFILLED 1건 + 기존 ORDER_UNFILLED 유지."""
    engine = _make_engine()
    engine._order.buy = AsyncMock(return_value=_order_result())  # type: ignore[method-assign]
    engine._confirm_fill = AsyncMock(return_value=0)  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]):
        await engine._execute_buy("069540", "빛과전자", 147, 6610)

    assert _buy_outcomes(engine) == ["UNFILLED"]
    metric_types = [c.args[0] for c in engine._record_metric.call_args_list]  # type: ignore[attr-defined]
    assert "ORDER_UNFILLED" in metric_types  # 하위호환 메트릭 유지
    engine._record_trade_to_db.assert_not_called()


# 6. 종단 상호배타 — 한 번의 호출은 정확히 1건의 BUY_OUTCOME만
@pytest.mark.asyncio
async def test_each_call_records_exactly_one_outcome() -> None:
    """모든 대표 종단에서 BUY_OUTCOME은 정확히 1건씩만 남는다(상호배타)."""
    # 체결 성공
    e1 = _make_engine()
    e1._order.buy = AsyncMock(return_value=_order_result())  # type: ignore[method-assign]
    e1._confirm_fill = AsyncMock(return_value=10)  # type: ignore[method-assign]
    with patch.object(e1, "_check_market_action_block", return_value=[]), \
         patch.object(e1._task_queue, "enqueue"):
        await e1._execute_buy("005930", "삼성전자", 10, 70000)
    assert len(_buy_outcomes(e1)) == 1

    # 공시 차단(기존 BUY_DISCLOSURE_BLOCK과 병행하지만 BUY_OUTCOME은 1건)
    e2 = _make_engine()
    e2._order.buy = AsyncMock()  # type: ignore[method-assign]
    with patch.object(e2, "_check_market_action_block", return_value=[]), \
         patch.object(e2, "_check_disclosure_risk_block",
                      return_value="상장폐지 사유발생"):
        await e2._execute_buy("464680", "테스트종목", 100, 4000)
    assert len(_buy_outcomes(e2)) == 1

    # 미체결(기존 ORDER_UNFILLED과 병행하지만 BUY_OUTCOME은 1건)
    e3 = _make_engine()
    e3._order.buy = AsyncMock(return_value=_order_result())  # type: ignore[method-assign]
    e3._confirm_fill = AsyncMock(return_value=0)  # type: ignore[method-assign]
    with patch.object(e3, "_check_market_action_block", return_value=[]):
        await e3._execute_buy("069540", "빛과전자", 147, 6610)
    assert len(_buy_outcomes(e3)) == 1
