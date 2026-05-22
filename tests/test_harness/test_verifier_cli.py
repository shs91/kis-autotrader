"""Verifier CLI subprocess 진입점 TDD."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "harness" / "run_verifier.py"


def _run(
    args: list[str], extra_env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(WRAPPER.parents[2])}
    # 상속된 사이클 산출물 경로가 테스트를 오염시키지 않도록 제거 후 명시 주입.
    env.pop("HARNESS_CYCLE_ARTIFACTS_PATH", None)
    if extra_env:
        env.update(extra_env)
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


def test_cli_mirrors_canonical_artifacts_when_env_set(tmp_path: Path) -> None:
    """HARNESS_CYCLE_ARTIFACTS_PATH가 설정되면 Stop 훅이 읽을 표준 산출물 파일을
    함께 기록한다 (top-level pytest/mypy/ruff 키)."""
    out = tmp_path / "verifier.json"
    canonical = tmp_path / "cycle_artifacts.json"
    _run(
        ["--self-test", "--out", str(out)],
        extra_env={"HARNESS_CYCLE_ARTIFACTS_PATH": str(canonical)},
    )
    assert canonical.exists()
    data = json.loads(canonical.read_text(encoding="utf-8"))
    assert "pytest" in data
    assert "mypy" in data
    assert "ruff" in data


def test_cli_skips_canonical_when_env_unset(tmp_path: Path) -> None:
    """env 미설정(수동 실행)이면 표준 산출물 파일을 쓰지 않는다."""
    out = tmp_path / "verifier.json"
    canonical = tmp_path / "cycle_artifacts.json"
    _run(["--self-test", "--out", str(out)])
    assert not canonical.exists()
