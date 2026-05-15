"""ProposalRepository TDD."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    ImplementationCategory,
    Proposal,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository


@pytest.fixture
def session():
    """SQLite in-memory 세션. JSONB → JSON 렌더링 등록 (test_repository.py와 동일 패턴)."""
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _make_proposal(repo: ProposalRepository, path: str, state: ProposalState) -> Proposal:
    return repo.create(
        path=path,
        title=f"T-{path}",
        category=ImplementationCategory.BUG_FIX,
        state=state,
        priority=ProposalPriority.MEDIUM,
    )


def test_create_and_find_by_path(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "docs/proposals/2026-05-14_x.md", ProposalState.READY)
    session.commit()
    assert repo.find_by_path("docs/proposals/2026-05-14_x.md").id == p.id


def test_create_duplicate_path_raises(session):
    repo = ProposalRepository(session)
    _make_proposal(repo, "docs/proposals/dup.md", ProposalState.READY)
    session.commit()
    with pytest.raises(IntegrityError):
        _make_proposal(repo, "docs/proposals/dup.md", ProposalState.READY)
        session.commit()


def test_list_ready_returns_only_ready_in_priority_order(session):
    repo = ProposalRepository(session)
    repo.create(
        path="a.md", title="A", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.LOW,
    )
    repo.create(
        path="b.md", title="B", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.CRITICAL,
    )
    repo.create(
        path="c.md", title="C", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.DRAFT, priority=ProposalPriority.CRITICAL,
    )
    session.commit()
    paths = [p.path for p in repo.list_ready()]
    assert paths == ["b.md", "a.md"]


def test_mark_in_flight_sets_state_and_cycle_id(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "x.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p.id, cycle_id="cycle-001")
    session.commit()
    refreshed = repo.find_by_path("x.md")
    assert refreshed.state == ProposalState.IN_FLIGHT
    assert refreshed.cycle_id == "cycle-001"
    assert refreshed.last_attempt_at is not None


def test_mark_in_flight_rejects_non_ready(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "y.md", ProposalState.IMPLEMENTED)
    session.commit()
    with pytest.raises(ValueError):
        repo.mark_in_flight(p.id, cycle_id="cycle-002")


def test_mark_implemented_clears_cycle_and_sets_state(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "z.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p.id, cycle_id="cycle-003")
    session.commit()
    repo.mark_implemented(p.id)
    session.commit()
    refreshed = repo.find_by_path("z.md")
    assert refreshed.state == ProposalState.IMPLEMENTED
    assert refreshed.cycle_id is None


def test_mark_failed_records_reason(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "f.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p.id, cycle_id="cycle-004")
    session.commit()
    repo.mark_failed(p.id, reason="ruff DTZ violation")
    session.commit()
    refreshed = repo.find_by_path("f.md")
    assert refreshed.state == ProposalState.FAILED
    assert refreshed.failure_reason == "ruff DTZ violation"


def test_mark_skipped_records_reason(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "s.md", ProposalState.READY)
    session.commit()
    repo.mark_skipped(p.id, reason="safety_gate_violation")
    session.commit()
    refreshed = repo.find_by_path("s.md")
    assert refreshed.state == ProposalState.SKIPPED
    assert refreshed.skip_reason == "safety_gate_violation"


def test_list_in_flight_for_cycle(session):
    repo = ProposalRepository(session)
    p1 = _make_proposal(repo, "p1.md", ProposalState.READY)
    p2 = _make_proposal(repo, "p2.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p1.id, cycle_id="cycle-X")
    repo.mark_in_flight(p2.id, cycle_id="cycle-Y")
    session.commit()
    rows = repo.list_in_flight_for_cycle("cycle-X")
    assert [r.path for r in rows] == ["p1.md"]
