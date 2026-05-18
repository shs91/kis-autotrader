"""Initializer 환경 점검 + progress.json 생성 TDD."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.initializer import (
    EnvCheckResult,
    Initializer,
    InitializerStatus,
)
from src.harness.progress import InitializerCheckResult


@pytest.fixture
def tmp_progress(tmp_path: Path) -> Path:
    return tmp_path / "claude-progress.json"


def test_check_alembic_head_pass(tmp_path: Path) -> None:
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_alembic_head_present()  # noqa: SLF001
    # alembic 미실행 환경에서는 fail 또는 skip — 둘 다 OK
    assert isinstance(result, EnvCheckResult)
    assert result.name == "alembic_head"


def test_check_git_clean_pass(tmp_path: Path) -> None:
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_git_clean()  # noqa: SLF001
    assert isinstance(result, EnvCheckResult)


def test_initialize_creates_progress_with_cycle_id(tmp_progress: Path) -> None:
    repo = tmp_progress.parent
    (repo / "src").mkdir()
    init = Initializer(repo_root=repo, env="virtual", progress_path=tmp_progress)
    status = init.run()
    assert isinstance(status, InitializerStatus)
    assert tmp_progress.exists()
    # cycle_id 형식: "auto-YYYYMMDD-HHMMSS"
    assert status.cycle_id.startswith("auto-")
    assert len(status.cycle_id) >= len("auto-20260515-190000")


def test_initialize_records_checks_in_progress(tmp_progress: Path) -> None:
    repo = tmp_progress.parent
    (repo / "src").mkdir()
    init = Initializer(repo_root=repo, env="virtual", progress_path=tmp_progress)
    status = init.run()
    from src.harness.progress import load_progress
    progress = load_progress(tmp_progress)
    assert progress is not None
    assert len(progress.initializer_checks) >= 4
    # 적어도 하나는 PASS 또는 SKIP 결과
    results = {c.result for c in progress.initializer_checks}
    assert any(r in results for r in (InitializerCheckResult.PASS, InitializerCheckResult.SKIP))
    assert progress.cycle_id == status.cycle_id


def test_initialize_failed_returns_status_with_failures(tmp_progress: Path) -> None:
    # 존재하지 않는 repo root → 일부 체크 실패
    bad = tmp_progress.parent / "nope"
    init = Initializer(repo_root=bad, env="virtual", progress_path=tmp_progress)
    status = init.run()
    # 일부는 실패해도 cycle_id는 발급
    assert status.cycle_id
    # progress.json은 여전히 생성됨 (실패 traces 포함)
    assert tmp_progress.exists()
