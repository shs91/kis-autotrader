"""파일 경로 → component 분류.

3축 Observability의 Component 축. changed_files JSONB에 component 필드를 추가하면,
하네스 모듈 단위로 변경 빈도/재발률을 측정할 수 있다.
"""

from __future__ import annotations

import re

# 우선순위 순서로 매칭 (앞이 높은 우선순위)
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\.claude/agents/"), "harness/agent"),
    (re.compile(r"^\.claude/skills/"), "harness/skill"),
    (re.compile(r"^\.claude/settings\.json$"), "harness/hook"),
    (re.compile(r"^scripts/claude-hooks/"), "harness/hook"),
    (re.compile(r"^scripts/harness/pipeline_"), "harness/mcp"),
    (re.compile(r"^scripts/harness/run_verifier"), "harness/verifier"),
    (re.compile(r"^scripts/harness/sync_"), "harness/sync"),
    (re.compile(r"^scripts/harness/baseline_kpis"), "harness/observability"),
    (re.compile(r"^scripts/harness/"), "harness/script"),
    (re.compile(r"^scripts/auto_implement_prompt"), "harness/prompt"),
    (re.compile(r"^tests/eval/golden_proposals/"), "harness/golden"),
    (re.compile(r"^src/harness/"), "code/harness"),
    (re.compile(r"^src/strategy/"), "code/strategy"),
    (re.compile(r"^src/api/"), "code/api"),
    (re.compile(r"^src/db/"), "code/db"),
    (re.compile(r"^src/scheduler/"), "code/scheduler"),
    (re.compile(r"^src/notify/"), "code/notify"),
    (re.compile(r"^src/utils/"), "code/utils"),
    (re.compile(r"^src/worker/"), "code/worker"),
    (re.compile(r"^src/backtest/"), "code/backtest"),
    (re.compile(r"^src/calendar/"), "code/calendar"),
    (re.compile(r"^src/config\.py$"), "code/config"),
    (re.compile(r"^src/engine\.py$"), "code/engine"),
    (re.compile(r"^main\.py$"), "code/main"),
    (re.compile(r"^alembic/versions/"), "migration"),
    (re.compile(r"^pyproject\.toml$"), "config"),
    (re.compile(r"^\.env\.example$"), "config"),
    (re.compile(r"^holidays\.json$"), "config"),
    (re.compile(r"^docs/proposals/"), "docs/proposal"),
    (re.compile(r"^docs/harness/"), "docs/harness"),
    (re.compile(r"^docs/reports/"), "docs/report"),
    (re.compile(r"^docs/plans/"), "docs/plan"),
    (re.compile(r"^README\.md$"), "docs/readme"),
    (re.compile(r"^docs/"), "docs/other"),
    (re.compile(r"^Dockerfile"), "infra"),
    (re.compile(r"^docker-compose"), "infra"),
    (re.compile(r"^scripts/.*\.sh$"), "script"),
    (re.compile(r"^scripts/"), "script"),
    (re.compile(r"^tests/"), "test"),
)


def classify_component(path: str) -> str:
    """파일 경로 1건을 component 카테고리로 분류. 알 수 없으면 'other'."""
    normalized = path
    while normalized.startswith("./"):
        normalized = normalized[2:]
    for pattern, label in _RULES:
        if pattern.search(normalized):
            return label
    return "other"
