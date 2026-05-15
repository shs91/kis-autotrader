"""Verifier CLI subprocess 진입점 TDD."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "harness" / "run_verifier.py"


def _run(args: list[str]) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(WRAPPER.parents[2])}
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(WRAPPER), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_cli_help_lists_options() -> None:
    code, out, _ = _run(["--help"])
    assert code == 0
    assert "--base-ref" in out
    assert "--out" in out


def test_cli_writes_artifact_json(tmp_path: Path) -> None:
    out = tmp_path / "verifier.json"
    # --self-test 옵션이 실제 명령을 돌리지 않고 더미 결과를 출력하도록 함
    code, _, _ = _run(["--self-test", "--out", str(out)])
    assert code in (0, 2)  # contract pass(0) 또는 fail(2)
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "passed" in payload
    assert "artifacts" in payload
