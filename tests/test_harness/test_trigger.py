"""harness trigger 가드 TDD."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.harness.trigger import (
    can_trigger,
    paused,
    set_paused,
)


@pytest.fixture
def tmp_lock_paths(tmp_path: Path, monkeypatch):
    pause = tmp_path / "paused"
    cycle = tmp_path / "in-flight"
    monkeypatch.setenv("HARNESS_PAUSE_LOCK_PATH", str(pause))
    monkeypatch.setenv("HARNESS_CYCLE_LOCK_PATH", str(cycle))
    return pause, cycle


def test_no_locks_allows(tmp_lock_paths):
    decision = can_trigger(env="virtual", market_hour=False)
    assert decision.allowed is True


def test_pause_lock_blocks(tmp_lock_paths):
    pause, _ = tmp_lock_paths
    pause.touch()
    decision = can_trigger(env="virtual", market_hour=False)
    assert decision.allowed is False
    assert "paused" in decision.reason.lower()


def test_cycle_in_flight_blocks(tmp_lock_paths):
    _, cycle = tmp_lock_paths
    cycle.write_text("cycle-xx")
    decision = can_trigger(env="virtual", market_hour=False)
    assert decision.allowed is False
    assert "in-flight" in decision.reason.lower() or "in_flight" in decision.reason.lower()


def test_min_interval_blocks_if_too_recent(tmp_lock_paths, monkeypatch):
    monkeypatch.setenv("HARNESS_MIN_CYCLE_INTERVAL_SECONDS", "300")
    # 마지막 완료 시각을 60초 전으로 시뮬레이션
    decision = can_trigger(
        env="virtual",
        market_hour=False,
        last_completed_at=time.time() - 60,
    )
    assert decision.allowed is False
    assert "interval" in decision.reason.lower()


def test_real_env_market_hour_requires_force(tmp_lock_paths):
    decision = can_trigger(env="real", market_hour=True, force=False)
    assert decision.allowed is False
    assert "force" in decision.reason.lower()


def test_real_env_market_hour_with_force_allows(tmp_lock_paths):
    decision = can_trigger(env="real", market_hour=True, force=True)
    assert decision.allowed is True


def test_set_paused_creates_and_clears(tmp_lock_paths):
    set_paused(True)
    assert paused() is True
    set_paused(False)
    assert paused() is False
