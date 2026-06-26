"""candidate_snapshots 모델·repository 테스트 (shadow 검증)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import CandidateSnapshot


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    """SQLite in-memory 세션을 생성한다."""
    engine = create_engine("sqlite:///:memory:")
    # candidate_snapshots 테이블만 생성 (Base 전체는 JSONB 의존으로 SQLite 불가)
    CandidateSnapshot.__table__.create(engine)
    sess = Session(engine)
    yield sess  # type: ignore[misc]
    sess.close()
    engine.dispose()


def test_candidate_snapshot_columns(session: Session) -> None:
    """명시적으로 전달한 컬럼 값이 DB에 저장된다."""
    snap = CandidateSnapshot(
        stock_code="AAPL",
        market="US",
        price=145.32,
        ensemble_action="BUY",
        ensemble_confidence=0.72,
        ensemble_reason="MA cross",
        captured_at=datetime.now(UTC),
    )
    session.add(snap)
    session.flush()
    assert snap.id is not None
    assert snap.stock_code == "AAPL"
    assert snap.market == "US"
    assert snap.price == 145.32
    assert snap.ensemble_action == "BUY"
    assert snap.ensemble_confidence == 0.72
    assert snap.ensemble_reason == "MA cross"
    assert snap.captured_at is not None


def test_candidate_snapshot_server_default_market(session: Session) -> None:
    """market 생략 시 DB server_default('KRX')가 적용된다."""
    snap = CandidateSnapshot(
        stock_code="005930",
        price=70000.0,
        ensemble_action="HOLD",
        ensemble_confidence=0.0,
        captured_at=datetime.now(UTC),
    )
    session.add(snap)
    session.flush()
    session.refresh(snap)
    assert snap.market == "KRX"


def test_candidate_snapshot_captured_at_python_default(session: Session) -> None:
    """captured_at 생략 시 python default(datetime.now(UTC))가 자동 적용된다."""
    snap = CandidateSnapshot(
        stock_code="AAPL",
        market="US",
        price=145.32,
        ensemble_action="SELL",
        ensemble_confidence=0.5,
    )
    session.add(snap)
    session.flush()
    assert snap.captured_at is not None


def test_candidate_snapshot_reason_nullable(session: Session) -> None:
    """ensemble_reason은 생략 가능(nullable)하다."""
    snap = CandidateSnapshot(
        stock_code="AAPL",
        market="US",
        price=145.32,
        ensemble_action="BUY",
        ensemble_confidence=0.6,
        captured_at=datetime.now(UTC),
    )
    session.add(snap)
    session.flush()
    assert snap.ensemble_reason is None


def test_candidate_snapshot_repr(session: Session) -> None:
    """CandidateSnapshot의 repr이 stock_code·id·action을 포함한다."""
    snap = CandidateSnapshot(
        stock_code="AAPL",
        market="US",
        price=145.32,
        ensemble_action="BUY",
        ensemble_confidence=0.6,
        captured_at=datetime.now(UTC),
    )
    session.add(snap)
    session.flush()
    result = repr(snap)
    assert "AAPL" in result
    assert str(snap.id) in result
    assert "BUY" in result


def test_repository_record_and_get_recent(session: Session) -> None:
    from src.db.repository import CandidateSnapshotRepository

    repo = CandidateSnapshotRepository(session)
    now = datetime.now(UTC)
    repo.record("AAPL", "US", 145.0, "BUY", 0.7, "r1", captured_at=now - timedelta(hours=2))
    repo.record("AAPL", "US", 146.5, "BUY", 0.8, "r2", captured_at=now - timedelta(hours=1))
    repo.record("MSFT", "US", 300.0, "HOLD", 0.0, None, captured_at=now)  # 다른 종목

    rows = repo.get_recent("AAPL", since=now - timedelta(days=1))
    assert len(rows) == 2
    assert [r.price for r in rows] == [145.0, 146.5]  # captured_at 오름차순
    assert [r.ensemble_action for r in rows] == ["BUY", "BUY"]


def test_repository_record_default_reason_none(session: Session) -> None:
    from src.db.repository import CandidateSnapshotRepository

    repo = CandidateSnapshotRepository(session)
    snap = repo.record("AAPL", "US", 145.0, "HOLD", 0.0)
    assert snap.ensemble_reason is None


def test_repository_get_recent_filters_since(session: Session) -> None:
    from src.db.repository import CandidateSnapshotRepository

    repo = CandidateSnapshotRepository(session)
    now = datetime.now(UTC)
    repo.record(
        "AAPL", "US", 100.0, "BUY", 0.6, captured_at=now - timedelta(days=10)
    )  # 범위 밖
    repo.record("AAPL", "US", 200.0, "BUY", 0.7, captured_at=now - timedelta(hours=1))

    rows = repo.get_recent("AAPL", since=now - timedelta(days=7))
    assert len(rows) == 1
    assert rows[0].price == 200.0


def test_repository_delete_older_than(session: Session) -> None:
    from src.db.repository import CandidateSnapshotRepository

    repo = CandidateSnapshotRepository(session)
    now = datetime.now(UTC)
    repo.record("AAPL", "US", 100.0, "BUY", 0.6, captured_at=now - timedelta(days=10))
    repo.record("AAPL", "US", 200.0, "BUY", 0.7, captured_at=now - timedelta(days=1))
    session.flush()

    deleted = repo.delete_older_than(now - timedelta(days=7))
    assert deleted == 1
    assert len(repo.get_recent("AAPL", since=now - timedelta(days=30))) == 1
