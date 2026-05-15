"""Claude Code hook wrapper TDD — stdin JSON → exit code 매핑."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "claude-hooks" / "run_hook.py"


def _run(
    payload: dict[str, object],
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    env = {**os.environ, "PYTHONPATH": str(WRAPPER.parents[2])}
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(  # noqa: S603 — fixed wrapper path, controlled test input
        [sys.executable, str(WRAPPER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stderr


def test_pre_tool_use_blocks_env_edit() -> None:
    code, err = _run(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": ".env"},
        }
    )
    assert code == 2
    assert "forbidden" in err.lower()


def test_pre_tool_use_allows_normal_edit() -> None:
    code, _ = _run(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/strategy/rsi.py"},
        }
    )
    assert code == 0


def test_pre_bash_blocks_force_push() -> None:
    code, err = _run(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force"},
        }
    )
    assert code == 2
    assert "dangerous" in err.lower()


def test_stop_blocks_when_artifacts_missing_in_cycle_context() -> None:
    """자동 구현 사이클 컨텍스트에서 verification artifacts 부재 시 차단."""
    code, err = _run(
        {
            "hook_event_name": "Stop",
            "verification_artifacts": {},
        },
        extra_env={"HARNESS_CYCLE_VERIFICATION_REQUIRED": "1"},
    )
    assert code == 2
    assert "verification" in err.lower()


def test_stop_passes_in_normal_session_without_env() -> None:
    """일반 Claude Code 세션(env 미설정)에서는 Stop hook이 통과."""
    code, _ = _run(
        {
            "hook_event_name": "Stop",
            "verification_artifacts": {},
        }
    )
    assert code == 0
