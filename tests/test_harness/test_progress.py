"""claude-progress.json 스키마 TDD."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.harness.progress import (
    CycleProgress,
    InitializerCheck,
    InitializerCheckResult,
    load_progress,
    save_progress,
)


def test_create_minimal_cycle():
    c = CycleProgress(
        cycle_id="c-1",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
    )
    assert c.cycle_id == "c-1"
    assert c.initializer_checks == []
    assert c.pending == []
    assert c.history == []


def test_roundtrip_save_load(tmp_path: Path):
    c = CycleProgress(
        cycle_id="c-2",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
        last_safe_tag="v0.2.4",
    )
    c.initializer_checks.append(
        InitializerCheck(name="alembic_head", result=InitializerCheckResult.PASS)
    )
    c.pending.append("docs/proposals/x.md")
    p = tmp_path / "claude-progress.json"
    save_progress(p, c)
    loaded = load_progress(p)
    assert loaded.cycle_id == "c-2"
    assert loaded.last_safe_tag == "v0.2.4"
    assert loaded.initializer_checks[0].name == "alembic_head"


def test_transition_records_history():
    c = CycleProgress(
        cycle_id="c-3",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
    )
    c.transition("docs/proposals/a.md", from_state="pending", to_state="in_flight")
    assert len(c.history) == 1
    assert c.history[0].path == "docs/proposals/a.md"
    assert c.history[0].to_state == "in_flight"


def test_load_missing_file_returns_none(tmp_path: Path):
    assert load_progress(tmp_path / "nope.json") is None


def test_save_creates_parent_dir(tmp_path: Path):
    target = tmp_path / "deep" / "deeper" / "progress.json"
    c = CycleProgress(
        cycle_id="c-4",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="real",
    )
    save_progress(target, c)
    assert target.exists()
