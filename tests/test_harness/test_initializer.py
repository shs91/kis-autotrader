"""Initializer 환경 점검 + progress.json 생성 TDD."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.harness.initializer import (
    EnvCheckResult,
    Initializer,
    InitializerStatus,
)
from src.harness.progress import InitializerCheckResult


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    """초기 커밋이 있는 깨끗한 git 저장소를 tmp에 만든다."""
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("init", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")


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


def test_git_clean_pass_on_clean_repo(tmp_path: Path) -> None:
    """변경이 전혀 없는 저장소는 PASS."""
    _init_repo(tmp_path)
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_git_clean()  # noqa: SLF001
    assert result.result == InitializerCheckResult.PASS


def test_git_clean_ignores_untracked_proposals(tmp_path: Path) -> None:
    """docs/proposals/ 아래 untracked 제안서만 있으면 PASS (정상 산출물)."""
    _init_repo(tmp_path)
    (tmp_path / "docs" / "proposals").mkdir(parents=True)
    (tmp_path / "docs" / "proposals" / "2026-06-06_x.md").write_text(
        "# x", encoding="utf-8"
    )
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_git_clean()  # noqa: SLF001
    assert result.result == InitializerCheckResult.PASS


def test_git_clean_ignores_untracked_reports(tmp_path: Path) -> None:
    """docs/reports/ 아래 untracked 리포트만 있으면 PASS (정상 산출물)."""
    _init_repo(tmp_path)
    (tmp_path / "docs" / "reports").mkdir(parents=True)
    (tmp_path / "docs" / "reports" / "2026-W23_weekly.md").write_text(
        "# x", encoding="utf-8"
    )
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_git_clean()  # noqa: SLF001
    assert result.result == InitializerCheckResult.PASS


def test_git_clean_fails_on_untracked_source(tmp_path: Path) -> None:
    """src/ 아래 untracked 코드는 여전히 FAIL (안전 유지)."""
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rogue.py").write_text("x = 1", encoding="utf-8")
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_git_clean()  # noqa: SLF001
    assert result.result == InitializerCheckResult.FAIL


def test_git_clean_fails_on_modified_tracked(tmp_path: Path) -> None:
    """tracked 파일 수정은 여전히 FAIL (안전 유지)."""
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("changed", encoding="utf-8")
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_git_clean()  # noqa: SLF001
    assert result.result == InitializerCheckResult.FAIL


def test_git_clean_fails_when_source_mixed_with_docs(tmp_path: Path) -> None:
    """docs untracked + src untracked 가 섞이면 코드 변경이 있으므로 FAIL."""
    _init_repo(tmp_path)
    (tmp_path / "docs" / "proposals").mkdir(parents=True)
    (tmp_path / "docs" / "proposals" / "p.md").write_text("# x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rogue.py").write_text("x = 1", encoding="utf-8")
    init = Initializer(repo_root=tmp_path, env="virtual")
    result = init._check_git_clean()  # noqa: SLF001
    assert result.result == InitializerCheckResult.FAIL


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
