"""Stop hook — Verifier 단계의 검증 출력이 모두 첨부되지 않으면 종료 차단."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_REQUIRED = ("pytest", "mypy", "ruff")


@dataclass(frozen=True)
class HookDecision:
    blocked: bool
    reason: str = ""


def evaluate(*, verification_artifacts: dict[str, Any]) -> HookDecision:
    """필수 검증 산출물(pytest/mypy/ruff)이 모두 있는지 확인하고 차단 여부 결정."""
    missing = [k for k in _REQUIRED if k not in verification_artifacts]
    if missing:
        return HookDecision(
            blocked=True,
            reason=f"verification artifacts missing: {', '.join(missing)}",
        )
    return HookDecision(blocked=False)
