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


# ── EVAL_TARGETS 메트릭 테스트 (proposal 2026-04-16) ──────────


class TestRecordEvalTargets:
    """_record_eval_targets 메트릭 기록 테스트."""

    def test_records_eval_targets_metric(self) -> None:
        """cycle/counts/targets/truncated 필드가 포함된 메트릭이 enqueue된다."""
        engine = _make_engine()

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_eval_targets(
                cycle_number=7,
                targets=["005930", "000660", "207940"],
                counts={"screening": 1, "watchlist": 5, "positions": 2},
            )

            mock_enqueue.assert_called_once()
            kwargs = mock_enqueue.call_args.kwargs
            assert kwargs["task_type"] == "record_metric"
            payload = kwargs["payload"]
            assert payload["metric_type"] == "EVAL_TARGETS"
            detail = payload["detail"]
            assert detail["cycle"] == 7
            assert detail["counts"] == {
                "screening": 1,
                "watchlist": 5,
                "positions": 2,
            }
            assert detail["total_targets"] == 3
            assert detail["targets"] == ["005930", "000660", "207940"]
            assert detail["truncated"] is False

    def test_truncates_long_target_list(self) -> None:
        """targets가 임계값을 넘으면 앞부분만 기록하고 truncated=True."""
        engine = _make_engine()
        long_targets = [f"{i:06d}" for i in range(80)]

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_eval_targets(
                cycle_number=1,
                targets=long_targets,
                counts={"screening": 70, "watchlist": 5, "positions": 5},
            )

            detail = mock_enqueue.call_args.kwargs["payload"]["detail"]
            assert detail["total_targets"] == 80
            assert len(detail["targets"]) == engine._EVAL_TARGETS_MAX_CODES
            assert detail["truncated"] is True


# ── SIGNAL_SUMMARY 메트릭 테스트 (proposal 2026-04-27) ──────


