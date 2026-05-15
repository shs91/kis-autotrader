"""Verifier Runner TDD — pytest/mypy/ruff/diff 실행 + 아티팩트 통합."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.harness.verifier.runner import (
    RunnerResult,
    VerifierRunner,
)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_runner_collects_all_artifacts(repo_root: Path) -> None:
    junit = (
        '<testsuites><testsuite name="x" tests="1" failures="0"'
        ' errors="0" skipped="0" time="0.1"/></testsuites>'
    )
    runner = VerifierRunner(repo_root=repo_root)
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        # 호출 순서: ruff, mypy, pytest (junit 파일 작성), git diff numstat
        r.side_effect = [
            _proc(0, stdout="[]"),  # ruff
            _proc(0, stdout="Success: no issues found in 5 source files"),  # mypy
            _proc(0, stdout=""),  # pytest (--junitxml로 파일 작성. side effect로 파일 생성)
            _proc(0, stdout="5\t1\tsrc/x.py\n"),  # git diff
        ]
        junit_file = repo_root / "junit.xml"
        junit_file.write_text(junit, encoding="utf-8")
        runner._junit_path = junit_file  # 테스트용 주입
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert isinstance(result, RunnerResult)
    assert result.ruff is not None
    assert result.mypy is not None
    assert result.pytest is not None
    assert result.diff is not None
    assert result.diff.file_count == 1


def test_runner_marks_failures_when_subprocess_errors(repo_root: Path) -> None:
    runner = VerifierRunner(repo_root=repo_root)
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        r.side_effect = subprocess.SubprocessError("pytest binary missing")
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert result.ruff is None or result.ruff.parse_error is not None
    assert result.runner_error is not None


def test_runner_default_paths(repo_root: Path) -> None:
    runner = VerifierRunner(repo_root=repo_root)
    assert runner.src_target == "src/"
    assert runner.test_target == "tests/"
