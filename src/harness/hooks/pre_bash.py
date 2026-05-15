"""PreToolUse(Bash) — 운영 영향이 큰 명령을 즉시 차단."""

from __future__ import annotations

import re

from src.harness.hooks.pre_tool_use import HookDecision

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgit\s+push\s+(--force|-f)\b"), "git push --force"),
    (re.compile(r"\brm\s+-rf\s+/(?!tmp/|var/folders/)"), "rm -rf on root-level path"),
    (re.compile(r"\bdrop\s+(table|database|schema)\b", re.IGNORECASE), "DROP SQL"),
    (re.compile(r"\blaunchctl\s+unload\s+.*com\.kis\.autotrader"), "unload autotrader"),
    (re.compile(r"\blaunchctl\s+unload\s+.*com\.kis\.watchdog"), "unload watchdog"),
    (re.compile(r"\bgit\s+config\s+(--global|--system)\b"), "git global config"),
)


def evaluate(command: str) -> HookDecision:
    """Bash 명령어를 받아 위험 패턴 차단 여부를 결정한다."""
    for pat, label in _PATTERNS:
        if pat.search(command):
            return HookDecision(blocked=True, reason=f"dangerous: {label}")
    return HookDecision(blocked=False)
