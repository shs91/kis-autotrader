"""MarketAction 모델 + Repository 테스트.

매매 엔진의 매수 직전 차단 lookup용 — 거래정지/관리종목/정리매매/시장경고
등 KIS 종목마스터 플래그를 종목별로 저장.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, MarketAction
from src.db.repository import MarketActionRepository
from src.db.session import validate_timezone_aware


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]
    if not hasattr(SQLiteTypeCompiler, "visit_VECTOR"):
        def visit_vector(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "TEXT"
        SQLiteTypeCompiler.visit_VECTOR = visit_vector  # type: ignore[attr-defined]

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


def _action(code: str = "005930", **flags: bool) -> MarketAction:
    return MarketAction(
        stock_code=code,
        is_trading_halted=flags.get("is_trading_halted", False),
        is_administrative=flags.get("is_administrative", False),
        is_liquidation=flags.get("is_liquidation", False),
        is_market_warning=flags.get("is_market_warning", False),
        is_warning_pretrigger=flags.get("is_warning_pretrigger", False),
        is_dishonest_disclosure=flags.get("is_dishonest_disclosure", False),
        snapshot_at=datetime(2026, 5, 19, 17, 0, tzinfo=UTC),
    )


class TestModel:
    def test_create_default_all_false(self, session: Session) -> None:
        ma = _action()
        session.add(ma)
        session.commit()
        assert ma.stock_code == "005930"
        assert ma.should_block_buy is False
        assert ma.block_reasons == []

    def test_blocked_when_any_flag_true(self, session: Session) -> None:
        ma = _action(is_trading_halted=True)
        assert ma.should_block_buy is True
        assert "trading_halted" in ma.block_reasons

    def test_multiple_reasons_collected(self, session: Session) -> None:
        ma = _action(is_administrative=True, is_market_warning=True)
        assert sorted(ma.block_reasons) == ["administrative", "market_warning"]


class TestRepository:
    def test_get_returns_none_when_absent(self, session: Session) -> None:
        repo = MarketActionRepository(session)
        assert repo.get("999999") is None

    def test_get_returns_stored(self, session: Session) -> None:
        repo = MarketActionRepository(session)
        repo.upsert([_action("005930"), _action("000660", is_trading_halted=True)])

        ma = repo.get("000660")
        assert ma is not None
        assert ma.is_trading_halted is True
        assert ma.should_block_buy is True

    def test_upsert_overwrites_existing(self, session: Session) -> None:
        """동일 stock_code 재호출 시 플래그/타임스탬프가 갱신된다."""
        repo = MarketActionRepository(session)
        repo.upsert([_action("005930", is_trading_halted=True)])
        # 정상화 (모든 플래그 False)
        repo.upsert([_action("005930")])

        ma = repo.get("005930")
        assert ma is not None
        assert ma.is_trading_halted is False
        assert ma.should_block_buy is False

    def test_is_blocked_helper(self, session: Session) -> None:
        repo = MarketActionRepository(session)
        repo.upsert([_action("005930"), _action("000660", is_administrative=True)])

        assert repo.is_blocked("005930") is False
        assert repo.is_blocked("000660") is True
        # 미등록 종목은 False (안전 기본값 — 마스터 sync 전이라도 매매는 가능)
        assert repo.is_blocked("999999") is False

    def test_upsert_empty_list_noop(self, session: Session) -> None:
        repo = MarketActionRepository(session)
        repo.upsert([])  # raise 안 함
        assert repo.get("005930") is None
