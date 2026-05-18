"""Trajectory 적재 헬퍼 TDD."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.db.models import TrajectoryStatus, TrajectoryStep
from src.harness.observability.trajectory import (
    append_entry,
    time_step,
)


def test_append_entry_uses_provided_repo() -> None:
    fake_repo = MagicMock()
    append_entry(
        repo=fake_repo,
        cycle_id="c-1",
        step=TrajectoryStep.INITIALIZER,
        status=TrajectoryStatus.OK,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    fake_repo.append.assert_called_once()
    kw = fake_repo.append.call_args.kwargs
    assert kw["cycle_id"] == "c-1"
    assert kw["step"] == TrajectoryStep.INITIALIZER


def test_time_step_context_manager_records_duration() -> None:
    fake_repo = MagicMock()
    with time_step(
        repo=fake_repo, cycle_id="c-2", step=TrajectoryStep.VERIFIER,
    ) as ctx:
        ctx.set_status(TrajectoryStatus.OK)
        ctx.set_result_summary("verified")
    fake_repo.append.assert_called_once()
    kw = fake_repo.append.call_args.kwargs
    assert kw["status"] == TrajectoryStatus.OK
    assert kw["result_summary"] == "verified"
    assert kw["duration_seconds"] >= 0.0


def test_time_step_exception_marks_fail() -> None:
    fake_repo = MagicMock()
    with pytest.raises(ValueError):
        with time_step(
            repo=fake_repo, cycle_id="c-3", step=TrajectoryStep.IMPLEMENTER,
        ) as ctx:
            ctx.set_status(TrajectoryStatus.OK)  # 무효화될 것
            raise ValueError("boom")
    fake_repo.append.assert_called_once()
    kw = fake_repo.append.call_args.kwargs
    assert kw["status"] == TrajectoryStatus.FAIL
    assert "boom" in (kw.get("result_summary") or "")
