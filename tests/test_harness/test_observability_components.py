"""파일 경로 → component 분류 TDD."""

from __future__ import annotations

import pytest

from src.harness.observability.components import classify_component


@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/strategy/rsi.py", "code/strategy"),
        ("src/api/auth.py", "code/api"),
        ("src/db/repository.py", "code/db"),
        ("src/scheduler/jobs.py", "code/scheduler"),
        ("src/notify/telegram.py", "code/notify"),
        ("src/utils/logger.py", "code/utils"),
        ("src/harness/initializer.py", "code/harness"),
        ("src/engine.py", "code/engine"),
        ("src/config.py", "code/config"),
        ("main.py", "code/main"),
        (".claude/agents/implementer.md", "harness/agent"),
        (".claude/skills/proposal-validation/SKILL.md", "harness/skill"),
        (".claude/settings.json", "harness/hook"),
        ("scripts/claude-hooks/run_hook.py", "harness/hook"),
        ("scripts/harness/pipeline_list_ready.py", "harness/mcp"),
        ("scripts/harness/run_verifier.py", "harness/verifier"),
        ("scripts/harness/sync_proposals_md_to_db.py", "harness/sync"),
        ("tests/eval/golden_proposals/G01_x/manifest.json", "harness/golden"),
        ("scripts/auto_implement_prompt.txt", "harness/prompt"),
        ("scripts/auto_implement_prompt_v2.txt", "harness/prompt"),
        ("alembic/versions/abc_xxx.py", "migration"),
        ("pyproject.toml", "config"),
        ("docs/proposals/2026-05-15_x.md", "docs/proposal"),
        ("docs/harness/phase4_completion.md", "docs/harness"),
        ("docs/reports/2026-05-15_daily.md", "docs/report"),
        ("README.md", "docs/readme"),
        ("Dockerfile", "infra"),
        ("docker-compose.yml", "infra"),
        ("scripts/run_dashboard.sh", "script"),
        ("scripts/backup_db.sh", "script"),
        ("tests/test_strategy/test_rsi.py", "test"),
        ("foo/bar/random.py", "other"),
    ],
)
def test_classify_known_paths(path: str, expected: str) -> None:
    assert classify_component(path) == expected
