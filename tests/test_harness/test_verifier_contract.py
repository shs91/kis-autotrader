"""Default-FAIL contract 평가기 TDD."""

from __future__ import annotations

from src.harness.verifier.contract import (
    ContractResult,
    evaluate_contract,
)
from src.harness.verifier.diff import ChangedFile, DiffSummary
from src.harness.verifier.parsers import (
    MypyArtifact,
    PytestArtifact,
    RuffArtifact,
)


def _ok_pytest() -> PytestArtifact:
    return PytestArtifact(tests=10, failures=0, errors=0, skipped=0, duration_seconds=0.5)


def _ok_mypy() -> MypyArtifact:
    return MypyArtifact(files_checked=5)


def _ok_ruff() -> RuffArtifact:
    return RuffArtifact()


def _ok_diff() -> DiffSummary:
    return DiffSummary(files=[ChangedFile(path="src/x.py", additions=3, deletions=1)])


def test_all_present_and_pass_means_pass() -> None:
    res = evaluate_contract(
        pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff(),
    )
    assert res.passed is True
    assert res.reasons == []


def test_missing_any_artifact_fails() -> None:
    res = evaluate_contract(pytest=None, mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff())
    assert res.passed is False
    assert any("pytest" in r for r in res.reasons)


def test_failing_pytest_fails_contract() -> None:
    bad = PytestArtifact(tests=10, failures=2, errors=0)
    res = evaluate_contract(pytest=bad, mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff())
    assert res.passed is False
    assert any("pytest" in r for r in res.reasons)


def test_failing_ruff_fails_contract() -> None:
    bad = RuffArtifact(parse_error="boom")
    res = evaluate_contract(pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=bad, diff=_ok_diff())
    assert res.passed is False


def test_diff_empty_fails() -> None:
    empty = DiffSummary()
    res = evaluate_contract(pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=_ok_ruff(), diff=empty)
    assert res.passed is False
    assert any("diff" in r for r in res.reasons)


def test_excessive_file_count_warns_not_fails() -> None:
    big = DiffSummary(
        files=[
            ChangedFile(path=f"src/f{i}.py", additions=1, deletions=0) for i in range(8)
        ]
    )
    res = evaluate_contract(
        pytest=_ok_pytest(),
        mypy=_ok_mypy(),
        ruff=_ok_ruff(),
        diff=big,
        file_count_threshold=5,
    )
    assert res.passed is True  # 통과는 함
    assert res.warnings  # 단 경고
    assert any("file_count" in w or "8" in w for w in res.warnings)


def test_to_jsonb_round_trip() -> None:
    res: ContractResult = evaluate_contract(
        pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff(),
    )
    payload = res.to_jsonb()
    assert payload["passed"] is True
    assert "artifacts" in payload
    assert set(payload["artifacts"].keys()) == {"pytest", "mypy", "ruff", "diff"}
