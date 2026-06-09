"""종목 처리 ERROR의 event_logs 적재 정합 테스트.

proposal 2026-06-06: 종목 처리 예외가 system_metrics(ERROR)에만 적재되고
event_logs(ERROR)에는 누락되던 관측성 결함 보강.

검증 포인트:
1. ``_record_error``가 system_metrics(ERROR) enqueue + event_logs(log_error)
   양쪽을 일관 적재한다.
2. ``log_error``가 예외를 던져도 ``_record_error``는 전파하지 않는다(매매 흐름 보호).
"""

from __future__ import annotations

from unittest.mock import patch

from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), \
         patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), \
         patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), \
         patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        return TradingEngine(watchlist=["005930"])


def test_record_error_emits_metric_and_event() -> None:
    """_record_error가 system_metrics(ERROR) enqueue + event_logs(log_error) 양쪽을 적재."""
    engine = _make_engine()
    engine._cycle_count = 7
    with patch.object(engine._task_queue, "enqueue") as mock_enqueue, \
         patch("src.engine.log_error") as mock_log_error:
        engine._record_error("034220")

        metric_calls = [
            c.kwargs["payload"]
            for c in mock_enqueue.call_args_list
            if c.kwargs.get("task_type") == "record_metric"
            and (c.kwargs.get("payload") or {}).get("metric_type") == "ERROR"
        ]
        assert len(metric_calls) == 1
        detail = metric_calls[0]["detail"]
        assert detail["stock_code"] == "034220"
        assert detail["cycle"] == 7
        assert detail["error"] == "종목 처리 실패"

        mock_log_error.assert_called_once()
        assert "034220" in mock_log_error.call_args.args[0]


def test_record_error_logger_failure_is_swallowed() -> None:
    """log_error가 예외를 던져도 _record_error는 전파하지 않는다(매매 흐름 보호)."""
    engine = _make_engine()
    with patch.object(engine._task_queue, "enqueue"), \
         patch("src.engine.log_error", side_effect=Exception("db down")):
        # 예외 없이 정상 반환되어야 한다.
        engine._record_error("005930")
