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
import sys

from src.harness.hooks import post_edit, pre_bash, pre_tool_use, stop


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
        stop_decision = stop.evaluate(
            verification_artifacts=payload.get("verification_artifacts", {}) or {},
        )
        if stop_decision.blocked:
            print(f"[stop] BLOCKED: {stop_decision.reason}", file=sys.stderr)
            return 2
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
