"""매수 게이트 진단 메트릭(BUY_REJECT) 통합 테스트.

proposal 2026-05-18: 시그널→매수 전환 0% anomaly 분해용.

검증 포인트:
1. 각 거절 분기에서 ``BUY_REJECT`` metric이 1회 enqueue된다.
2. detail.reason 코드가 BRIDGE 제안서의 분류와 일치한다.
3. ``_record_metric`` enqueue 실패 시에도 매매 흐름이 중단되지 않는다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.engine import TradingEngine
from src.strategy.base import Signal, SignalType


def _make_engine() -> TradingEngine:
    """최소한의 mock으로 TradingEngine을 생성한다."""
    with patch("src.engine.KISClient"), \
         patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), \
         patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), \
         patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    return engine


def _extract_buy_reject_calls(mock_enqueue: MagicMock) -> list[dict]:
    """enqueue mock에서 task_type=record_metric & metric_type=BUY_REJECT 호출만 추출."""
    out: list[dict] = []
    for call in mock_enqueue.call_args_list:
        kwargs = call.kwargs
        if kwargs.get("task_type") != "record_metric":
            continue
        payload = kwargs.get("payload") or {}
        if payload.get("metric_type") == "BUY_REJECT":
            out.append(payload)
    return out


class TestRecordBuyRejectHelper:
    """``_record_buy_reject`` 단위 동작 검증."""

    def test_records_buy_reject_metric(self) -> None:
        """BUY_REJECT 메트릭이 record_metric 큐로 적재된다."""
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_buy_reject(
                stock_code="005930",
                reason="LOW_CONFIDENCE",
                confidence=0.05,
                context={"balance": 1_000_000.0},
            )
            rejects = _extract_buy_reject_calls(mock_enqueue)
            assert len(rejects) == 1
            payload = rejects[0]
            assert payload["metric_type"] == "BUY_REJECT"
            detail = payload["detail"]
            assert detail["stock_code"] == "005930"
            assert detail["reason"] == "LOW_CONFIDENCE"
            assert detail["confidence"] == pytest.approx(0.05, abs=1e-4)
            assert detail["context"] == {"balance": 1_000_000.0}

    def test_none_confidence_recorded(self) -> None:
        """confidence가 None이면 detail.confidence도 None."""
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_buy_reject(
                stock_code="005930",
                reason="OTHER",
                confidence=None,
            )
            rejects = _extract_buy_reject_calls(mock_enqueue)
            assert len(rejects) == 1
            assert rejects[0]["detail"]["confidence"] is None

    def test_record_failure_does_not_raise(self) -> None:
        """enqueue가 예외를 던져도 본 흐름이 중단되지 않는다."""
        engine = _make_engine()
        with patch.object(
            engine._task_queue,
            "enqueue",
            side_effect=Exception("queue down"),
        ):
            # 예외 없이 정상 반환되어야 한다.
            engine._record_buy_reject(
                stock_code="005930",
                reason="RISK_GATE",
                confidence=0.5,
            )


# ── _process_stock의 BUY 경로 통합 테스트 ─────────────────────


@pytest.mark.asyncio
async def test_process_stock_low_confidence_records_buy_reject() -> None:
    """저신뢰도 시그널이 BUY_REJECT(LOW_CONFIDENCE)로 기록된다."""
    engine = _make_engine()

    # 일봉 mock
    df = pd.DataFrame([{"close": 70000.0, "date": "2026-05-15"}])
    engine._get_daily_df = AsyncMock(return_value=df)  # type: ignore[method-assign]

    # 현재가 mock
    current_mock = MagicMock()
    current_mock.current_price = 70_000
    current_mock.stock_name = "삼성전자"
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)

    # 전략 셀렉터: BUY 시그널 (저신뢰도)
    low_conf_signal = Signal(
        signal_type=SignalType.BUY,
        confidence=0.001,
        target_price=70_000.0,
        reason="ensemble vote",
    )
    strategy_stub = MagicMock()
    strategy_stub.name = "ensemble"
    strategy_stub.analyze = MagicMock(return_value=low_conf_signal)
    engine._selector.get_strategy = MagicMock(return_value=strategy_stub)

    with patch.object(engine._task_queue, "enqueue") as mock_enqueue, \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="005930",
            deposit=1_000_000,
            is_held=False,
            holding_info=None,
        )

        rejects = _extract_buy_reject_calls(mock_enqueue)
        assert len(rejects) == 1
        assert rejects[0]["detail"]["reason"] == "LOW_CONFIDENCE"
        assert rejects[0]["detail"]["stock_code"] == "005930"


@pytest.mark.asyncio
async def test_process_stock_insufficient_cash_records_buy_reject() -> None:
    """잔고 0일 때 BUY_REJECT(INSUFFICIENT_CASH) 기록."""
    engine = _make_engine()

    df = pd.DataFrame([{"close": 70000.0, "date": "2026-05-15"}])
    engine._get_daily_df = AsyncMock(return_value=df)  # type: ignore[method-assign]

    current_mock = MagicMock()
    current_mock.current_price = 70_000
    current_mock.stock_name = "삼성전자"
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)

    high_conf_signal = Signal(
        signal_type=SignalType.BUY,
        confidence=0.8,
        target_price=70_000.0,
        reason="golden",
    )
    strategy_stub = MagicMock()
    strategy_stub.name = "ma"
    strategy_stub.analyze = MagicMock(return_value=high_conf_signal)
    engine._selector.get_strategy = MagicMock(return_value=strategy_stub)

    with patch.object(engine._task_queue, "enqueue") as mock_enqueue, \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="005930",
            deposit=0,
            is_held=False,
            holding_info=None,
        )

        rejects = _extract_buy_reject_calls(mock_enqueue)
        assert len(rejects) == 1
        assert rejects[0]["detail"]["reason"] == "INSUFFICIENT_CASH"


@pytest.mark.asyncio
async def test_process_stock_position_ratio_records_buy_reject() -> None:
    """매수 가능 수량 0(POSITION_RATIO) BUY_REJECT 기록."""
    engine = _make_engine()

    df = pd.DataFrame([{"close": 70000.0, "date": "2026-05-15"}])
    engine._get_daily_df = AsyncMock(return_value=df)  # type: ignore[method-assign]

    # 매우 비싼 주식 → quantity 0
    current_mock = MagicMock()
    current_mock.current_price = 100_000_000
    current_mock.stock_name = "고가주"
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)

    signal = Signal(
        signal_type=SignalType.BUY,
        confidence=0.8,
        target_price=100.0,  # target_price는 잔고보다 작게 — INSUFFICIENT_CASH 회피
        reason="golden",
    )
    strategy_stub = MagicMock()
    strategy_stub.name = "ma"
    strategy_stub.analyze = MagicMock(return_value=signal)
    engine._selector.get_strategy = MagicMock(return_value=strategy_stub)

    # validate_order는 통과시키되 calculate_position_size에서 0 반환
    engine._risk.validate_order = MagicMock(return_value=True)  # type: ignore[method-assign]
    engine._risk.calculate_position_size = MagicMock(return_value=0)  # type: ignore[method-assign]

    with patch.object(engine._task_queue, "enqueue") as mock_enqueue, \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="999999",
            deposit=1_000_000,
            is_held=False,
            holding_info=None,
        )

        rejects = _extract_buy_reject_calls(mock_enqueue)
        assert len(rejects) == 1
        assert rejects[0]["detail"]["reason"] == "POSITION_RATIO"


@pytest.mark.asyncio
async def test_process_stock_daily_trade_limit_records_buy_reject() -> None:
    """일일 매매 한도 도달 시 BUY_REJECT(DAILY_TRADE_LIMIT) 기록."""
    engine = _make_engine()
    # 매매 카운트를 한도에 도달시킨다
    engine._today_trade_count = engine._risk._daily_trade_limit

    df = pd.DataFrame([{"close": 70000.0, "date": "2026-05-15"}])
    engine._get_daily_df = AsyncMock(return_value=df)  # type: ignore[method-assign]

    current_mock = MagicMock()
    current_mock.current_price = 70_000
    current_mock.stock_name = "삼성전자"
    engine._quote.get_current_price = AsyncMock(return_value=current_mock)

    signal = Signal(
        signal_type=SignalType.BUY,
        confidence=0.8,
        target_price=70_000.0,
        reason="golden",
    )
    strategy_stub = MagicMock()
    strategy_stub.name = "ma"
    strategy_stub.analyze = MagicMock(return_value=signal)
    engine._selector.get_strategy = MagicMock(return_value=strategy_stub)

    with patch.object(engine._task_queue, "enqueue") as mock_enqueue, \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="005930",
            deposit=1_000_000,
            is_held=False,
            holding_info=None,
        )

        rejects = _extract_buy_reject_calls(mock_enqueue)
        assert len(rejects) == 1
        assert rejects[0]["detail"]["reason"] == "DAILY_TRADE_LIMIT"
