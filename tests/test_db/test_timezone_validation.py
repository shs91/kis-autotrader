"""TIMESTAMPTZ 컬럼에 naive datetime을 거부하는 SQLAlchemy listener 테스트."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, Trade, TradeType
from src.db.session import validate_timezone_aware


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    """SQLite in-memory 세션에 listener를 명시적으로 등록한다.

    프로덕션은 `get_session()`이 listener를 등록하지만, 테스트는 자체
    세션을 만들므로 같은 listener를 수동으로 attach해 동작을 검증한다.
    JSONB 컬럼은 SQLite에서 JSON으로 렌더링한다 (다른 test_db 픽스처와 동일 패턴).
    """
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    event.listen(sess, "before_flush", validate_timezone_aware)
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _make_trade(traded_at: datetime) -> Trade:
    """검증에 필요한 최소 필드만 채운 Trade 인스턴스를 만든다."""
    return Trade(
        stock_code="005930",
        stock_name="삼성전자",
        trade_type=TradeType.BUY,
        quantity=10,
        price=70000,
        total_amount=700000,
        cycle_number=1,
        traded_at=traded_at,
    )


class TestTimezoneValidation:
    """`validate_timezone_aware` 리스너 동작 검증."""

    def test_naive_datetime_rejected(self, session: Session) -> None:
        """naive datetime을 TIMESTAMPTZ 컬럼에 set하면 flush 시 거부된다."""
        trade = _make_trade(datetime(2026, 5, 12, 11, 0, 0))
        session.add(trade)

        with pytest.raises(ValueError, match="Naive datetime"):
            session.flush()

    def test_aware_utc_datetime_accepted(self, session: Session) -> None:
        """aware UTC datetime은 정상 flush·commit된다."""
        trade = _make_trade(datetime.now(UTC))
        session.add(trade)
        session.commit()

        assert trade.id is not None

    def test_aware_kst_datetime_accepted(self, session: Session) -> None:
        """aware KST(ZoneInfo) datetime도 정상 처리된다."""
        kst = ZoneInfo("Asia/Seoul")
        trade = _make_trade(datetime(2026, 5, 12, 11, 0, 0, tzinfo=kst))
        session.add(trade)
        session.commit()

        assert trade.id is not None
