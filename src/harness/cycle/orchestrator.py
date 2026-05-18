"""Cycle Orchestrator — 사이클 진입점.

순서:
1. Initializer.run() — 환경 점검 + claude-progress.json 생성
2. claude -p (top-level prompt) 호출 — subagent 오케스트레이션
3. claude exit code + progress.json 변화량으로 CycleOutcome 결정
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.harness.initializer import Initializer
from src.harness.progress import load_progress
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass(frozen=True)
class CycleOutcome:
    cycle_id: str
    claude_exit_code: int | None
    initializer_all_passed: bool
    completed_count: int
    failed_count: int
    skipped_count: int


def run_cycle(
    *,
    repo_root: Path,
    env: Literal["virtual", "real"],
    progress_path: Path,
    prompt_path: Path,
    claude_bin: str = "/Users/songhansu/.local/bin/claude",
    trajectory_repo: Any = None,
) -> CycleOutcome:
    """1회 사이클 실행."""
    init = Initializer(
        repo_root=repo_root, env=env, progress_path=progress_path,
        trajectory_repo=trajectory_repo,
    )
    status = init.run()
    logger.info(
        "cycle %s initialized (all_pass=%s)",
        status.cycle_id, status.all_passed,
    )

    claude_exit: int | None = None
    prompt: str = ""
    prompt_available = prompt_path.exists()
    if prompt_available:
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("prompt read failed: %s", e)
            prompt = ""
            prompt_available = False
    else:
        logger.warning("prompt %s missing, invoke claude with empty prompt", prompt_path)
    # Stop hook 활성화 — claude -p 종료 시 Verifier 검증 강제 (Phase 3 hotfix)
    cycle_env = {**os.environ, "HARNESS_CYCLE_VERIFICATION_REQUIRED": "1"}
    claude_started = datetime.now(UTC)
    cp = subprocess.run(  # noqa: S603
        [
            claude_bin, "-p", prompt,
            "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep,Task",
        ],
        cwd=str(repo_root), capture_output=True, text=True, check=False,
        timeout=3600, env=cycle_env,
    )
    claude_completed = datetime.now(UTC)
    claude_exit = cp.returncode
    if trajectory_repo is not None and prompt_available:
        from src.db.models import TrajectoryStatus, TrajectoryStep
        trajectory_repo.append(
            cycle_id=status.cycle_id,
            step=TrajectoryStep.IMPLEMENTER,
            status=(
                TrajectoryStatus.OK if cp.returncode == 0 else TrajectoryStatus.FAIL
            ),
            started_at=claude_started,
            completed_at=claude_completed,
            result_summary=f"claude exit={cp.returncode}",
            duration_seconds=(claude_completed - claude_started).total_seconds(),
        )

    # 사이클 종료 후 progress.json 통계 (필요 시 다시 로드)
    final = load_progress(progress_path)
    completed_count = len(final.completed) if final else 0
    failed_count = len(final.failed) if final else 0
    skipped_count = len(final.skipped) if final else 0

    return CycleOutcome(
        cycle_id=status.cycle_id,
        claude_exit_code=claude_exit,
        initializer_all_passed=status.all_passed,
        completed_count=completed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
    )
