#!/usr/bin/env python3
"""Claude Code hooks 진입점.

stdin으로 JSON payload를 받고, hook_event_name + tool_name에 따라
src.harness.hooks의 적절한 evaluator를 호출한다.

차단: exit 2 + stderr 사유
경고: exit 0 + stderr 메시지
통과: exit 0
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from src.harness.hooks import post_edit, pre_bash, pre_tool_use, stop

_REQUIRED_ARTIFACTS = ("pytest", "mypy", "ruff")


def _artifacts_path() -> Path:
    """Verifier가 기록하는 검증 산출물 파일 경로.

    HARNESS_CYCLE_ARTIFACTS_PATH로 오버라이드 가능(테스트 격리용),
    기본값은 harness 상태 디렉토리(`~/.kis-autotrader/cycle_artifacts.json`).
    """
    override = os.environ.get("HARNESS_CYCLE_ARTIFACTS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".kis-autotrader" / "cycle_artifacts.json"


def _load_artifacts_file() -> dict[str, object]:
    """검증 산출물 파일을 읽어 dict로 반환(없거나 손상 시 빈 dict)."""
    try:
        loaded = json.loads(_artifacts_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    event = payload.get("hook_event_name", "")
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if event == "PreToolUse":
        if tool == "Bash":
            bash_decision = pre_bash.evaluate(tool_input.get("command", ""))
            if bash_decision.blocked:
                print(f"[pre_bash] BLOCKED: {bash_decision.reason}", file=sys.stderr)
                return 2
            return 0
        edit_decision = pre_tool_use.evaluate(tool, tool_input)
        if edit_decision.blocked:
            print(f"[pre_tool_use] BLOCKED: {edit_decision.reason}", file=sys.stderr)
            return 2
        if edit_decision.warning:
            print(f"[pre_tool_use] WARN: {edit_decision.reason}", file=sys.stderr)
        return 0

    if event == "PostToolUse" and tool in ("Edit", "Write", "MultiEdit"):
        post_decision = post_edit.evaluate(
            tool_input.get("file_path", ""),
            file_count_in_cycle=int(payload.get("file_count_in_cycle", 1)),
        )
        if post_decision.warn:
            print(f"[post_edit] WARN: {post_decision.message}", file=sys.stderr)
        # ruff 실행은 wrapper 책임 밖 — Stop hook 시점에서 verifier가 수행
        return 0

    if event == "Stop":
        # Phase 3 hotfix: 자동 구현 사이클(run_auto_implement.sh/Cycle Orchestrator)이
        # HARNESS_CYCLE_VERIFICATION_REQUIRED=1을 export한 상태에서만 강제.
        # 일반 Claude Code 세션은 verification_artifacts 페이로드 부재로 무조건
        # 차단되던 디자인 결함 해결.
        if not os.environ.get("HARNESS_CYCLE_VERIFICATION_REQUIRED"):
            return 0
        # 산출물 출처 우선순위: Stop 페이로드 → verifier가 기록한 파일(폴백).
        # Claude Code Stop 이벤트는 verification_artifacts를 싣지 않으므로,
        # 파일 폴백이 없으면 사이클이 종료 시 항상 차단된다.
        artifacts = dict(payload.get("verification_artifacts", {}) or {})
        if not all(k in artifacts for k in _REQUIRED_ARTIFACTS):
            artifacts = {**_load_artifacts_file(), **artifacts}
        stop_decision = stop.evaluate(verification_artifacts=artifacts)
        if stop_decision.blocked:
            print(f"[stop] BLOCKED: {stop_decision.reason}", file=sys.stderr)
            return 2
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
