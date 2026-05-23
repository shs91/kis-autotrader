"""매도 PL 부호와 sell_reason 라벨 일관성 강제 listener 테스트.

proposal 2026-05-23: 760027 ETN anomaly(STOP_LOSS인데 PL +18.54%) 재발 차단.

mapper-level ``before_insert``/``before_update`` listener는 import 시점에 전역
등록되므로, 테스트는 별도 등록 없이 Trade를 flush하면 보정이 적용된다.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, SellReason, Trade, TradeType


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    """SQLite in-memory 세션. JSONB는 JSON으로 렌더링(다른 test_db 픽스처와 동일)."""
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _make_sell(
    sell_reason: SellReason | None,
    profit_loss_pct: float | None,
    *,
    price: int = 4226,
) -> Trade:
    """매도 Trade 인스턴스를 만든다."""
    return Trade(
        stock_code="760027",
        stock_name="키움 인버스 2X 전력 TOP5 ETN",
        trade_type=TradeType.SELL,
        quantity=942,
        price=price,
        total_amount=price * 942,
        sell_reason=sell_reason,
        profit_loss_pct=profit_loss_pct,
        profit_loss_amount=622_540,
        cycle_number=1,
        traded_at=datetime.now(UTC),
    )


class TestSellReasonConsistencyListener:
    """``before_insert``/``before_update`` 일관성 보정 검증."""

    def test_stop_loss_with_positive_pl_corrected_to_take_profit(
        self, session: Session
    ) -> None:
        """STOP_LOSS인데 PL>0이면 TAKE_PROFIT으로 보정 (760027 재현)."""
        trade = _make_sell(SellReason.STOP_LOSS, 18.54)
        session.add(trade)
        session.flush()
        assert trade.sell_reason == SellReason.TAKE_PROFIT

    def test_take_profit_with_negative_pl_corrected_to_stop_loss(
        self, session: Session
    ) -> None:
        """TAKE_PROFIT인데 PL<0이면 STOP_LOSS로 보정."""
        trade = _make_sell(SellReason.TAKE_PROFIT, -3.2)
        session.add(trade)
        session.flush()
        assert trade.sell_reason == SellReason.STOP_LOSS

    def test_consistent_stop_loss_unchanged(self, session: Session) -> None:
        """STOP_LOSS + PL<0 (정상)은 그대로 유지."""
        trade = _make_sell(SellReason.STOP_LOSS, -3.04)
        session.add(trade)
        session.flush()
        assert trade.sell_reason == SellReason.STOP_LOSS

    def test_trailing_stop_with_positive_pl_unchanged(
        self, session: Session
    ) -> None:
        """TRAILING_STOP은 PL 부호와 무관하게 유지 (분류 명확)."""
        trade = _make_sell(SellReason.TRAILING_STOP, 5.0)
        session.add(trade)
        session.flush()
        assert trade.sell_reason == SellReason.TRAILING_STOP

    def test_market_close_with_negative_pl_unchanged(
        self, session: Session
    ) -> None:
        """MARKET_CLOSE는 PL 부호와 무관하게 유지."""
        trade = _make_sell(SellReason.MARKET_CLOSE, -1.0)
        session.add(trade)
        session.flush()
        assert trade.sell_reason == SellReason.MARKET_CLOSE

    def test_zero_pl_unchanged(self, session: Session) -> None:
        """PL=0은 모호하므로 보정하지 않는다."""
        trade = _make_sell(SellReason.STOP_LOSS, 0.0)
        session.add(trade)
        session.flush()
        assert trade.sell_reason == SellReason.STOP_LOSS

    def test_buy_trade_not_touched(self, session: Session) -> None:
        """매수 Trade는 검사 대상이 아니다."""
        trade = Trade(
            stock_code="005930",
            stock_name="삼성전자",
            trade_type=TradeType.BUY,
            quantity=10,
            price=70000,
            total_amount=700000,
            cycle_number=1,
            traded_at=datetime.now(UTC),
        )
        session.add(trade)
        session.flush()
        assert trade.sell_reason is None

    def test_update_also_corrected(self, session: Session) -> None:
        """UPDATE 경로에서도 보정이 적용된다."""
        trade = _make_sell(SellReason.TRAILING_STOP, 5.0)
        session.add(trade)
        session.flush()
        # 사후 라벨을 STOP_LOSS로 잘못 갱신 → before_update에서 보정
        trade.sell_reason = SellReason.STOP_LOSS
        session.flush()
        assert trade.sell_reason == SellReason.TAKE_PROFIT
