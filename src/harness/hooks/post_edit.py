"""PostToolUse(Edit|Write) — Python 변경에 대한 ruff/DTZ 검사 신호."""

from __future__ import annotations

from dataclasses import dataclass

_FILE_THRESHOLD = 5


@dataclass(frozen=True)
class HookDecision:
    run_ruff: bool
    warn: bool = False
    message: str = ""


def evaluate(file_path: str, *, file_count_in_cycle: int) -> HookDecision:
    """편집된 파일 경로/사이클 누적 카운트로 ruff 실행 여부와 경고를 결정한다."""
    if not file_path.endswith(".py"):
        return HookDecision(run_ruff=False)
    warn = file_count_in_cycle > _FILE_THRESHOLD
    msg = (
        f"이번 사이클에서 {file_count_in_cycle}개 파일 편집 — {_FILE_THRESHOLD} 초과 경고"
        if warn
        else ""
    )
    return HookDecision(run_ruff=True, warn=warn, message=msg)
