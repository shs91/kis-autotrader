"""실전 전환 전 안전장치(Phase 0) 테스트.

검토(2026-05-30)에서 확인된 실전 치명 공백에 대한 수정 검증:
- 수동 킬스위치(비상 동결)
- 주문 직전 DB 헬스체크(추적 불가 실포지션 방지)
- 미체결 취소 직전 고아 체결 회수
- 장중 재시작 시 오늘 체결로 리스크 상태 재구성(halt 우회 방지)
"""

from __future__ import annotations

import types
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import TradeType
from src.engine import PendingOrder, TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._record_metric = MagicMock()  # type: ignore[method-assign]
    return engine


@contextmanager
def _force_flag(name: str, value: object):
    """frozen TradingConfig 플래그를 일시적으로 덮어쓴다(테스트 전용)."""
    from src.config import settings

    original = getattr(settings.trading, name)
    object.__setattr__(settings.trading, name, value)
    try:
        yield
    finally:
        object.__setattr__(settings.trading, name, original)


# ── 수동 킬스위치 ──────────────────────────────────────

def test_kill_switch_predicate_reads_file() -> None:
    engine = _make_engine()
    with patch("src.engine.os.path.exists", return_value=True):
        assert engine._is_trading_halted_manual() is True
    with patch("src.engine.os.path.exists", return_value=False):
        assert engine._is_trading_halted_manual() is False


@pytest.mark.asyncio
async def test_kill_switch_freezes_cycle() -> None:
    """킬스위치 활성 시 매매 사이클이 즉시 동결되어 잔고 조회조차 하지 않는다."""
    engine = _make_engine()
    engine._notifier.notify_error = AsyncMock()  # type: ignore[method-assign]
    engine._get_balance = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("동결 상태에서 잔고 조회 금지")
    )
    with patch("src.engine.os.path.exists", return_value=True):
        await engine.run_trading_cycle()
    engine._notifier.notify_error.assert_awaited_once()
    # 동일 동결 동안 재호출 시 알림 중복 없음
    with patch("src.engine.os.path.exists", return_value=True):
        await engine.run_trading_cycle()
    engine._notifier.notify_error.assert_awaited_once()


# ── 주문 직전 DB 헬스체크 ──────────────────────────────

@pytest.mark.asyncio
async def test_buy_skipped_when_db_down() -> None:
    engine = _make_engine()
    engine._order.buy = AsyncMock()
    with _force_flag("db_precheck_before_order", True), \
         patch("src.engine.db_healthcheck", return_value=False), \
         patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_check_disclosure_risk_block", return_value=None):
        await engine._execute_buy("005930", "삼성전자", 1, 70000)
    engine._order.buy.assert_not_awaited()


@pytest.mark.asyncio
async def test_sell_skipped_when_db_down() -> None:
    engine = _make_engine()
    engine._order.sell = AsyncMock()
    with _force_flag("db_precheck_before_order", True), \
         patch("src.engine.db_healthcheck", return_value=False):
        await engine._execute_sell("005930", 1, 70000, reason="손절")
    engine._order.sell.assert_not_awaited()


@pytest.mark.asyncio
async def test_buy_proceeds_when_db_up() -> None:
    engine = _make_engine()
    r = MagicMock()
    r.order_no = "ODNO"
    engine._order.buy = AsyncMock(return_value=r)
    engine._confirm_fill = AsyncMock(return_value=0)  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    with _force_flag("db_precheck_before_order", True), \
         patch("src.engine.db_healthcheck", return_value=True), \
         patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_check_disclosure_risk_block", return_value=None), \
         patch.object(engine, "_holding_quantity", new=AsyncMock(return_value=0)), \
         patch.object(engine._task_queue, "enqueue"):
        await engine._execute_buy("005930", "삼성전자", 1, 70000)
    engine._order.buy.assert_awaited_once()


# ── 고아 체결 회수 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_orphan_fill_recorded_instead_of_cancelled() -> None:
    """취소 직전 잔고 변동이 잡히면 트레이드로 기록하고 취소를 건너뛴다."""
    engine = _make_engine()
    engine._order.cancel = AsyncMock()
    engine._confirm_fill = AsyncMock(return_value=10)  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    pending = PendingOrder(
        order_no="A1", side="BUY", quantity=10, placed_cycle=1,
        stock_name="삼성전자", qty_before=0, price=70000,
    )
    engine._pending_orders["005930"] = pending
    with patch("src.engine.log_trade"), patch.object(engine._task_queue, "enqueue"):
        await engine._cancel_pending_order("005930", pending, reason="stale_cleanup")
    engine._order.cancel.assert_not_awaited()
    engine._record_trade_to_db.assert_called_once()
    assert "005930" not in engine._pending_orders


@pytest.mark.asyncio
async def test_no_orphan_fill_proceeds_to_cancel() -> None:
    engine = _make_engine()
    engine._order.cancel = AsyncMock()
    engine._confirm_fill = AsyncMock(return_value=0)  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    pending = PendingOrder(
        order_no="A1", side="SELL", quantity=10, placed_cycle=1,
        stock_name="삼성전자", qty_before=10, price=70000, avg_price=69000.0,
    )
    engine._pending_orders["005930"] = pending
    await engine._cancel_pending_order("005930", pending, reason="stale_cleanup")
    engine._order.cancel.assert_awaited_once()
    engine._record_trade_to_db.assert_not_called()
    assert "005930" not in engine._pending_orders


# ── 장중 재시작 리스크 상태 재구성 ──────────────────────

def _sell(amount: int, second: int) -> object:
    from datetime import UTC, datetime
    return types.SimpleNamespace(
        trade_type=TradeType.SELL,
        profit_loss_amount=amount,
        traded_at=datetime(2026, 6, 1, 1, 0, second, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_restart_reconstructs_risk_from_trades() -> None:
    """pre_market 미실행 상태에서 오늘 매도 체결을 재생해 누적손익/연패를 복원한다."""
    engine = _make_engine()
    engine._load_peak_prices = MagicMock(return_value={})  # type: ignore[method-assign]
    fake_trades = [_sell(-1000, 1), _sell(-2000, 2), _sell(500, 3), _sell(-300, 4)]

    repo = MagicMock()
    repo.get_trades_by_date.return_value = fake_trades

    @contextmanager
    def fake_session():
        yield MagicMock()

    with patch("src.engine.get_session", fake_session), \
         patch("src.engine.TradeRepository", return_value=repo):
        engine._restore_risk_state_if_needed()

    # 누적손익 = -1000-2000+500-300 = -2800, 마지막 연속 손실 1건
    assert engine._risk.daily_cumulative_pnl == -2800
    assert engine._risk.consecutive_losses == 1
    # 한 번만 시도(재호출 시 no-op)
    repo.get_trades_by_date.reset_mock()
    engine._restore_risk_state_if_needed()
    repo.get_trades_by_date.assert_not_called()


def test_premarket_disables_restart_restore() -> None:
    """pre_market이 돌았으면(_risk_state_restored=True) 재구성 경로는 비활성."""
    engine = _make_engine()
    engine._risk_state_restored = True
    with patch("src.engine.get_session") as gs:
        engine._restore_risk_state_if_needed()
    gs.assert_not_called()
