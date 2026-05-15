"""PreToolUse(Edit|Write) hook 차단 룰 TDD."""

from __future__ import annotations

import pytest

from src.harness.hooks.pre_tool_use import evaluate


@pytest.mark.parametrize(
    "tool,path",
    [
        ("Edit", ".env"),
        ("Write", ".env.local"),
        ("Edit", "credentials.json"),
        ("Edit", "token.json"),
        ("Write", "alembic/versions/abc_xxx.py"),
        ("Edit", "src/api/auth.py"),  # OAuth 인증 로직 직접 편집 차단
    ],
)
def test_blocks_forbidden_paths(tool: str, path: str) -> None:
    decision = evaluate(tool, {"file_path": path})
    assert decision.blocked is True
    assert path.split("/")[-1] in decision.reason.lower() or path in decision.reason


def test_allows_normal_src_edit() -> None:
    decision = evaluate("Edit", {"file_path": "src/strategy/rsi.py"})
    assert decision.blocked is False


def test_blocks_pyproject_dependency_lines_via_marker() -> None:
    # dependency 라인 차단은 patch content를 보지 않으면 불가능하므로
    # 본 모듈에서는 pyproject.toml 자체 편집을 경고 수준으로 처리한다.
    decision = evaluate("Edit", {"file_path": "pyproject.toml"})
    assert decision.warning is True
    assert decision.blocked is False  # 경고만 (블록은 PostToolUse에서)


def test_unknown_tool_passes_through() -> None:
    decision = evaluate("Read", {"file_path": ".env"})
    assert decision.blocked is False
