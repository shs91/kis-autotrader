"""Golden case invariant 평가기.

regex_absent/regex_present/ruff_rule/pytest_passes 4 type 지원.
ruff_rule과 pytest_passes는 subprocess 실행이 필요하므로 외부 명령에 의존.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.harness.golden.loader import GoldenCase, InvariantType


@dataclass(frozen=True)
class InvariantResult:
    """단일 invariant 평가 결과."""

    case_id: str
    passed: bool
    detail: str


def _eval_regex(
    case: GoldenCase, repo_root: Path, *, expect_match: bool
) -> InvariantResult:
    """regex_absent/regex_present 평가.

    expect_match=True면 regex_present (매칭이 있어야 pass),
    expect_match=False면 regex_absent (매칭이 없어야 pass).
    """
    params = case.invariant.params
    rel_path = str(params.get("file", ""))
    pattern = str(params.get("pattern", ""))
    target = repo_root / rel_path
    if not target.exists():
        return InvariantResult(case.id, False, f"file not found: {rel_path}")
    content = target.read_text(encoding="utf-8")
    try:
        rx = re.compile(pattern, re.MULTILINE)
    except re.error as e:
        return InvariantResult(case.id, False, f"regex error: {e!s:.80}")
    found = rx.search(content) is not None
    if expect_match:
        return InvariantResult(
            case.id,
            found,
            "pattern present" if found else f"pattern missing: {pattern!r}",
        )
    return InvariantResult(
        case.id,
        not found,
        "pattern absent" if not found else f"pattern matched: {pattern!r}",
    )


def _eval_ruff_rule(case: GoldenCase, repo_root: Path) -> InvariantResult:
    """지정 rule로 ruff check. returncode == 0이면 pass."""
    params = case.invariant.params
    rule = str(params.get("rule", ""))
    target = str(params.get("target", "src/"))
    cp = subprocess.run(  # noqa: S603
        ["ruff", "check", target, "--select", rule, "--output-format=concise"],  # noqa: S607
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    passed = cp.returncode == 0
    stdout = cp.stdout or ""
    first_line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    return InvariantResult(
        case.id,
        passed,
        f"ruff {rule} {'pass' if passed else 'fail'}: {first_line}",
    )


def _eval_pytest(case: GoldenCase, repo_root: Path) -> InvariantResult:
    """지정 nodeid로 pytest 실행. returncode == 0이면 pass."""
    params = case.invariant.params
    nodeid = str(params.get("nodeid", ""))
    cp = subprocess.run(  # noqa: S603
        ["pytest", nodeid, "-q", "--no-header"],  # noqa: S607
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return InvariantResult(
        case.id,
        cp.returncode == 0,
        f"pytest {nodeid} exit={cp.returncode}",
    )


def evaluate_case(case: GoldenCase, *, repo_root: Path) -> InvariantResult:
    """case.invariant.type에 따라 적절한 평가기로 dispatch."""
    if case.invariant.type == InvariantType.REGEX_ABSENT:
        return _eval_regex(case, repo_root, expect_match=False)
    if case.invariant.type == InvariantType.REGEX_PRESENT:
        return _eval_regex(case, repo_root, expect_match=True)
    if case.invariant.type == InvariantType.RUFF_RULE:
        return _eval_ruff_rule(case, repo_root)
    if case.invariant.type == InvariantType.PYTEST_PASSES:
        return _eval_pytest(case, repo_root)
    return InvariantResult(
        case.id, False, f"unsupported invariant type: {case.invariant.type}"
    )
