"""매매 엔진 DB 적재 통합 테스트.

핵심 검증:
1. DB/Queue 장애 시에도 매매 로직이 중단되지 않아야 한다.
2. enqueue 호출 시 올바른 payload가 전달되어야 한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import SellReason, TradeType
from src.engine import TradingEngine
from src.strategy.base import Signal, SignalType

# ── 헬퍼 ──────────────────────────────────────────────────


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


# ── _record_trade_to_db 테스트 ─────────────────────────────


class TestRecordTradeToDb:
    """_record_trade_to_db 메서드 테스트 (Queue 경유)."""

    def test_buy_trade_enqueued(self) -> None:
        """매수 체결이 Worker Queue에 적재된다."""
        engine = _make_engine()

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_trade_to_db(
                stock_code="005930",
                stock_name="삼성전자",
                trade_type=TradeType.BUY,
                quantity=10,
                price=70000,
            )

            mock_enqueue.assert_called_once()
            call_kwargs = mock_enqueue.call_args
            payload = call_kwargs.kwargs["payload"]
            assert payload["stock_code"] == "005930"
            assert payload["trade_type"] == "BUY"
            assert payload["total_amount"] == 700000
            assert payload["sell_reason"] is None
            assert call_kwargs.kwargs["task_type"] == "record_trade"
            assert call_kwargs.kwargs["priority"] == 10

    def test_sell_trade_with_pnl(self) -> None:
        """매도 체결 시 손익이 계산되어 payload에 포함된다."""
        engine = _make_engine()

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_trade_to_db(
                stock_code="005930",
                stock_name="삼성전자",
                trade_type=TradeType.SELL,
                quantity=10,
                price=72000,
                reason="익절",
                avg_price=70000.0,
            )

            payload = mock_enqueue.call_args.kwargs["payload"]
            assert payload["sell_reason"] == SellReason.TAKE_PROFIT.value
            assert payload["profit_loss_amount"] == 20000
            # (72000 - 70000) / 70000 * 100 ≈ 2.857
            assert abs(payload["profit_loss_pct"] - 2.857) < 0.01

    def test_queue_failure_does_not_raise(self) -> None:
        """Queue 장애 시 예외가 전파되지 않는다."""
        engine = _make_engine()

        with patch.object(
            engine._task_queue, "enqueue", side_effect=Exception("큐 장애")
        ):
            # 예외 없이 정상 반환
            engine._record_trade_to_db(
                stock_code="005930",
                stock_name="삼성전자",
                trade_type=TradeType.BUY,
                quantity=10,
                price=70000,
            )


# ── _record_signal_to_db 테스트 ────────────────────────────


class TestRecordSignalToDb:
    """_record_signal_to_db 메서드 테스트 (Queue 경유)."""

    def test_buy_signal_enqueued(self) -> None:
        """매수 시그널이 Worker Queue에 적재된다."""
        engine = _make_engine()
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.85,
            reason="골든크로스 발생 (단기MA 70000 > 장기MA 68000)",
        )

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_signal_to_db(
                "005930", "삼성전자", signal, action_taken=True,
            )

            payload = mock_enqueue.call_args.kwargs["payload"]
            assert payload["signal_type"] == "GOLDEN_CROSS"
            assert payload["confidence"] == 0.85
            assert payload["action_taken"] is True
            assert mock_enqueue.call_args.kwargs["priority"] == 5

    def test_hold_signal_not_enqueued(self) -> None:
        """HOLD 시그널은 Queue에 적재하지 않는다."""
        engine = _make_engine()
        signal = Signal(signal_type=SignalType.HOLD, confidence=0.0)

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_signal_to_db("005930", "삼성전자", signal)
            mock_enqueue.assert_not_called()

    def test_queue_failure_does_not_raise(self) -> None:
        """Queue 장애 시 예외가 전파되지 않는다."""
        engine = _make_engine()
        signal = Signal(
            signal_type=SignalType.BUY, confidence=0.5, reason="골든크로스",
        )

        with patch.object(
            engine._task_queue, "enqueue", side_effect=Exception("큐 장애")
        ):
            engine._record_signal_to_db("005930", "삼성전자", signal)


# ── _record_screening_to_db 테스트 ─────────────────────────


class TestRecordScreeningToDb:
    """_record_screening_to_db 메서드 테스트 (직접 DB — Phase 3에서 분리 예정)."""

    def test_screening_batch_recorded(self) -> None:
        """스크리닝 결과가 배치로 기록된다."""
        engine = _make_engine()

        items = []
        for code, name, vol in [
            ("005930", "삼성전자", 5000000),
            ("000660", "SK하이닉스", 3000000),
        ]:
            item = MagicMock()
            item.stock_code = code
            item.stock_name = name
            item.volume = vol
            item.change_rate = 2.5
            items.append(item)

        with patch("src.engine.get_session") as mock_session_ctx:
            mock_session = MagicMock()
            mock_session_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_ctx.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.engine.ScreeningResultRepository") as mock_repo_cls:
                mock_repo = mock_repo_cls.return_value

                engine._record_screening_to_db(items, ["005930"])

                assert mock_repo.record_screening.call_count == 2
                # 첫 번째 (삼성전자)는 converted_to_trade=True
                first_call = mock_repo.record_screening.call_args_list[0].kwargs
                assert first_call["converted_to_trade"] is True
                # 두 번째 (SK하이닉스)는 converted_to_trade=False
                second_call = mock_repo.record_screening.call_args_list[1].kwargs
                assert second_call["converted_to_trade"] is False

    def test_db_failure_does_not_raise(self) -> None:
        """DB 장애 시 예외가 전파되지 않는다."""
        engine = _make_engine()

        with patch("src.engine.get_session", side_effect=Exception("DB 연결 실패")):
            engine._record_screening_to_db([], [])


# ── _record_metric 테스트 ──────────────────────────────────


class TestRecordMetric:
    """_record_metric 메서드 테스트 (Queue 경유)."""

    def test_metric_enqueued(self) -> None:
        """시스템 메트릭이 Worker Queue에 적재된다."""
        engine = _make_engine()

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_metric("CYCLE_START", {"cycle": 1})

            payload = mock_enqueue.call_args.kwargs["payload"]
            assert payload["metric_type"] == "CYCLE_START"
            assert payload["detail"] == {"cycle": 1}
            assert mock_enqueue.call_args.kwargs["priority"] == 3

    def test_queue_failure_does_not_raise(self) -> None:
        """Queue 장애 시 예외가 전파되지 않는다."""
        engine = _make_engine()

        with patch.object(
            engine._task_queue, "enqueue", side_effect=Exception("큐 장애")
        ):
            engine._record_metric("ERROR", {"msg": "test"})


# ── 매매 사이클 통합: DB 장애에도 매매 정상 동작 ──────────────


class TestTradingCycleWithDbFailure:
    """DB/Queue 완전 장애 상태에서 매매 사이클이 정상 동작하는지 검증."""

    @pytest.mark.asyncio
    async def test_execute_buy_succeeds_despite_queue_failure(self) -> None:
        """Queue 장애에도 매수 주문이 실행된다."""
        engine = _make_engine()

        order_result = MagicMock()
        order_result.order_no = "KIS12345"
        engine._order.buy = AsyncMock(return_value=order_result)
        engine._notifier.notify_buy = AsyncMock()

        # Queue 완전 장애
        with patch.object(
            engine._task_queue, "enqueue", side_effect=Exception("큐 죽음")
        ):
            await engine._execute_buy("005930", "삼성전자", 10, 70000)

        # 매수 주문은 실행됨
        engine._order.buy.assert_awaited_once()
        assert engine._today_trade_count == 1

    @pytest.mark.asyncio
    async def test_execute_sell_succeeds_despite_queue_failure(self) -> None:
        """Queue 장애에도 매도 주문이 실행된다."""
        engine = _make_engine()

        order_result = MagicMock()
        order_result.order_no = "KIS12346"
        engine._order.sell = AsyncMock(return_value=order_result)
        engine._notifier.notify_sell = AsyncMock()

        # Queue 완전 장애
        with patch.object(
            engine._task_queue, "enqueue", side_effect=Exception("큐 죽음")
        ):
            await engine._execute_sell(
                "005930", 10, 72000,
                reason="손절", avg_price=70000.0,
            )

        # 매도 주문은 실행됨
        engine._order.sell.assert_awaited_once()
        assert engine._today_trade_count == 1

    @pytest.mark.asyncio
    async def test_run_trading_cycle_survives_queue_failure(self) -> None:
        """Queue 장애에도 매매 사이클이 끝까지 실행된다."""
        engine = _make_engine()
        engine._cycle_count = 0

        balance = MagicMock()
        balance.deposit = 10_000_000
        balance.holdings = []
        engine._get_balance = AsyncMock(return_value=balance)

        # Queue 장애
        with patch.object(
            engine._task_queue, "enqueue", side_effect=Exception("큐 죽음")
        ):
            # 사이클 실행 — 예외 없이 완료
            await engine.run_trading_cycle()

        assert engine._cycle_count == 1
