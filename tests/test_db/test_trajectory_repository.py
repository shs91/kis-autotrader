"""TrajectoryRepository TDD."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import (
    Base,
    TrajectoryStatus,
    TrajectoryStep,
)
from src.db.repository import TrajectoryRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def test_append_entry_persists(session: Session) -> None:
    repo = TrajectoryRepository(session)
    now = datetime.now(UTC)
    entry = repo.append(
        cycle_id="c-1",
        step=TrajectoryStep.INITIALIZER,
        status=TrajectoryStatus.OK,
        started_at=now,
        completed_at=now,
        duration_seconds=0.5,
    )
    session.commit()
    assert entry.id is not None
    rows = repo.list_for_cycle("c-1")
    assert len(rows) == 1
    assert rows[0].step == TrajectoryStep.INITIALIZER


def test_list_for_cycle_filters_correctly(session: Session) -> None:
    repo = TrajectoryRepository(session)
    now = datetime.now(UTC)
    repo.append(
        cycle_id="c-a", step=TrajectoryStep.IMPLEMENTER,
        status=TrajectoryStatus.OK, started_at=now, completed_at=now,
    )
    repo.append(
        cycle_id="c-b", step=TrajectoryStep.VERIFIER,
        status=TrajectoryStatus.FAIL, started_at=now, completed_at=now,
    )
    session.commit()
    assert len(repo.list_for_cycle("c-a")) == 1
    assert len(repo.list_for_cycle("c-b")) == 1
    assert repo.list_for_cycle("c-x") == []


def test_list_recent_returns_ordered(session: Session) -> None:
    repo = TrajectoryRepository(session)
    base = datetime.now(UTC)
    for i in range(5):
        repo.append(
            cycle_id=f"c-{i}", step=TrajectoryStep.INITIALIZER,
            status=TrajectoryStatus.OK,
            started_at=base.replace(microsecond=i),
            completed_at=base.replace(microsecond=i),
        )
    session.commit()
    rows = repo.list_recent(limit=3)
    assert len(rows) == 3
    # 최신 순
    assert rows[0].cycle_id == "c-4"


def test_append_with_optional_metadata(session: Session) -> None:
    repo = TrajectoryRepository(session)
    now = datetime.now(UTC)
    entry = repo.append(
        cycle_id="c-2", step=TrajectoryStep.IMPLEMENTER,
        status=TrajectoryStatus.OK, started_at=now, completed_at=now,
        proposal_path="docs/proposals/x.md",
        agent="implementer",
        input_summary="proposal x",
        result_summary="3 files edited",
        token_usage_input=1500, token_usage_output=400,
        meta={"changed_files": ["src/x.py"]},
    )
    session.commit()
    assert entry.agent == "implementer"
    assert entry.token_usage_input == 1500
    assert entry.meta["changed_files"] == ["src/x.py"]
