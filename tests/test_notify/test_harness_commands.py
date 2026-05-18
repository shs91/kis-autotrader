"""Telegram 하네스 명령 TDD."""

from __future__ import annotations

import pytest

from src.harness.telegram_commands import (
    cmd_pause_implement,
    cmd_run_implement,
    cmd_status_implement,
)
from src.harness.trigger import paused, set_paused


@pytest.fixture
def tmp_lock_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_PAUSE_LOCK_PATH", str(tmp_path / "p"))
    monkeypatch.setenv("HARNESS_CYCLE_LOCK_PATH", str(tmp_path / "c"))
    yield


@pytest.mark.asyncio
async def test_run_implement_blocked_when_paused(tmp_lock_paths):
    set_paused(True)
    try:
        msg = await cmd_run_implement("")
        assert "차단" in msg or "blocked" in msg.lower()
    finally:
        set_paused(False)


@pytest.mark.asyncio
async def test_pause_implement_toggles(tmp_lock_paths):
    msg = await cmd_pause_implement("")
    assert paused() is True
    assert "일시 중단" in msg

    msg = await cmd_pause_implement("resume")
    assert paused() is False
    assert "재개" in msg


@pytest.mark.asyncio
async def test_status_implement_returns_summary(tmp_lock_paths):
    msg = await cmd_status_implement("")
    assert "harness" in msg.lower() or "사이클" in msg
