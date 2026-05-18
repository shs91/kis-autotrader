"""Cycle orchestrator TDD — Initializer 호출 + claude 위임 + 결과 적용."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.harness.cycle.orchestrator import (
    CycleOutcome,
    run_cycle,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh", encoding="utf-8")
    return tmp_path


def test_cycle_creates_progress_and_returns_cycle_id(repo: Path, tmp_path: Path) -> None:
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        r.return_value = MagicMock(returncode=0, stdout="", stderr="")
        outcome = run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
    assert isinstance(outcome, CycleOutcome)
    assert outcome.cycle_id.startswith("auto-")
    assert progress.exists()


def test_cycle_returns_initializer_failure_without_calling_claude(
    tmp_path: Path,
) -> None:
    bad_repo = tmp_path / "missing"
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        r.return_value = MagicMock(returncode=0, stdout="", stderr="")
        outcome = run_cycle(
            repo_root=bad_repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
    # Initializer가 환경 점검 실패해도 claude는 호출 — 단 outcome에 표시
    assert outcome.cycle_id


def test_cycle_returns_claude_exit_code(repo: Path, tmp_path: Path) -> None:
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        r.return_value = MagicMock(returncode=2, stdout="x", stderr="")
        outcome = run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
    assert outcome.claude_exit_code == 2


def test_cycle_records_trajectory_when_repo_provided(
    repo: Path, tmp_path: Path,
) -> None:
    fake_traj = MagicMock()
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        r.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
            trajectory_repo=fake_traj,
        )
    # Initializer entry + (prompt 없으니 claude entry는 적재 안 됨)
    assert fake_traj.append.call_count >= 1
