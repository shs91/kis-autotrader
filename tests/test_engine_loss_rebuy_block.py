"""손실 청산 당일 재매수 차단 게이트 테스트.

손실 확정 종목을 같은 거래일에 더 낮은 가격으로 재진입하는 churn(2026-07-03
감사: 재진입 19건 -18,553원 vs 첫진입 +34,351원, 손실 청산 직후 재매수 13건)을
시간 쿨다운(120분)과 별개로 당일 전체 차단한다. opt-in(기본 false).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.config import settings
from src.db.models import TradeType
from tests.test_engine_buy_gate_metric import _extract_buy_reject_calls, _make_engine
from tests.test_engine_rebuy_cooldown import _process_buy


@contextmanager
def _flag(value: bool) -> Iterator[None]:
    original = settings.trading.loss_rebuy_block_same_day
    object.__setattr__(settings.trading, "loss_rebuy_block_same_day", value)
    try:
        yield
    finally:
        object.__setattr__(settings.trading, "loss_rebuy_block_same_day", original)


def test_flag_default_false() -> None:
    """기본값은 비활성(false) — 기존 동작 보존, config_overrides로 opt-in."""
    assert settings.trading.loss_rebuy_block_same_day is False


class TestLossSellRecording:
    """매도 기록 관문(_record_trade_to_db)에서 손실 청산 날짜가 기록된다.

    단일 관문 훅이라 일반 매도·고아 체결 정산 경로 모두 커버된다.
    """

    def test_loss_sell_records_block_date(self) -> None:
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue"):
            engine._record_trade_to_db(
                "005930", "삼성전자", TradeType.SELL, 10, 9_700.0,
                reason="손절", avg_price=10_000.0,
            )
        assert (
            engine._loss_sell_dates.get("005930")
            == datetime.now(engine._tz).date()
        )

    def test_profit_sell_not_recorded(self) -> None:
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue"):
            engine._record_trade_to_db(
                "005930", "삼성전자", TradeType.SELL, 10, 10_500.0,
                reason="트레일링", avg_price=10_000.0,
            )
        assert "005930" not in engine._loss_sell_dates


class TestLossRebuyGate:
    """당일 손실 청산 종목의 재매수를 차단하는 BUY 게이트."""

    @pytest.mark.asyncio
    async def test_loss_sell_today_blocks_rebuy(self) -> None:
        """플래그 on + 당일 손실 청산 → LOSS_REBUY_BLOCKED."""
        engine = _make_engine()
        engine._loss_sell_dates["005930"] = datetime.now(engine._tz).date()
        with _flag(True):
            mock_enqueue = await _process_buy(engine, "005930")
        rejects = [
            r for r in _extract_buy_reject_calls(mock_enqueue)
            if r["detail"]["reason"] == "LOSS_REBUY_BLOCKED"
        ]
        assert len(rejects) == 1

    @pytest.mark.asyncio
    async def test_flag_off_does_not_block(self) -> None:
        """기본(비활성)에선 당일 손실 청산 종목도 차단하지 않는다."""
        engine = _make_engine()
        engine._loss_sell_dates["005930"] = datetime.now(engine._tz).date()
        with _flag(False):
            mock_enqueue = await _process_buy(engine, "005930")
        rejects = [
            r for r in _extract_buy_reject_calls(mock_enqueue)
            if r["detail"]["reason"] == "LOSS_REBUY_BLOCKED"
        ]
        assert rejects == []

    @pytest.mark.asyncio
    async def test_previous_day_loss_does_not_block(self) -> None:
        """전일 손실 청산은 차단 대상이 아니다(당일 한정)."""
        engine = _make_engine()
        engine._loss_sell_dates["005930"] = (
            datetime.now(engine._tz).date() - timedelta(days=1)
        )
        with _flag(True):
            mock_enqueue = await _process_buy(engine, "005930")
        rejects = [
            r for r in _extract_buy_reject_calls(mock_enqueue)
            if r["detail"]["reason"] == "LOSS_REBUY_BLOCKED"
        ]
        assert rejects == []

    @pytest.mark.asyncio
    async def test_other_stock_not_blocked(self) -> None:
        """한 종목의 손실 청산이 다른 종목 매수를 막지 않는다."""
        engine = _make_engine()
        engine._loss_sell_dates["005930"] = datetime.now(engine._tz).date()
        with _flag(True):
            mock_enqueue = await _process_buy(engine, "000660")
        rejects = [
            r for r in _extract_buy_reject_calls(mock_enqueue)
            if r["detail"]["reason"] == "LOSS_REBUY_BLOCKED"
        ]
        assert rejects == []
