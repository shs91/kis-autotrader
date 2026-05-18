"""PreToolUse(Bash) — 위험 명령 차단 TDD."""

from __future__ import annotations

import pytest

from src.harness.hooks.pre_bash import evaluate


@pytest.mark.parametrize(
    "cmd",
    [
        "git push --force",
        "git push -f origin main",
        "rm -rf /Users/songhansu/IdeaProjects/kis-autotrader",
        "psql -c 'DROP TABLE proposals'",
        'psql -d kis_trader -c "DROP DATABASE kis_trader"',
        "launchctl unload ~/Library/LaunchAgents/com.kis.autotrader.plist",
    ],
)
def test_blocks_dangerous_commands(cmd: str) -> None:
    decision = evaluate(cmd)
    assert decision.blocked is True


@pytest.mark.parametrize(
    "cmd",
    [
        "ls -la",
        "git status",
        "pytest tests/",
        "rm logs/*.log",
        "rm -rf .pytest_cache",
        "psql -c 'SELECT count(*) FROM proposals'",
    ],
)
def test_allows_safe_commands(cmd: str) -> None:
    decision = evaluate(cmd)
    assert decision.blocked is False
