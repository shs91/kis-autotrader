"""RiskManager 상태 스냅샷/복원 테스트(장중 재시작 halt 우회 방지)."""

from __future__ import annotations

from src.strategy.risk import RiskManager


def test_snapshot_restore_round_trip() -> None:
    rm = RiskManager()
    rm.record_trade_result(-1000)
    rm.record_trade_result(-2000)
    snap = rm.snapshot()

    restored = RiskManager()
    restored.restore(snap)

    assert restored.daily_cumulative_pnl == rm.daily_cumulative_pnl
    assert restored.consecutive_losses == rm.consecutive_losses
    assert restored.is_portfolio_halted == rm.is_portfolio_halted


def test_restore_recovers_halt_state() -> None:
    rm = RiskManager()
    rm.restore(
        {
            "daily_peak_pnl": 5000,
            "daily_cumulative_pnl": -8000,
            "consecutive_losses": 9,
            "portfolio_halted": True,
            "halt_reason": "MAX_CONSECUTIVE_LOSSES",
        }
    )
    assert rm.is_portfolio_halted is True
    assert rm.consecutive_losses == 9
    assert rm.daily_cumulative_pnl == -8000


def test_restore_partial_keeps_current() -> None:
    rm = RiskManager()
    rm.record_trade_result(-500)
    before = rm.consecutive_losses
    rm.restore({"daily_cumulative_pnl": -1234})  # 연패 키 누락
    assert rm.daily_cumulative_pnl == -1234
    assert rm.consecutive_losses == before  # 누락 키는 현재 값 유지


def test_restore_ignores_wrong_types() -> None:
    rm = RiskManager()
    rm.restore({"consecutive_losses": "oops", "portfolio_halted": "yes"})
    assert rm.consecutive_losses == 0
    assert rm.is_portfolio_halted is False
