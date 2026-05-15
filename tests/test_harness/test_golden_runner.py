"""Golden runner invariant 평가기 TDD."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.golden.loader import GoldenCase, Invariant, InvariantType
from src.harness.golden.runner import (
    InvariantResult,
    evaluate_case,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


def _case(itype: InvariantType, **params: object) -> GoldenCase:
    return GoldenCase(
        id="Gtest",
        proposal_path="x.md",
        category="bug_fix",
        summary="t",
        invariant=Invariant(type=itype, params=dict(params)),
    )


def test_regex_absent_passes_when_pattern_not_found(repo: Path) -> None:
    (repo / "src" / "x.py").write_text("a = 1\n", encoding="utf-8")
    case = _case(InvariantType.REGEX_ABSENT, file="src/x.py", pattern=r"datetime\.utcnow\(")
    r: InvariantResult = evaluate_case(case, repo_root=repo)
    assert r.passed is True


def test_regex_absent_fails_when_pattern_found(repo: Path) -> None:
    (repo / "src" / "x.py").write_text(
        "import datetime\nx = datetime.utcnow()\n", encoding="utf-8"
    )
    case = _case(InvariantType.REGEX_ABSENT, file="src/x.py", pattern=r"datetime\.utcnow\(")
    r: InvariantResult = evaluate_case(case, repo_root=repo)
    assert r.passed is False
    assert "matched" in r.detail.lower() or "found" in r.detail.lower()


def test_regex_present_passes_when_pattern_found(repo: Path) -> None:
    (repo / "src" / "x.py").write_text("def safe(): return tz=UTC\n", encoding="utf-8")
    case = _case(InvariantType.REGEX_PRESENT, file="src/x.py", pattern=r"tz=UTC")
    r: InvariantResult = evaluate_case(case, repo_root=repo)
    assert r.passed is True


def test_regex_present_fails_when_pattern_missing(repo: Path) -> None:
    (repo / "src" / "x.py").write_text("def unsafe(): pass\n", encoding="utf-8")
    case = _case(InvariantType.REGEX_PRESENT, file="src/x.py", pattern=r"tz=UTC")
    r: InvariantResult = evaluate_case(case, repo_root=repo)
    assert r.passed is False


def test_missing_file_fails(repo: Path) -> None:
    case = _case(InvariantType.REGEX_PRESENT, file="src/nope.py", pattern="x")
    r: InvariantResult = evaluate_case(case, repo_root=repo)
    assert r.passed is False
    assert "not found" in r.detail.lower() or "exist" in r.detail.lower()
