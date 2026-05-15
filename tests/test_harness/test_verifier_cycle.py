"""Verifier 결과 → proposals/implementation_logs wiring TDD."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import (
    Base,
    ImplementationCategory,
    Proposal,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository
from src.harness.verifier.contract import ContractResult
from src.harness.verifier.cycle import apply_verification_result


@pytest.fixture
def session() -> Iterator[Session]:
    """SQLite in-memory 세션 (JSONB workaround 포함)."""
    # SQLite JSONB workaround
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


def _make_in_flight(repo: ProposalRepository, path: str, cycle_id: str) -> Proposal:
    """READY 상태 생성 후 IN_FLIGHT로 전이시키는 헬퍼."""
    p = repo.create(
        path=path, title="t", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
    repo.mark_in_flight(p.id, cycle_id=cycle_id)
    return p


def test_apply_pass_marks_implemented(session: Session) -> None:
    """contract.passed=True → IN_FLIGHT → IMPLEMENTED 전이."""
    repo = ProposalRepository(session)
    _make_in_flight(repo, "docs/proposals/x.md", "c-1")
    session.commit()
    contract = ContractResult(
        passed=True,
        artifacts={
            "pytest": {"passed": True},
            "mypy": {"passed": True},
            "ruff": {"passed": True},
            "diff": {"file_count": 1},
        },
    )
    apply_verification_result(
        session=session,
        cycle_id="c-1",
        contract=contract,
    )
    session.commit()
    refreshed = repo.find_by_path("docs/proposals/x.md")
    assert refreshed is not None
    assert refreshed.state == ProposalState.IMPLEMENTED


def test_apply_fail_marks_failed_with_reason(session: Session) -> None:
    """contract.passed=False → IN_FLIGHT → FAILED + reason 첨부."""
    repo = ProposalRepository(session)
    _make_in_flight(repo, "docs/proposals/y.md", "c-2")
    session.commit()
    contract = ContractResult(
        passed=False,
        reasons=["pytest failed (failures=2, errors=0)"],
        artifacts={},
    )
    apply_verification_result(session=session, cycle_id="c-2", contract=contract)
    session.commit()
    refreshed = repo.find_by_path("docs/proposals/y.md")
    assert refreshed is not None
    assert refreshed.state == ProposalState.FAILED
    assert refreshed.failure_reason is not None
    assert "pytest" in refreshed.failure_reason


def test_apply_only_affects_in_flight_for_given_cycle(session: Session) -> None:
    """cycle_id 범위 밖 제안서는 영향받지 않음."""
    repo = ProposalRepository(session)
    _make_in_flight(repo, "docs/proposals/a.md", "c-X")
    _make_in_flight(repo, "docs/proposals/b.md", "c-Y")
    session.commit()
    contract = ContractResult(passed=True, artifacts={})
    apply_verification_result(session=session, cycle_id="c-X", contract=contract)
    session.commit()
    a = repo.find_by_path("docs/proposals/a.md")
    b = repo.find_by_path("docs/proposals/b.md")
    assert a is not None and a.state == ProposalState.IMPLEMENTED
    assert b is not None and b.state == ProposalState.IN_FLIGHT
