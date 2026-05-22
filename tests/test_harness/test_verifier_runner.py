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


def test_runner_mypy_scopes_errors_to_changed_files(repo_root: Path) -> None:
    """mypy가 import한 미변경 의존 파일의 사전 존재 에러는 게이트를 FAIL시키지 않는다.

    Phase 3 hotfix D2 완성: 변경 파일만 검사해도 mypy는 import 그래프를 따라
    미변경 파일(pandas import-untyped 등)의 baseline 에러까지 보고한다. 이는 이번
    diff의 회귀가 아니므로 변경 파일에서 발생한 에러만 센다(전역 baseline≈85건이라
    스코프 제한 없이는 게이트가 구조적으로 항상 FAIL → auto-implement 재시작 불가).
    """
    runner = VerifierRunner(repo_root=repo_root)
    mypy_out = (
        "src/strategy/macd.py:55: error: Untyped thing  [import-untyped]\n"
        "src/strategy/rsi.py:179: error: Unused ignore  [unused-ignore]\n"
        "Found 2 errors in 2 files (checked 1 source file)\n"
    )
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        r.side_effect = [
            _proc(0, stdout="5\t1\tsrc/strategy/risk.py\n"),  # diff: risk.py만 변경
            _proc(0, stdout="[]"),  # ruff
            _proc(1, stdout=mypy_out),  # mypy: 에러가 미변경 의존 파일에만
        ]
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert result.mypy is not None
    assert result.mypy.error_count == 0  # macd/rsi 에러는 스코프 밖 → 제거
    assert result.mypy.passed is True


def test_runner_mypy_keeps_errors_in_changed_files(repo_root: Path) -> None:
    """변경된 파일 자체에서 발생한 에러는 회귀이므로 보존하고 FAIL시킨다."""
    runner = VerifierRunner(repo_root=repo_root)
    mypy_out = (
        "src/strategy/risk.py:42: error: Bad return type  [return-value]\n"
        "src/strategy/macd.py:55: error: Untyped thing  [import-untyped]\n"
        "Found 2 errors in 2 files (checked 1 source file)\n"
    )
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        r.side_effect = [
            _proc(0, stdout="5\t1\tsrc/strategy/risk.py\n"),  # diff: risk.py만 변경
            _proc(0, stdout="[]"),  # ruff
            _proc(1, stdout=mypy_out),  # mypy: 변경 파일 + 의존 파일 에러
        ]
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert result.mypy is not None
    assert result.mypy.error_count == 1  # risk.py 에러만 보존
    assert result.mypy.passed is False
    assert result.mypy.errors[0].file == "src/strategy/risk.py"
