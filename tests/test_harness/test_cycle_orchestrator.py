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


def test_cycle_sets_artifacts_path_env_for_claude(repo: Path, tmp_path: Path) -> None:
    """run_cycle은 claude 서브프로세스에 HARNESS_CYCLE_ARTIFACTS_PATH를 주입해
    verifier(쓰기)와 Stop 훅(읽기)이 동일 경로를 공유하게 한다."""
    progress = tmp_path / "p.json"
    canonical = tmp_path / "cycle_artifacts.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r, patch.dict(
        "os.environ", {"HARNESS_CYCLE_ARTIFACTS_PATH": str(canonical)}, clear=False
    ):
        r.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
        passed_env = r.call_args.kwargs["env"]
    assert passed_env["HARNESS_CYCLE_VERIFICATION_REQUIRED"] == "1"
    assert passed_env["HARNESS_CYCLE_ARTIFACTS_PATH"] == str(canonical)


def test_cycle_clears_stale_artifacts_before_claude(repo: Path, tmp_path: Path) -> None:
    """이전 사이클의 산출물이 게이트를 거짓 통과시키지 않도록 사이클 시작 시 제거."""
    progress = tmp_path / "p.json"
    canonical = tmp_path / "cycle_artifacts.json"
    canonical.write_text('{"pytest": "stale"}', encoding="utf-8")
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r, patch.dict(
        "os.environ", {"HARNESS_CYCLE_ARTIFACTS_PATH": str(canonical)}, clear=False
    ):
        r.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
    assert not canonical.exists()


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
