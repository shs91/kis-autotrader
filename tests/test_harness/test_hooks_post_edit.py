"""PostToolUse(Edit|Write) — ruff/DTZ 자동 검사 TDD."""

from __future__ import annotations

from src.harness.hooks.post_edit import evaluate


def test_non_python_file_no_action() -> None:
    d = evaluate("docs/x.md", file_count_in_cycle=1)
    assert d.run_ruff is False
    assert d.warn is False


def test_python_file_triggers_ruff() -> None:
    d = evaluate("src/strategy/rsi.py", file_count_in_cycle=1)
    assert d.run_ruff is True


def test_exceeding_file_threshold_warns() -> None:
    d = evaluate("src/strategy/rsi.py", file_count_in_cycle=6)
    assert d.warn is True
    assert "5" in d.message  # 5파일 임계
