"""Pipeline CLI 통합 TDD — subprocess로 8 commands 호출."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    ImplementationCategory,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "harness"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_session(monkeypatch, tmp_path):
    # SQLite JSONB workaround
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]
    db_path = tmp_path / "p.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Pipeline CLI는 src.db.session.get_engine을 호출하므로 모듈 reset 필요
    from src.db import session as session_mod
    session_mod.reset_engine()

    s = factory()
    repo = ProposalRepository(s)
    repo.create(
        path="docs/proposals/x.md", title="X",
        category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
    repo.create(
        path="docs/proposals/y.md", title="Y",
        category=ImplementationCategory.PARAM_TUNING,
        state=ProposalState.DRAFT, priority=ProposalPriority.LOW,
    )
    s.commit()
    yield s
    s.close()
    session_mod.reset_engine()


def _run(script: str, *args: str) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPTS_DIR / script), *args],
        capture_output=True, text=True, env=env, check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_list_ready_outputs_only_ready_proposals(db_session) -> None:
    code, out, _ = _run("pipeline_list_ready.py")
    assert code == 0
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["path"] == "docs/proposals/x.md"
    assert data[0]["state"] == "ready"


def test_find_proposal_returns_metadata(db_session) -> None:
    code, out, _ = _run("pipeline_find_proposal.py", "--path", "docs/proposals/x.md")
    assert code == 0
    data = json.loads(out)
    assert data["title"] == "X"
    assert data["state"] == "ready"


def test_find_proposal_missing_exits_nonzero(db_session) -> None:
    code, _, _ = _run("pipeline_find_proposal.py", "--path", "docs/proposals/nope.md")
    assert code == 1


def test_last_safe_tag_outputs_latest_tag() -> None:
    code, out, _ = _run("pipeline_last_safe_tag.py")
    # tag가 있으면 0, 없으면 0 with empty stdout 또는 1
    assert code in (0, 1)
    if code == 0:
        assert out.strip()  # 최소 한 줄


def test_mark_in_flight_transitions_state(db_session) -> None:
    code, _, _ = _run(
        "pipeline_mark_in_flight.py",
        "--path", "docs/proposals/x.md", "--cycle-id", "c-1",
    )
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.IN_FLIGHT
    assert p.cycle_id == "c-1"


def test_mark_implemented_after_in_flight(db_session) -> None:
    _run("pipeline_mark_in_flight.py", "--path", "docs/proposals/x.md", "--cycle-id", "c-2")
    code, _, _ = _run("pipeline_mark_implemented.py", "--path", "docs/proposals/x.md")
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.IMPLEMENTED


def test_mark_failed_records_reason(db_session) -> None:
    _run("pipeline_mark_in_flight.py", "--path", "docs/proposals/x.md", "--cycle-id", "c-3")
    code, _, _ = _run(
        "pipeline_mark_failed.py",
        "--path", "docs/proposals/x.md",
        "--reason", "verifier contract failed",
    )
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.FAILED
    assert "verifier" in p.failure_reason


def test_mark_skipped_from_ready(db_session) -> None:
    code, _, _ = _run(
        "pipeline_mark_skipped.py",
        "--path", "docs/proposals/x.md",
        "--reason", "safety_gate_violation",
    )
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.SKIPPED


def test_mark_in_flight_missing_path_exits_nonzero(db_session) -> None:
    code, _, _ = _run(
        "pipeline_mark_in_flight.py",
        "--path", "docs/proposals/nope.md", "--cycle-id", "c-x",
    )
    assert code == 1


def test_append_progress_records_transition(tmp_path) -> None:
    progress_file = tmp_path / "progress.json"
    # 먼저 빈 progress 생성
    from datetime import datetime, timedelta, timezone

    from src.harness.progress import CycleProgress, save_progress
    kst = timezone(timedelta(hours=9))
    cp = CycleProgress(
        cycle_id="t-1", started_at=datetime.now(kst), env="virtual",
    )
    save_progress(progress_file, cp)

    code, _, _ = _run(
        "pipeline_append_progress.py",
        "--progress", str(progress_file),
        "--proposal", "docs/proposals/x.md",
        "--from-state", "ready",
        "--to-state", "in_flight",
    )
    assert code == 0
    from src.harness.progress import load_progress
    refreshed = load_progress(progress_file)
    assert refreshed is not None
    assert len(refreshed.history) == 1
    assert refreshed.history[0].path == "docs/proposals/x.md"
    assert refreshed.history[0].to_state == "in_flight"
