"""Telegram bot 하네스 명령 핸들러.

/run_implement [--dry]      → 즉시 1회 사이클 시작 (가드 통과 시)
/status_implement           → 현재 사이클 상태와 가드 상태
/pause_implement [resume]   → 일시 중단/재개
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import settings
from src.harness.progress import load_progress
from src.harness.trigger import (
    acquire_cycle_lock,
    can_trigger,
    paused,
    release_cycle_lock,
    set_paused,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_KST = timezone(timedelta(hours=9))


def _is_market_hour(now: datetime | None = None) -> bool:
    now = now or datetime.now(_KST)
    if now.weekday() >= 5:
        return False
    return (now.hour, now.minute) >= (9, 0) and (now.hour, now.minute) <= (15, 30)


async def cmd_run_implement(args: str) -> str:
    dry = "--dry" in args
    force = "--force" in args
    decision = can_trigger(
        env=settings.kis.env, market_hour=_is_market_hour(), force=force,
    )
    if not decision.allowed:
        return f"❌ 발동 차단: {decision.reason}"

    if dry:
        return "✅ 가드 통과 — 구현은 생략(--dry)"

    cycle_id = f"manual-{datetime.now(_KST).strftime('%Y%m%d-%H%M%S')}"
    acquire_cycle_lock(cycle_id)
    try:
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "start", "com.kis.autoimplement",
        )
        await proc.wait()
        return f"🚀 사이클 발동: {cycle_id} (launchctl start 호출)"
    finally:
        # 실제 사이클 lock은 run_auto_implement.sh가 진입 시 다시 잡고 끝나면 release.
        # 본 함수는 launchctl 호출 완료 후 즉시 lock을 풀어 다음 발동이 가능하도록 한다.
        release_cycle_lock()


async def cmd_pause_implement(args: str) -> str:
    if args.strip() in ("resume", "off"):
        set_paused(False)
        return "▶️ 하네스 재개 (pause lock 제거)"
    set_paused(True)
    return "⏸️ 하네스 일시 중단 (pause lock 설치 — 자동/수동 트리거 모두 차단)"


async def cmd_status_implement(args: str) -> str:
    lines = ["🛠 하네스 상태"]
    lines.append(f"  paused: {'YES' if paused() else 'no'}")
    progress_path = Path.home() / ".kis-autotrader" / "claude-progress.json"
    cp = load_progress(progress_path)
    if cp is None:
        lines.append("  현재 사이클: 없음")
    else:
        lines.append(f"  현재 사이클: {cp.cycle_id} (started_at={cp.started_at.isoformat()})")
        lines.append(f"  pending={len(cp.pending)} in_flight={len(cp.in_flight)}")
        lines.append(f"  completed={len(cp.completed)} failed={len(cp.failed)}")
    return "\n".join(lines)
