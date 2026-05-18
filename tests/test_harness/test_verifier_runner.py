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
    """변경된 .py 파일(src + tests)이 있을 때 diff → ruff → mypy → pytest 순으로 실행."""
    junit = (
        '<testsuites><testsuite name="x" tests="1" failures="0"'
        ' errors="0" skipped="0" time="0.1"/></testsuites>'
    )
    runner = VerifierRunner(repo_root=repo_root)
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        # Phase 3 hotfix D2: 호출 순서가 git diff → ruff → mypy → pytest로 변경
        r.side_effect = [
            _proc(0, stdout="5\t1\tsrc/x.py\n3\t1\ttests/test_x.py\n"),  # git diff first
            _proc(0, stdout="[]"),  # ruff (src/x.py + tests/test_x.py 한정)
            _proc(0, stdout="Success: no issues found in 1 source files"),  # mypy (src/x.py만)
            _proc(0, stdout=""),  # pytest (tests/test_x.py 한정, junit 파일은 fixture로 작성됨)
        ]
        junit_file = repo_root / "junit.xml"
        junit_file.write_text(junit, encoding="utf-8")
        runner._junit_path = junit_file  # 테스트용 주입
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert isinstance(result, RunnerResult)
    assert result.diff is not None
    assert result.diff.file_count == 2  # src/x.py + tests/test_x.py
    assert result.ruff is not None
    assert result.ruff.passed is True
    assert result.mypy is not None
    assert result.mypy.passed is True
    assert result.pytest is not None
    assert result.pytest.passed is True


def test_runner_skips_checks_when_no_py_files_changed(repo_root: Path) -> None:
    """Phase 3 hotfix D2: .py 파일이 전혀 변경되지 않으면 ruff/mypy/pytest 모두 PASS 기본값."""
    runner = VerifierRunner(repo_root=repo_root)
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        # diff에 .md 파일만 — Python 검증 대상 없음
        r.side_effect = [
            _proc(0, stdout="2\t0\tdocs/x.md\n"),
        ]
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert result.diff is not None
    assert result.diff.file_count == 1
    # 검증 대상 없음 → 기본 artifact는 모두 passed
    assert result.ruff is not None and result.ruff.passed is True
    assert result.mypy is not None and result.mypy.passed is True
    assert result.pytest is not None and result.pytest.passed is True
    # subprocess.run은 git diff 1번만 호출됨
    assert r.call_count == 1


def test_runner_marks_failures_when_subprocess_errors(repo_root: Path) -> None:
    runner = VerifierRunner(repo_root=repo_root)
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        r.side_effect = subprocess.SubprocessError("git missing")
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    # diff first → diff 호출에서 실패 → 모든 artifact None
    assert result.diff is None
    assert result.runner_error is not None


def test_runner_default_paths(repo_root: Path) -> None:
    runner = VerifierRunner(repo_root=repo_root)
    assert runner.src_target == "src/"
    assert runner.test_target == "tests/"
