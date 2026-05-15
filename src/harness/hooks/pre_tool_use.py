"""PreToolUse(Edit|Write) — 금지 경로 즉시 차단.

D3(BRIDGE_SPEC 자연어 규칙)의 deterministic 대체. Hook wrapper(T7)가 본 모듈을 호출한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

# 절대 차단: secrets·재현 곤란
_FORBIDDEN_EXACT = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "token.json",
    }
)

# 접두 차단: 디렉토리 단위
_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "alembic/versions/",  # 마이그레이션 직접 편집 금지 (autogenerate만)
    "src/api/auth.py",    # OAuth/Keychain 영향
)

# 경고 수준 (블록은 안 함, PostToolUse에서 dependency 라인 검사)
_WARN_EXACT = frozenset({"pyproject.toml"})


@dataclass(frozen=True)
class HookDecision:
    blocked: bool
    reason: str = ""
    warning: bool = False


def _normalize(p: str) -> str:
    return PurePosixPath(p.replace("\\", "/")).as_posix()


def evaluate(tool: str, params: dict[str, Any]) -> HookDecision:
    """tool/params를 받아 차단 여부를 결정한다."""
    if tool not in ("Edit", "Write", "MultiEdit"):
        return HookDecision(blocked=False)
    path = params.get("file_path") or params.get("path") or ""
    if not isinstance(path, str) or not path:
        return HookDecision(blocked=False)
    norm = _normalize(path)
    leaf = norm.rsplit("/", 1)[-1]

    if leaf in _FORBIDDEN_EXACT:
        return HookDecision(blocked=True, reason=f"forbidden file: {leaf}")

    for prefix in _FORBIDDEN_PREFIXES:
        if norm.startswith(prefix) or norm == prefix:
            return HookDecision(
                blocked=True,
                reason=f"forbidden path prefix: {prefix} (path={norm})",
            )

    if leaf in _WARN_EXACT:
        return HookDecision(blocked=False, warning=True, reason=f"warn: {leaf} edit detected")

    return HookDecision(blocked=False)