class TestSignalSummaryMetric:
    """사이클 종료 시 SIGNAL_SUMMARY 메트릭 기록 테스트."""

    @pytest.mark.asyncio
    async def test_signal_summary_recorded_after_cycle(self) -> None:
        """사이클 실행 후 SIGNAL_SUMMARY 메트릭이 enqueue된다."""
        engine = _make_engine()
        engine._cycle_count = 0

        engine._client.circuit_breaker.is_open = False
        mock_risk = MagicMock()
        mock_risk.is_portfolio_halted = False
        mock_risk.check_daily_trade_limit.return_value = False
        engine._risk = mock_risk

        balance = MagicMock()
        balance.deposit = 10_000_000
        balance.holdings = []
        engine._get_balance = AsyncMock(return_value=balance)

        # _screened_codes에 종목을 넣어 evaluated > 0 이 되도록 mock
        engine._screened_codes = {"005930", "000660"}

        async def fake_process(
            code: str, deposit: object, is_held: object, holding: object,
        ) -> None:
            engine._cycle_buy_count += 1
            engine._cycle_max_confidence = max(
                engine._cycle_max_confidence, 0.75,
            )

        engine._process_stock = AsyncMock(side_effect=fake_process)

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            await engine.run_trading_cycle()

        summary_calls = [
            c for c in mock_enqueue.call_args_list
            if c.kwargs.get("task_type") == "record_metric"
            and c.kwargs.get("payload", {}).get("metric_type") == "SIGNAL_SUMMARY"
        ]
        assert len(summary_calls) == 1
        detail = summary_calls[0].kwargs["payload"]["detail"]
        assert detail["cycle"] == 1
        expected = detail["buy_count"] + detail["sell_count"] + detail["hold_count"]
        assert detail["evaluated"] == expected
        assert "max_confidence" in detail
        assert "screened_count" in detail

    @pytest.mark.asyncio
    async def test_signal_summary_contains_all_keys(self) -> None:
        """SIGNAL_SUMMARY detail에 필수 키가 모두 존재한다."""
        engine = _make_engine()
        engine._cycle_count = 0

        engine._client.circuit_breaker.is_open = False
        mock_risk = MagicMock()
        mock_risk.is_portfolio_halted = False
        mock_risk.check_daily_trade_limit.return_value = False
        engine._risk = mock_risk

        balance = MagicMock()
        balance.deposit = 10_000_000
        balance.holdings = []
        engine._get_balance = AsyncMock(return_value=balance)

        engine._screened_codes = {"005930"}

        async def fake_process(
            code: str, deposit: object, is_held: object, holding: object,
        ) -> None:
            engine._cycle_hold_count += 1

        engine._process_stock = AsyncMock(side_effect=fake_process)

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            await engine.run_trading_cycle()

        summary_calls = [
            c for c in mock_enqueue.call_args_list
            if c.kwargs.get("task_type") == "record_metric"
            and c.kwargs.get("payload", {}).get("metric_type") == "SIGNAL_SUMMARY"
        ]
        assert len(summary_calls) == 1
        detail = summary_calls[0].kwargs["payload"]["detail"]
        expected_keys = {
            "cycle", "evaluated", "buy_count", "sell_count",
            "hold_count", "max_confidence", "screened_count",
        }
        assert set(detail.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_no_signal_summary_when_zero_evaluated(self) -> None:
        """평가 종목 0건이면 SIGNAL_SUMMARY가 기록되지 않는다."""
        engine = _make_engine()
        engine._cycle_count = 0

        engine._client.circuit_breaker.is_open = False
        mock_risk = MagicMock()
        mock_risk.is_portfolio_halted = False
        mock_risk.check_daily_trade_limit.return_value = False
        engine._risk = mock_risk

        balance = MagicMock()
        balance.deposit = 10_000_000
        balance.holdings = []
        engine._get_balance = AsyncMock(return_value=balance)

        # 스크리닝 종목 없음 → 평가 대상 0건
        engine._screened_codes = set()
        engine._process_stock = AsyncMock()

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            await engine.run_trading_cycle()

        summary_calls = [
            c for c in mock_enqueue.call_args_list
            if c.kwargs.get("task_type") == "record_metric"
            and c.kwargs.get("payload", {}).get("metric_type") == "SIGNAL_SUMMARY"
        ]
        assert len(summary_calls) == 0


    @pytest.mark.asyncio
    async def test_screen_stocks_includes_unconverted(self) -> None:
        """converted_to_trade=False인 스크리닝 결과도 평가 대상에 포함된다."""
        engine = _make_engine()
        engine._screened_codes = set()
        # watchlist을 비워서 관심종목 제외 필터 방지
        engine._watchlist_codes = []

        # screening_results DB 레코드 mock (모두 converted_to_trade=False)
        mock_results = []
        for i, (code, name) in enumerate([
            ("999001", "테스트A"), ("999002", "테스트B"), ("999003", "테스트C"),
        ]):
            r = MagicMock()
            r.stock_code = code
            r.stock_name = name
            r.converted_to_trade = False
            r.screening_rank = i + 1
            mock_results.append(r)

        mock_repo = MagicMock()
        mock_repo.get_by_date.return_value = mock_results

        with patch("src.engine.get_session") as mock_session, \
             patch("src.engine.ScreeningResultRepository", return_value=mock_repo):
            mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            await engine._screen_stocks()

        # converted_to_trade 필터 없이 3종목 모두 반영
        assert engine._screened_codes == {"999001", "999002", "999003"}

    @pytest.mark.asyncio
    async def test_screen_stocks_deduplicates(self) -> None:
        """동일 종목이 여러 사이클에 걸쳐 있어도 중복 없이 1회만 반영된다."""
        engine = _make_engine()
        engine._screened_codes = set()
        engine._watchlist_codes = []

        # 같은 종목이 2번 등장 (다른 cycle)
        mock_results = []
        for _cycle in [1, 2]:
            r = MagicMock()
            r.stock_code = "999001"
            r.stock_name = "테스트A"
            r.converted_to_trade = False
            r.screening_rank = 1
            mock_results.append(r)

        mock_repo = MagicMock()
        mock_repo.get_by_date.return_value = mock_results

        with patch("src.engine.get_session") as mock_session, \
             patch("src.engine.ScreeningResultRepository", return_value=mock_repo):
            mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            await engine._screen_stocks()

        assert engine._screened_codes == {"999001"}

    @pytest.mark.asyncio
    async def test_screen_stocks_respects_max_screened(self) -> None:
        """max_screened 한도를 초과하지 않는다."""
        engine = _make_engine()
        engine._screened_codes = set()
        engine._watchlist_codes = []
        engine._screener._config = MagicMock()
        engine._screener._config.max_screened = 2

        mock_results = []
        for i, code in enumerate(["999001", "999002", "999003"]):
            r = MagicMock()
            r.stock_code = code
            r.stock_name = f"종목{i}"
            r.converted_to_trade = False
            r.screening_rank = i + 1
            mock_results.append(r)

        mock_repo = MagicMock()
        mock_repo.get_by_date.return_value = mock_results

        with patch("src.engine.get_session") as mock_session, \
             patch("src.engine.ScreeningResultRepository", return_value=mock_repo):
            mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            await engine._screen_stocks()

        assert len(engine._screened_codes) == 2

    @pytest.mark.asyncio
    async def test_cycle_emits_eval_targets(self) -> None:
        """run_trading_cycle 실행 시 EVAL_TARGETS 메트릭이 enqueue된다."""
        engine = _make_engine()
        engine._cycle_count = 0

        # 서킷 브레이커/리스크 차단 없이 정상 사이클이 돌도록 mock 세팅
        engine._client.circuit_breaker.is_open = False
        mock_risk = MagicMock()
        mock_risk.is_portfolio_halted = False
        mock_risk.check_daily_trade_limit.return_value = False
        engine._risk = mock_risk

        balance = MagicMock()
        balance.deposit = 10_000_000
        balance.holdings = []
        engine._get_balance = AsyncMock(return_value=balance)

        # _process_stock 내부는 관심 없음(EVAL_TARGETS enqueue만 검증)
        engine._process_stock = AsyncMock()

        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            await engine.run_trading_cycle()

        # enqueue 호출 중 EVAL_TARGETS 메트릭이 최소 1회 있는지 확인
        eval_calls = [
            c for c in mock_enqueue.call_args_list
            if c.kwargs.get("task_type") == "record_metric"
            and c.kwargs.get("payload", {}).get("metric_type") == "EVAL_TARGETS"
        ]
        assert len(eval_calls) == 1
        detail = eval_calls[0].kwargs["payload"]["detail"]
        assert "counts" in detail
        assert set(detail["counts"].keys()) == {"screening", "watchlist", "positions"}
