"""TradingEngine 매매 진단 알림 적재 테스트."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from src.engine import TradingEngine


def test_enqueue_telegram_diagnostics_payload() -> None:
    """진단 dict가 telegram_notify(diagnostics) 태스크로 적재된다."""
    engine = TradingEngine.__new__(TradingEngine)
    engine._task_queue = MagicMock()  # type: ignore[attr-defined]

    diag = {
        "trade_date": date(2026, 6, 8).isoformat(),
        "trade_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "monitored": [],
        "monitored_counts": {},
        "screening": {},
        "buy_rejects": {},
        "deposit": 449947,
        "holdings": 0,
        "headline": "매매 0건 — 모니터링 0종목",
    }
    engine._enqueue_telegram_diagnostics(diag)

    engine._task_queue.enqueue.assert_called_once()
    kwargs = engine._task_queue.enqueue.call_args.kwargs
    assert kwargs["task_type"] == "telegram_notify"
    assert kwargs["payload"]["notify_type"] == "diagnostics"
    assert kwargs["payload"]["message_data"]["diag"]["deposit"] == 449947
    assert kwargs["idempotency_key"].startswith("telegram_diag_")
