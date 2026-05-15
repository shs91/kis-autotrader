"""Stop hook — 검증 단계 미실행 차단 TDD."""

from __future__ import annotations

from src.harness.hooks.stop import evaluate


def test_blocks_when_verification_artifacts_missing() -> None:
    d = evaluate(verification_artifacts={})
    assert d.blocked is True


def test_blocks_when_only_partial_artifacts() -> None:
    d = evaluate(verification_artifacts={"pytest": "ok"})
    assert d.blocked is True
    assert "mypy" in d.reason.lower()


def test_allows_when_all_artifacts_present() -> None:
    d = evaluate(verification_artifacts={"pytest": "ok", "mypy": "ok", "ruff": "ok"})
    assert d.blocked is False
