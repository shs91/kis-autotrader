"""사이클 트리거 가드 — CLI/Telegram 공통.

다음을 강제한다.
- 동시 실행 금지 (cycle_lock_path 존재 시 차단)
- 최소 인터벌 (마지막 완료로부터 N초 이내 재발동 차단)
- KIS_ENV=real + 장중 시간 → --force 없이는 차단
- pause_lock_path 존재 시 모든 발동 차단
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import settings


@dataclass(frozen=True)
class TriggerDecision:
    allowed: bool
    reason: str = ""


def _pause_path() -> Path:
    return Path(os.environ.get("HARNESS_PAUSE_LOCK_PATH", settings.harness.pause_lock_path))


def _cycle_path() -> Path:
    return Path(os.environ.get("HARNESS_CYCLE_LOCK_PATH", settings.harness.cycle_lock_path))


def _min_interval() -> int:
    return int(
        os.environ.get(
            "HARNESS_MIN_CYCLE_INTERVAL_SECONDS",
            str(settings.harness.min_cycle_interval_seconds),
        )
    )


def paused() -> bool:
    return _pause_path().exists()


def set_paused(value: bool) -> None:
    p = _pause_path()
    if value:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def can_trigger(
    *,
    env: str,
    market_hour: bool,
    force: bool = False,
    last_completed_at: float | None = None,
) -> TriggerDecision:
    """발동 가드 평가."""
    if paused():
        return TriggerDecision(allowed=False, reason="harness paused (pause lock present)")
    if _cycle_path().exists():
        return TriggerDecision(allowed=False, reason="cycle in-flight (lock present)")
    if env == "real" and market_hour and not force:
        return TriggerDecision(
            allowed=False,
            reason="KIS_ENV=real + market hour requires --force",
        )
    if last_completed_at is not None:
        elapsed = time.time() - last_completed_at
        if elapsed < _min_interval():
            return TriggerDecision(
                allowed=False,
                reason=(
                    f"min interval not met (elapsed={elapsed:.0f}s, "
                    f"required={_min_interval()}s)"
                ),
            )
    return TriggerDecision(allowed=True)


def acquire_cycle_lock(cycle_id: str) -> Path:
    """사이클 시작 시 lock 파일을 만들고 cycle_id를 적는다."""
    p = _cycle_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(cycle_id)
    return p


def release_cycle_lock() -> None:
    try:
        _cycle_path().unlink()
    except FileNotFoundError:
        pass
