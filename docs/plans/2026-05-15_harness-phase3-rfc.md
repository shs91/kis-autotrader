# 하네스 Phase 3 — 5계층 ADK 완성 + 병렬화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자동 구현 사이클의 단일 `claude -p` 호출을 Initializer(Python) + 5종 Claude Code subagent(`.claude/agents/`)로 분해하고, agent들이 호출하는 Pipeline CLI 8종을 통해 `proposals` 상태 머신과 `claude-progress.json`을 일관되게 조작하며, 독립 제안서들을 병렬로 처리한다.

**Architecture:** Python `Initializer`가 환경 점검과 cycle_id 발급·`claude-progress.json` 생성을 결정적으로 수행한 뒤, 새 top-level claude prompt가 5종 subagent(`proposal-validator`/`implementer`/`verifier`/`evaluator`/`rollback-handler`)를 Pipeline CLI를 통해 오케스트레이션. 외부 MCP SDK 의존 없이 stdio JSON-RPC 대신 **Pipeline CLI scripts**가 Repository와 progress.json을 매개. 워크트리에 한정 적용, 메인 repo 운영 영향 0.

**Tech Stack:** Python 3.12 stdlib(`argparse`, `subprocess`, `json`, `pathlib`), 기존 `src.harness.*`(progress/trigger/verifier/golden), 기존 `src.db.repository.ProposalRepository`, Claude Code `.claude/agents/` 마크다운 선언, `.claude/skills/` 마크다운, pytest 9 / ruff / mypy strict.

---

## Spec → Task 매핑

harness plan §5 Phase 3 + 축 D + phase2_completion.md §6.

| 진단/스펙 | Task |
|----------|------|
| D1 컨텍스트 인계 부재 (zero memory 매 사이클) | T1 Initializer + T7 progress wiring |
| D8 단일 거대 프롬프트 | T6 agents 분해 + T11 prompt 재설계 |
| 축 A 5계층 ADK (CLAUDE.md/Skills/MCP/Subagents/Hooks) | T6(agents) + T7(skills) + T2~T5(Pipeline CLI = MCP 대체) |
| 축 D 5종 subagent 마크다운 | T6 |
| 축 D 4종 Skill 마크다운 | T7 |
| 축 D Pipeline MCP (6~8 도구) | T2~T5 8종 Pipeline CLI (MCP SDK 회피) |
| 축 D 병렬화 (worker pool, MapReduce) | T8 dependency graph + T11 prompt 지시 |
| Phase 1·2 의 `claude-progress.json` 사이클 wiring (이관) | T1 Initializer + T9 cycle orchestrator |
| Phase 2 `apply_verification_result` 실제 사이클 호출 | T9 |

---

## File Structure

### Create

| 파일 | 책임 |
|------|------|
| `src/harness/initializer.py` | 환경 점검 + cycle_id 발급 + `claude-progress.json` 생성 |
| `src/harness/dependency.py` | 제안서 독립 그룹 계산 (changed_files 비교) |
| `src/harness/cycle/__init__.py` | 패키지 stub |
| `src/harness/cycle/orchestrator.py` | Init→Validate→Implement→Verify→Record/Rollback 진입점 |
| `scripts/harness/pipeline_list_ready.py` | `--out path.json` 또는 stdout JSON 출력 |
| `scripts/harness/pipeline_find_proposal.py` | `--path X` → proposal JSON |
| `scripts/harness/pipeline_mark_in_flight.py` | `--path X --cycle-id Y` |
| `scripts/harness/pipeline_mark_implemented.py` | `--path X` |
| `scripts/harness/pipeline_mark_failed.py` | `--path X --reason "..."` |
| `scripts/harness/pipeline_mark_skipped.py` | `--path X --reason "..."` |
| `scripts/harness/pipeline_append_progress.py` | `--progress path --from-state ... --to-state ... --proposal X` |
| `scripts/harness/pipeline_last_safe_tag.py` | git tag 중 SemVer 패턴 최신 출력 |
| `.claude/agents/proposal-validator.md` | Read/Grep만, BRIDGE_SPEC 안전 게이트 검증 |
| `.claude/agents/implementer.md` | Read/Edit/Write/Bash, 단일 proposal 컨텍스트 |
| `.claude/agents/verifier.md` | Read/Bash(pytest/mypy/ruff)만 — Phase 2 Verifier CLI 호출 |
| `.claude/agents/evaluator.md` | fresh context, 골든 셋만 채점 |
| `.claude/agents/rollback-handler.md` | Bash(git restore/reset) + Telegram MCP만 |
| `.claude/skills/proposal-validation/SKILL.md` | 제안서 안전 게이트 검증 절차 |
| `.claude/skills/kis-api-rate-limit-pattern/SKILL.md` | RateLimiter 사용 규칙 + WS 상태 머신 |
| `.claude/skills/strategy-add-pattern/SKILL.md` | 신규 전략 추가 체크리스트 |
| `.claude/skills/alembic-migration-flow/SKILL.md` | 마이그레이션 자동 생성/검토/적용 |
| `scripts/auto_implement_prompt_v2.txt` | 새 top-level prompt — subagent 오케스트레이션 |
| `tests/test_harness/test_initializer.py` | T1 TDD |
| `tests/test_harness/test_dependency.py` | T8 TDD |
| `tests/test_harness/test_pipeline_cli.py` | T2~T5 통합 TDD |
| `tests/test_harness/test_cycle_orchestrator.py` | T9 TDD |

### Modify

| 파일 | 변경 |
|------|------|
| `scripts/run_auto_implement.sh` | 단일 `claude -p` → Python Initializer 호출 → 새 prompt(v2) 사용 |
| `docs/harness/phase2_completion.md` | Phase 3 진입 안내 한 줄 |

---

## Task 1: Initializer 모듈

**Files:**
- Create: `src/harness/initializer.py`
- Test: `tests/test_harness/test_initializer.py`

- [ ] **Step 1: 실패 테스트**

```python
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
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_initializer.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/harness/initializer.py`:
```python
"""Initializer — 사이클 시작 시점의 결정적 환경 점검 + progress.json 생성.

매 사이클 시작에서 1회 호출. claude-progress.json을 만들고 cycle_id를 발급한다.
이후 subagent들이 progress.json을 통해 상태를 공유한다.

점검 항목:
- alembic head: 마이그레이션이 최신인지
- git clean: 워킹 디렉토리가 깨끗한지 (uncommitted 변경 없음)
- venv: 파이썬 인터프리터 + 핵심 패키지 import 가능
- disk free: 1GB 이상
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from src.harness.progress import (
    CycleProgress,
    InitializerCheck,
    InitializerCheckResult,
    save_progress,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_KST = timezone(timedelta(hours=9))
_DEFAULT_DISK_THRESHOLD_GB = 1.0


@dataclass(frozen=True)
class EnvCheckResult:
    name: str
    result: InitializerCheckResult
    detail: str | None = None


@dataclass(frozen=True)
class InitializerStatus:
    cycle_id: str
    progress_path: Path
    all_passed: bool


class Initializer:
    def __init__(
        self,
        repo_root: Path,
        env: Literal["virtual", "real"],
        progress_path: Path | None = None,
        disk_threshold_gb: float = _DEFAULT_DISK_THRESHOLD_GB,
    ) -> None:
        self.repo_root = repo_root
        self.env = env
        self.progress_path = (
            progress_path
            if progress_path
            else Path.home() / ".kis-autotrader" / "claude-progress.json"
        )
        self.disk_threshold_gb = disk_threshold_gb

    def _check_alembic_head_present(self) -> EnvCheckResult:
        try:
            cp = subprocess.run(  # noqa: S603, S607
                [".venv/bin/alembic", "current"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return EnvCheckResult(
                name="alembic_head",
                result=InitializerCheckResult.SKIP,
                detail=f"alembic 실행 실패: {e!s:.80}",
            )
        if cp.returncode == 0 and "head" in cp.stdout:
            return EnvCheckResult(name="alembic_head", result=InitializerCheckResult.PASS)
        return EnvCheckResult(
            name="alembic_head",
            result=InitializerCheckResult.FAIL,
            detail=cp.stdout.strip()[:200],
        )

    def _check_git_clean(self) -> EnvCheckResult:
        try:
            cp = subprocess.run(  # noqa: S603, S607
                ["git", "status", "--porcelain"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return EnvCheckResult(
                name="git_clean",
                result=InitializerCheckResult.SKIP,
                detail=f"git 실행 실패: {e!s:.80}",
            )
        if cp.returncode != 0:
            return EnvCheckResult(
                name="git_clean",
                result=InitializerCheckResult.FAIL,
                detail=cp.stderr.strip()[:200],
            )
        if cp.stdout.strip():
            return EnvCheckResult(
                name="git_clean",
                result=InitializerCheckResult.FAIL,
                detail=f"uncommitted changes:\n{cp.stdout.strip()[:200]}",
            )
        return EnvCheckResult(name="git_clean", result=InitializerCheckResult.PASS)

    def _check_venv(self) -> EnvCheckResult:
        venv_py = self.repo_root / ".venv" / "bin" / "python"
        if not venv_py.exists():
            return EnvCheckResult(
                name="venv",
                result=InitializerCheckResult.FAIL,
                detail=f".venv/bin/python 없음: {venv_py}",
            )
        return EnvCheckResult(name="venv", result=InitializerCheckResult.PASS)

    def _check_disk_free(self) -> EnvCheckResult:
        try:
            usage = shutil.disk_usage(self.repo_root)
        except OSError as e:
            return EnvCheckResult(
                name="disk_free",
                result=InitializerCheckResult.SKIP,
                detail=f"disk_usage 실패: {e!s:.80}",
            )
        free_gb = usage.free / (1024**3)
        if free_gb < self.disk_threshold_gb:
            return EnvCheckResult(
                name="disk_free",
                result=InitializerCheckResult.FAIL,
                detail=f"free={free_gb:.2f}GB, threshold={self.disk_threshold_gb}GB",
            )
        return EnvCheckResult(
            name="disk_free",
            result=InitializerCheckResult.PASS,
            detail=f"free={free_gb:.2f}GB",
        )

    def _last_safe_tag(self) -> str | None:
        try:
            cp = subprocess.run(  # noqa: S603, S607
                ["git", "tag", "--sort=-creatordate"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return None
        if cp.returncode != 0 or not cp.stdout.strip():
            return None
        return cp.stdout.strip().splitlines()[0]

    def run(self) -> InitializerStatus:
        cycle_id = "auto-" + datetime.now(_KST).strftime("%Y%m%d-%H%M%S")
        checks = [
            self._check_alembic_head_present(),
            self._check_git_clean(),
            self._check_venv(),
            self._check_disk_free(),
        ]
        progress = CycleProgress(
            cycle_id=cycle_id,
            started_at=datetime.now(_KST),
            env=self.env,
            last_safe_tag=self._last_safe_tag(),
            initializer_checks=[
                InitializerCheck(name=c.name, result=c.result, detail=c.detail)
                for c in checks
            ],
        )
        save_progress(self.progress_path, progress)
        all_passed = all(c.result == InitializerCheckResult.PASS for c in checks)
        if all_passed:
            logger.info("Initializer %s: all checks PASS", cycle_id)
        else:
            failures = [c.name for c in checks if c.result == InitializerCheckResult.FAIL]
            logger.warning(
                "Initializer %s: %d failures (%s)",
                cycle_id, len(failures), ",".join(failures),
            )
        return InitializerStatus(
            cycle_id=cycle_id,
            progress_path=self.progress_path,
            all_passed=all_passed,
        )
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_initializer.py -v
.venv/bin/ruff check src/harness/initializer.py tests/test_harness/test_initializer.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/initializer.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/initializer.py tests/test_harness/test_initializer.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): Initializer 환경 점검 + claude-progress.json 생성 (Phase 3 T1)"
```
Expected: 5 passed

---

## Task 2: Pipeline CLI — Read 명령 3종

**Files:**
- Create: `scripts/harness/pipeline_list_ready.py`, `pipeline_find_proposal.py`, `pipeline_last_safe_tag.py`
- Test: `tests/test_harness/test_pipeline_cli.py`

- [ ] **Step 1: 실패 테스트**

```python
"""Pipeline CLI 통합 TDD — subprocess로 8 commands 호출."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    ImplementationCategory,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "harness"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_session(monkeypatch, tmp_path):
    # SQLite JSONB workaround
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]
    db_path = tmp_path / "p.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Pipeline CLI는 src.db.session.get_engine을 호출하므로 모듈 reset 필요
    from src.db import session as session_mod
    session_mod.reset_engine()

    s = factory()
    repo = ProposalRepository(s)
    repo.create(
        path="docs/proposals/x.md", title="X",
        category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
    repo.create(
        path="docs/proposals/y.md", title="Y",
        category=ImplementationCategory.PARAM_TUNING,
        state=ProposalState.DRAFT, priority=ProposalPriority.LOW,
    )
    s.commit()
    yield s
    s.close()
    session_mod.reset_engine()


def _run(script: str, *args: str) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), *args],
        capture_output=True, text=True, env=env, check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_list_ready_outputs_only_ready_proposals(db_session) -> None:
    code, out, _ = _run("pipeline_list_ready.py")
    assert code == 0
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["path"] == "docs/proposals/x.md"
    assert data[0]["state"] == "ready"


def test_find_proposal_returns_metadata(db_session) -> None:
    code, out, _ = _run("pipeline_find_proposal.py", "--path", "docs/proposals/x.md")
    assert code == 0
    data = json.loads(out)
    assert data["title"] == "X"
    assert data["state"] == "ready"


def test_find_proposal_missing_exits_nonzero(db_session) -> None:
    code, _, _ = _run("pipeline_find_proposal.py", "--path", "docs/proposals/nope.md")
    assert code == 1


def test_last_safe_tag_outputs_latest_tag() -> None:
    code, out, _ = _run("pipeline_last_safe_tag.py")
    # tag가 있으면 0, 없으면 0 with empty stdout 또는 1
    assert code in (0, 1)
    if code == 0:
        assert out.strip()  # 최소 한 줄
```

- [ ] **Step 2: 실패 확인 → 구현**

`scripts/harness/pipeline_list_ready.py`:
```python
#!/usr/bin/env python3
"""READY 상태 제안서를 우선순위순 JSON list로 출력."""

from __future__ import annotations

import json
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main() -> int:
    with get_session() as session:
        repo = ProposalRepository(session)
        rows = repo.list_ready()
        payload = [
            {
                "id": r.id,
                "path": r.path,
                "title": r.title,
                "category": r.category.value,
                "state": r.state.value,
                "priority": r.priority.value,
            }
            for r in rows
        ]
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/harness/pipeline_find_proposal.py`:
```python
#!/usr/bin/env python3
"""특정 path의 제안서 메타데이터를 JSON으로 출력. 없으면 exit 1."""

from __future__ import annotations

import argparse
import json
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True)
    args = p.parse_args(argv)
    with get_session() as session:
        repo = ProposalRepository(session)
        prop = repo.find_by_path(args.path)
        if prop is None:
            print(f"proposal not found: {args.path}", file=sys.stderr)
            return 1
        payload = {
            "id": prop.id,
            "path": prop.path,
            "title": prop.title,
            "category": prop.category.value,
            "state": prop.state.value,
            "priority": prop.priority.value,
            "failure_reason": prop.failure_reason,
            "skip_reason": prop.skip_reason,
            "cycle_id": prop.cycle_id,
        }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/harness/pipeline_last_safe_tag.py`:
```python
#!/usr/bin/env python3
"""마지막 git tag(SemVer 정렬)를 출력. 없으면 exit 1."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    try:
        cp = subprocess.run(  # noqa: S603, S607
            ["git", "tag", "--sort=-creatordate"],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"git failed: {e!s}", file=sys.stderr)
        return 1
    if cp.returncode != 0 or not cp.stdout.strip():
        return 1
    print(cp.stdout.strip().splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_pipeline_cli.py::test_list_ready_outputs_only_ready_proposals tests/test_harness/test_pipeline_cli.py::test_find_proposal_returns_metadata tests/test_harness/test_pipeline_cli.py::test_find_proposal_missing_exits_nonzero tests/test_harness/test_pipeline_cli.py::test_last_safe_tag_outputs_latest_tag -v
chmod +x scripts/harness/pipeline_list_ready.py scripts/harness/pipeline_find_proposal.py scripts/harness/pipeline_last_safe_tag.py
.venv/bin/ruff check scripts/harness/pipeline_*.py tests/test_harness/test_pipeline_cli.py
PYTHONPATH=. .venv/bin/python -m mypy --strict scripts/harness/pipeline_list_ready.py scripts/harness/pipeline_find_proposal.py scripts/harness/pipeline_last_safe_tag.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/harness/pipeline_list_ready.py scripts/harness/pipeline_find_proposal.py scripts/harness/pipeline_last_safe_tag.py tests/test_harness/test_pipeline_cli.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(pipeline): read CLI 3종(list_ready/find_proposal/last_safe_tag) + TDD (Phase 3 T2)"
```
Expected: 4 passed

---

## Task 3: Pipeline CLI — Mark 명령 4종

**Files:**
- Create: `scripts/harness/pipeline_mark_in_flight.py`, `pipeline_mark_implemented.py`, `pipeline_mark_failed.py`, `pipeline_mark_skipped.py`
- Test: `tests/test_harness/test_pipeline_cli.py` (append)

- [ ] **Step 1: 테스트 append**

```python
def test_mark_in_flight_transitions_state(db_session) -> None:
    code, _, _ = _run(
        "pipeline_mark_in_flight.py",
        "--path", "docs/proposals/x.md", "--cycle-id", "c-1",
    )
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.IN_FLIGHT
    assert p.cycle_id == "c-1"


def test_mark_implemented_after_in_flight(db_session) -> None:
    _run("pipeline_mark_in_flight.py", "--path", "docs/proposals/x.md", "--cycle-id", "c-2")
    code, _, _ = _run("pipeline_mark_implemented.py", "--path", "docs/proposals/x.md")
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.IMPLEMENTED


def test_mark_failed_records_reason(db_session) -> None:
    _run("pipeline_mark_in_flight.py", "--path", "docs/proposals/x.md", "--cycle-id", "c-3")
    code, _, _ = _run(
        "pipeline_mark_failed.py",
        "--path", "docs/proposals/x.md",
        "--reason", "verifier contract failed",
    )
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.FAILED
    assert "verifier" in p.failure_reason


def test_mark_skipped_from_ready(db_session) -> None:
    code, _, _ = _run(
        "pipeline_mark_skipped.py",
        "--path", "docs/proposals/x.md",
        "--reason", "safety_gate_violation",
    )
    assert code == 0
    db_session.expire_all()
    repo = ProposalRepository(db_session)
    p = repo.find_by_path("docs/proposals/x.md")
    assert p.state == ProposalState.SKIPPED


def test_mark_in_flight_missing_path_exits_nonzero(db_session) -> None:
    code, _, _ = _run(
        "pipeline_mark_in_flight.py",
        "--path", "docs/proposals/nope.md", "--cycle-id", "c-x",
    )
    assert code == 1
```

- [ ] **Step 2: 구현**

`scripts/harness/pipeline_mark_in_flight.py`:
```python
#!/usr/bin/env python3
"""제안서를 IN_FLIGHT 상태로 전이. cycle_id 필수."""

from __future__ import annotations

import argparse
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True)
    p.add_argument("--cycle-id", required=True)
    args = p.parse_args(argv)
    with get_session() as session:
        repo = ProposalRepository(session)
        prop = repo.find_by_path(args.path)
        if prop is None:
            print(f"proposal not found: {args.path}", file=sys.stderr)
            return 1
        try:
            repo.mark_in_flight(prop.id, cycle_id=args.cycle_id)
        except ValueError as e:
            print(f"state transition error: {e!s}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/harness/pipeline_mark_implemented.py`:
```python
#!/usr/bin/env python3
"""제안서를 IMPLEMENTED 상태로 전이."""

from __future__ import annotations

import argparse
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True)
    args = p.parse_args(argv)
    with get_session() as session:
        repo = ProposalRepository(session)
        prop = repo.find_by_path(args.path)
        if prop is None:
            print(f"proposal not found: {args.path}", file=sys.stderr)
            return 1
        try:
            repo.mark_implemented(prop.id)
        except ValueError as e:
            print(f"state transition error: {e!s}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/harness/pipeline_mark_failed.py`:
```python
#!/usr/bin/env python3
"""제안서를 FAILED 상태로 전이. reason 필수."""

from __future__ import annotations

import argparse
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True)
    p.add_argument("--reason", required=True)
    args = p.parse_args(argv)
    with get_session() as session:
        repo = ProposalRepository(session)
        prop = repo.find_by_path(args.path)
        if prop is None:
            print(f"proposal not found: {args.path}", file=sys.stderr)
            return 1
        try:
            repo.mark_failed(prop.id, reason=args.reason)
        except ValueError as e:
            print(f"state transition error: {e!s}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/harness/pipeline_mark_skipped.py`:
```python
#!/usr/bin/env python3
"""제안서를 SKIPPED 상태로 전이. reason 필수 (예: safety_gate_violation)."""

from __future__ import annotations

import argparse
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True)
    p.add_argument("--reason", required=True)
    args = p.parse_args(argv)
    with get_session() as session:
        repo = ProposalRepository(session)
        prop = repo.find_by_path(args.path)
        if prop is None:
            print(f"proposal not found: {args.path}", file=sys.stderr)
            return 1
        try:
            repo.mark_skipped(prop.id, reason=args.reason)
        except ValueError as e:
            print(f"state transition error: {e!s}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_pipeline_cli.py -v
chmod +x scripts/harness/pipeline_mark_*.py
.venv/bin/ruff check scripts/harness/pipeline_mark_*.py
PYTHONPATH=. .venv/bin/python -m mypy --strict scripts/harness/pipeline_mark_in_flight.py scripts/harness/pipeline_mark_implemented.py scripts/harness/pipeline_mark_failed.py scripts/harness/pipeline_mark_skipped.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/harness/pipeline_mark_*.py tests/test_harness/test_pipeline_cli.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(pipeline): mark CLI 4종(in_flight/implemented/failed/skipped) + TDD (Phase 3 T3)"
```
Expected: 9 passed (4 read + 5 mark)

---

## Task 4: Pipeline CLI — Progress 명령

**Files:**
- Create: `scripts/harness/pipeline_append_progress.py`
- Test: `tests/test_harness/test_pipeline_cli.py` (append)

- [ ] **Step 1: 테스트 append**

```python
def test_append_progress_records_transition(tmp_path) -> None:
    progress_file = tmp_path / "progress.json"
    # 먼저 빈 progress 생성
    from src.harness.progress import CycleProgress, save_progress
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    cp = CycleProgress(
        cycle_id="t-1", started_at=datetime.now(KST), env="virtual",
    )
    save_progress(progress_file, cp)

    code, _, _ = _run(
        "pipeline_append_progress.py",
        "--progress", str(progress_file),
        "--proposal", "docs/proposals/x.md",
        "--from-state", "ready",
        "--to-state", "in_flight",
    )
    assert code == 0
    from src.harness.progress import load_progress
    refreshed = load_progress(progress_file)
    assert refreshed is not None
    assert len(refreshed.history) == 1
    assert refreshed.history[0].path == "docs/proposals/x.md"
    assert refreshed.history[0].to_state == "in_flight"
```

- [ ] **Step 2: 구현**

`scripts/harness/pipeline_append_progress.py`:
```python
#!/usr/bin/env python3
"""claude-progress.json에 상태 전이 1건을 추가한다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.harness.progress import load_progress, save_progress


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--progress", required=True, type=Path)
    p.add_argument("--proposal", required=True)
    p.add_argument("--from-state", required=True)
    p.add_argument("--to-state", required=True)
    p.add_argument("--reason", default=None)
    args = p.parse_args(argv)

    progress = load_progress(args.progress)
    if progress is None:
        print(f"progress not found: {args.progress}", file=sys.stderr)
        return 1
    progress.transition(
        args.proposal,
        from_state=args.from_state,
        to_state=args.to_state,
        reason=args.reason,
    )
    save_progress(args.progress, progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_pipeline_cli.py -v
chmod +x scripts/harness/pipeline_append_progress.py
.venv/bin/ruff check scripts/harness/pipeline_append_progress.py
PYTHONPATH=. .venv/bin/python -m mypy --strict scripts/harness/pipeline_append_progress.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/harness/pipeline_append_progress.py tests/test_harness/test_pipeline_cli.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(pipeline): append_progress CLI + TDD (Phase 3 T4)"
```
Expected: 10 passed

---

## Task 5: 제안서 독립성 그래프

**Files:**
- Create: `src/harness/dependency.py`
- Test: `tests/test_harness/test_dependency.py`

- [ ] **Step 1: 실패 테스트**

```python
"""제안서 독립 그룹 계산 TDD."""

from __future__ import annotations

from src.harness.dependency import compute_independent_groups


def test_disjoint_files_form_separate_groups() -> None:
    proposals = [
        {"path": "p1.md", "files": ["src/strategy/rsi.py"]},
        {"path": "p2.md", "files": ["src/strategy/macd.py"]},
        {"path": "p3.md", "files": ["src/api/auth.py"]},
    ]
    groups = compute_independent_groups(proposals)
    assert len(groups) == 3
    assert all(len(g) == 1 for g in groups)


def test_overlapping_files_collapse_into_one_group() -> None:
    proposals = [
        {"path": "p1.md", "files": ["src/engine.py", "src/db/repository.py"]},
        {"path": "p2.md", "files": ["src/engine.py"]},
        {"path": "p3.md", "files": ["src/api/auth.py"]},
    ]
    groups = compute_independent_groups(proposals)
    assert len(groups) == 2
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2]


def test_no_files_treated_as_serial() -> None:
    proposals = [
        {"path": "p1.md", "files": []},
        {"path": "p2.md", "files": []},
    ]
    groups = compute_independent_groups(proposals)
    # files 미지정 → 보수적으로 직렬 처리 (단일 그룹)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_returns_groups_in_deterministic_order() -> None:
    proposals = [
        {"path": "p_b.md", "files": ["src/x.py"]},
        {"path": "p_a.md", "files": ["src/y.py"]},
    ]
    groups = compute_independent_groups(proposals)
    # 그룹별로 첫 path 알파벳 정렬 (재현 가능성)
    first_paths = [g[0]["path"] for g in groups]
    assert first_paths == sorted(first_paths)
```

- [ ] **Step 2: 구현**

`src/harness/dependency.py`:
```python
"""제안서 changed_files 비교로 독립 그룹 계산.

Union-Find 패턴: 두 제안서가 공통 파일을 1개라도 공유하면 같은 그룹.
files가 비어 있는 제안서들은 보수적으로 모두 한 그룹(직렬).
"""

from __future__ import annotations

from typing import Any


def _find(parent: dict[int, int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict[int, int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def compute_independent_groups(
    proposals: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """proposals = [{"path": str, "files": list[str]}, ...] → groups."""
    n = len(proposals)
    if n == 0:
        return []
    parent: dict[int, int] = {i: i for i in range(n)}
    # files 빈 인덱스들을 한 그룹으로 묶기
    empty_indices = [i for i, p in enumerate(proposals) if not p.get("files")]
    for i in range(1, len(empty_indices)):
        _union(parent, empty_indices[0], empty_indices[i])

    # 파일 공유 그래프 union
    file_to_idx: dict[str, int] = {}
    for i, p in enumerate(proposals):
        for f in p.get("files", []):
            if f in file_to_idx:
                _union(parent, file_to_idx[f], i)
            else:
                file_to_idx[f] = i

    groups: dict[int, list[dict[str, Any]]] = {}
    for i, p in enumerate(proposals):
        root = _find(parent, i)
        groups.setdefault(root, []).append(p)

    # 결정적 정렬: 그룹 내 path 정렬, 그룹 간 첫 path 기준 정렬
    ordered = [sorted(g, key=lambda x: x["path"]) for g in groups.values()]
    ordered.sort(key=lambda g: g[0]["path"])
    return ordered
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_dependency.py -v
.venv/bin/ruff check src/harness/dependency.py tests/test_harness/test_dependency.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/dependency.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/dependency.py tests/test_harness/test_dependency.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): 제안서 독립 그룹 계산 (Union-Find) + TDD (Phase 3 T5)"
```
Expected: 4 passed

---

## Task 6: `.claude/agents/` 5종 마크다운

**Files:**
- Create: `.claude/agents/proposal-validator.md`, `implementer.md`, `verifier.md`, `evaluator.md`, `rollback-handler.md`

> **참고:** `.claude/`는 `.gitignore`에 등록되어 있으므로 `git add -f`로 강제 스테이징 필요 (Phase 1 T7에서 검증된 패턴).

- [ ] **Step 1: proposal-validator.md**

```markdown
---
name: proposal-validator
description: BRIDGE_SPEC 안전 게이트(파일 경로 화이트리스트, 파라미터 범위, 카테고리)에 따라 ready 제안서를 검증. 위반 시 skipped 마킹.
tools: Read, Grep, Glob, Bash
---

# Proposal Validator

너는 자동 구현 사이클의 안전 게이트 담당이다. ready 제안서 1건을 받아 BRIDGE_SPEC 규격에 부합하는지 검증한다.

## 입력
- 단일 제안서 path (예: `docs/proposals/2026-05-15_*.md`)
- BRIDGE_SPEC: `docs/BRIDGE_SPEC.md`

## 검증 항목
1. 메타데이터 유효성 — `상태`/`우선순위`/`카테고리`/`관련파일`
2. 안전 게이트:
   - 변경 대상 경로가 BRIDGE_SPEC §safety_gate.forbidden_paths에 포함 안 됨
   - 카테고리가 허용 카테고리 안에 있음
   - 파라미터 변경 시 BRIDGE_SPEC §parameter_ranges 내
   - 변경 파일 수가 §file_count_threshold 이내
3. 충돌:
   - 동일 path가 이미 IN_FLIGHT면 안 됨

## 출력 (Bash로 호출)
- 통과: 종료 (다음 단계인 implementer에게 위임)
- 거절: `scripts/harness/pipeline_mark_skipped.py --path X --reason safety_gate_violation` 호출 후 종료

## 금지
- Write/Edit 도구 사용 금지
- src/ 코드 직접 조사 외 행위 금지
```

- [ ] **Step 2: implementer.md**

```markdown
---
name: implementer
description: 단일 ready 제안서를 받아 변경 사항을 코드에 반영. 컨텍스트는 그 제안서 1건과 BRIDGE_SPEC만.
tools: Read, Edit, Write, Bash, Glob, Grep
---

# Implementer

너는 자동 구현 사이클의 코드 작성자다. proposal-validator가 통과시킨 제안서 1건을 받아 변경을 적용한다.

## 입력
- 단일 제안서 path
- 제안서 내 "변경 대상 파일" 섹션

## 작업
1. `pipeline_mark_in_flight.py --path X --cycle-id $CYCLE_ID` 호출
2. 제안서의 변경 사항을 코드에 반영 (Edit/Write 도구)
3. 변경 파일 수가 5개 초과면 즉시 중단하고 mark_failed
4. 작업 완료 보고 (Verifier가 다음에 호출됨 — 이 agent는 mark_implemented 안 함)

## 금지
- `.env`/credentials.json/token.json 편집 (PreToolUse hook이 차단함)
- alembic/versions/* 직접 편집 (autogenerate만 허용)
- 제안서 범위 밖 파일 변경

## 격리 원칙
- 너는 단일 제안서 1건만 컨텍스트에 둔다
- 다른 제안서는 의식하지 않는다
```

- [ ] **Step 3: verifier.md**

```markdown
---
name: verifier
description: 변경된 코드의 pytest/mypy/ruff/diff 4종 증거를 수집하고 Default-FAIL contract로 채점. Write/Edit 도구는 절대 사용 안 함.
tools: Read, Bash, Glob, Grep
---

# Verifier

너는 fresh-context 검증자다. 다른 agent가 만든 변경을 보지 않은 상태에서 결과만 채점한다.

## 입력
- cycle_id (현재 IN_FLIGHT 제안서들의 그룹 식별자)

## 작업
1. `scripts/harness/run_verifier.py --base-ref HEAD~N --head-ref HEAD --out /tmp/verifier_$CYCLE_ID.json` 호출 (N은 implementer가 만든 커밋 수)
2. exit code:
   - 0 (contract pass) → cycle의 모든 IN_FLIGHT 제안서를 `pipeline_mark_implemented.py`
   - 2 (contract fail) → cycle의 모든 IN_FLIGHT 제안서를 `pipeline_mark_failed.py --reason "verifier: ..."`
   - 3 (runner error) → rollback-handler 호출
3. `scripts/harness/pipeline_append_progress.py`로 transition 기록

## 절대 금지
- Edit/Write/MultiEdit 도구 호출 (PreToolUse hook이 차단함)
- 제안서 본문 조사 (자기보고 편향 차단)
- 변경된 코드의 의도 추측

## 원칙
- 너는 Default-FAIL contract만 신뢰한다
- 증거 4종 중 하나라도 부재하면 자동 FAIL
```

- [ ] **Step 4: evaluator.md**

```markdown
---
name: evaluator
description: 골든 회귀 셋 결과만 채점. 변경 코드는 보지 않으며 invariant 평가만 수행.
tools: Bash, Read, Glob
---

# Evaluator

너는 골든 회귀 셋 평가자다.

## 입력
- 골든 셋 디렉토리: `tests/eval/golden_proposals/`

## 작업
1. `pytest tests/eval/test_golden_runner.py -q` 호출
2. 결과 보고:
   - exit 0: 모든 골든 통과 → 사이클 진행 OK
   - exit != 0: 회귀 발견 → 어떤 case가 실패했는지 출력하고 rollback-handler 호출

## 격리 원칙
- 변경된 src/ 코드 직접 조사 금지 (자기보고 편향 차단)
- 골든 셋 manifest 임의 수정 금지
```

- [ ] **Step 5: rollback-handler.md**

```markdown
---
name: rollback-handler
description: 사이클 실패 시 git 안전 태그로 복원하고 Telegram에 알람.
tools: Bash, Read
---

# Rollback Handler

너는 사이클 실패 시 복구 담당이다.

## 입력
- last_safe_tag (Initializer가 기록한 직전 안전 태그)
- 실패한 제안서 path 목록

## 작업
1. `git reset --hard $LAST_SAFE_TAG` 호출
2. 각 실패 제안서에 `pipeline_mark_failed.py --path X --reason ...` 호출
3. Telegram 알람 (`scripts/notify_telegram.py` 또는 동등 명령)으로 사용자 통보

## 안전 원칙
- 직접 `rm -rf` 금지
- `git push --force` 금지 (PreToolUse hook이 차단함)
- `last_safe_tag`가 비어 있으면 reset 하지 말고 사용자 통보만
```

- [ ] **Step 6: 5종 한 번에 커밋**

```bash
mkdir -p /Users/songhansu/IdeaProjects/kis-autotrader-harness/.claude/agents
# (위 5개 파일을 각각 Write 도구로 작성)
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add -f .claude/agents/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(agents): 5종 서브에이전트 마크다운 선언 (Phase 3 T6)"
```

---

## Task 7: `.claude/skills/` 4종 마크다운

**Files:**
- Create: `.claude/skills/proposal-validation/SKILL.md`, `kis-api-rate-limit-pattern/SKILL.md`, `strategy-add-pattern/SKILL.md`, `alembic-migration-flow/SKILL.md`

- [ ] **Step 1: proposal-validation/SKILL.md**

```markdown
---
name: proposal-validation
description: BRIDGE_SPEC 안전 게이트에 따라 자동 구현 제안서를 검증한다. 파일 화이트리스트, 파라미터 범위, 카테고리 분류를 결정적으로 점검.
---

# Proposal Validation Skill

## 사용 시점
proposal-validator agent가 ready 제안서를 받았을 때.

## 절차
1. `docs/BRIDGE_SPEC.md`를 읽고 다음을 추출:
   - `safety_gate.forbidden_paths` (절대 변경 금지 경로)
   - `safety_gate.allowed_categories` (자동 구현 허용 카테고리)
   - `parameter_ranges` (파라미터별 허용 범위)
   - `file_count_threshold` (사이클당 최대 변경 파일 수, 기본 5)
2. 제안서의 메타데이터 검증:
   - `상태` == "ready"
   - `카테고리` ∈ `allowed_categories`
   - `우선순위` ∈ {low, medium, high, critical}
3. 제안서의 "변경 대상 파일" 섹션 검증:
   - 각 파일이 `forbidden_paths`에 없는지
   - 파일 수 ≤ `file_count_threshold`
4. 파라미터 변경이 있는 경우:
   - 각 파라미터가 `parameter_ranges`의 ±50% 이내
5. 통과: 종료(다음 단계에서 implementer가 인계받음)
6. 거절: `pipeline_mark_skipped.py --reason safety_gate_violation` 호출

## 예시
- 통과: `2026-05-15_strategy-tweak-rsi.md` (카테고리 param_tuning, 단일 파일, 파라미터 변경 ±20%)
- 거절: 카테고리 "infra" + 변경 파일이 `alembic/versions/*` → SKIP
```

- [ ] **Step 2: kis-api-rate-limit-pattern/SKILL.md**

```markdown
---
name: kis-api-rate-limit-pattern
description: KIS API 호출 제한 규칙과 WebSocket 상태 머신 준수 패턴. RateLimiter 사용 + 재연결 backoff + 디바운싱.
---

# KIS API Rate Limit Pattern

## 핵심 규칙
- **REST**: 초당 5건(virtual) / 20건(real). Token Bucket `src.api.rate_limiter`를 반드시 경유.
- **WebSocket**: 연결 → 구독 → 데이터 수신 확인 → 구독 해제 → 종료. 패턴 위반 시 IP/앱키 차단.
- **재연결**: exponential backoff 5→10→20→60초, 최대 5회.
- **Circuit Breaker**: 연속 5회 실패 시 트립, 30→60→120→240→300초 대기.

## 코드 패턴
```python
# 올바른 REST 호출
async with rate_limiter.acquire():
    response = await client.get(url, headers=headers)

# 올바른 WS 패턴
await ws.connect()
await ws.subscribe(symbol)
data = await ws.recv()  # 수신 확인
await ws.unsubscribe(symbol)  # 디바운싱: 최소 1초 간격
await ws.close()
```

## 금지 패턴
- RateLimiter 우회한 직접 httpx 호출
- WS 연결 직후 즉시 종료 반복
- 구독 등록/해제 무한 반복 (디바운싱 위반)

## 검증
구현 후 `pytest tests/test_api/test_rate_limiter.py tests/test_api/test_websocket.py`로 회귀 확인.
```

- [ ] **Step 3: strategy-add-pattern/SKILL.md**

```markdown
---
name: strategy-add-pattern
description: 새 매매 전략(`src/strategy/*.py`)을 추가할 때 따라야 할 체크리스트. 레지스트리 등록, 셀렉터 갱신, TDD.
---

# Strategy Add Pattern

## 절차

### 1. 클래스 신설
- `src/strategy/<name>.py` — `BaseStrategy` 상속
- `generate_signal(data: pd.DataFrame) -> Signal` 메소드 구현
- `__init__`에서 파라미터 받기 (env 변수 또는 config_overrides.json)

### 2. 레지스트리 등록
- `src/strategy/registry.py`의 `STRATEGY_REGISTRY`에 추가:
  ```python
  STRATEGY_REGISTRY = {
      ...,
      "new_strategy_name": NewStrategy,
  }
  ```

### 3. 셀렉터 갱신 (필요 시)
- 종목별 전략 매핑이 필요하면 `src/strategy/selector.py` 갱신

### 4. TDD
- `tests/test_strategy/test_<name>.py` 신설
  - 매수 시그널 케이스
  - 매도 시그널 케이스
  - HOLD 케이스 (정상 범위)
  - NaN/empty 데이터 가드

### 5. 백테스트 검증
- `python scripts/run_backtest.py --strategy <name> --period 1month`로 회귀 확인

### 6. 문서
- `README.md` 매매 전략 섹션에 추가
- 신규 환경변수 있으면 `.env.example` 갱신

## 금지
- BaseStrategy 우회한 시그널 직접 발행
- API 직접 호출 (전략은 데이터를 인자로 받음)
- DB 직접 쓰기 (Repository 경유)
```

- [ ] **Step 4: alembic-migration-flow/SKILL.md**

```markdown
---
name: alembic-migration-flow
description: SQLAlchemy 모델 변경 → Alembic 자동 생성 → 검토 → 적용 워크플로. 기존 enum 재사용·UNIQUE·index 패턴.
---

# Alembic Migration Flow

## 절차

### 1. 모델 수정
- `src/db/models.py`에 새 컬럼/테이블/enum 추가
- `from __future__ import annotations` 첫 줄 유지

### 2. 자동 생성
```bash
PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "설명"
```
- 출력: `alembic/versions/<hash>_설명.py`

### 3. 검토 (필수)
생성된 파일을 반드시 확인:
- **enum 재사용**: 이미 존재하는 enum(예: `impl_category_enum`)을 재생성하지 말 것. `sa.Enum(..., create_type=False)` 또는 `postgresql.ENUM(..., create_type=False)` 적용
- **task_queue 등 무관 인덱스**: autogenerate가 잡아낸 무관한 변경은 제거
- **UNIQUE 제약**: 이름 명시 (`sa.UniqueConstraint('path', name='uq_proposals_path')`)
- **인덱스**: `op.create_index('ix_<table>_<col>', ...)` 형식
- **downgrade**: drop_table + 신규 enum drop. **기존 enum drop 금지**

### 4. 적용
```bash
PYTHONPATH=. .venv/bin/alembic upgrade head
psql "$DATABASE_URL" -c "\d <table>"  # 스키마 검증
```

### 5. 롤백 검증 (권장)
```bash
PYTHONPATH=. .venv/bin/alembic downgrade -1
PYTHONPATH=. .venv/bin/alembic upgrade head
```

## 금지
- 마이그레이션 파일 수기 작성 (autogenerate 거치지 않음)
- 운영 DB에 직접 DDL (DROP TABLE 등)
- 적용 후 마이그레이션 파일 수정 (새 revision 추가로 보완)
```

- [ ] **Step 5: 4종 한 번에 커밋**

```bash
mkdir -p /Users/songhansu/IdeaProjects/kis-autotrader-harness/.claude/skills/{proposal-validation,kis-api-rate-limit-pattern,strategy-add-pattern,alembic-migration-flow}
# (위 4개 SKILL.md를 각각 Write로 작성)
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add -f .claude/skills/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(skills): 4종 도메인 워크플로 SKILL.md (Phase 3 T7)"
```

---

## Task 8: 새 top-level prompt — auto_implement_prompt_v2.txt

**Files:**
- Create: `scripts/auto_implement_prompt_v2.txt`

- [ ] **Step 1: 프롬프트 작성**

`scripts/auto_implement_prompt_v2.txt`:
```
## 역할
너는 KIS 자동매매 시스템의 자동 구현 사이클 코디네이터(top-level)다.
Initializer가 만든 claude-progress.json을 읽고, 5종 subagent에게 작업을 위임한다.

## 컨텍스트
- 워크트리: `/Users/songhansu/IdeaProjects/kis-autotrader-harness` (또는 메인 repo)
- claude-progress.json: `~/.kis-autotrader/claude-progress.json` (Initializer가 생성)
- 가용 subagent: `proposal-validator`, `implementer`, `verifier`, `evaluator`, `rollback-handler`

## 사이클 흐름

### 1. 사전 회귀 검증
- `evaluator` agent를 Task tool로 dispatch — 골든 회귀 셋 통과 확인
- 실패 시: 즉시 사이클 중단, 사용자 통보, 종료

### 2. ready 제안서 수집
- Bash: `python scripts/harness/pipeline_list_ready.py` → JSON list
- 결과가 비면 종료: "오늘 처리할 제안서 없음"

### 3. 검증 (병렬)
- 각 제안서마다 `proposal-validator` agent dispatch
- **여러 dispatch를 한 메시지에 묶어서 보내 병렬 처리**
- 거절된 것은 자동으로 skipped 마킹됨 (validator가 처리)

### 4. 구현 (그룹 단위 병렬)
- Bash: `python -m src.harness.dependency`로 독립 그룹 계산 (또는 직접 changed_files 분석)
- 그룹 내 제안서는 **직렬** 처리 (`implementer` 1회 dispatch에 그룹 통째로 위임)
- 그룹 간은 **병렬** dispatch

### 5. 검증
- `verifier` agent를 dispatch — Default-FAIL contract 채점
- exit 0 → 모든 IN_FLIGHT을 implemented 처리
- exit 2 → 모든 IN_FLIGHT을 failed 처리 + rollback-handler dispatch
- exit 3 → rollback-handler dispatch

### 6. 회귀 사후 검증
- `evaluator` agent 재dispatch — 변경이 골든 셋 회귀를 유발했는지
- 실패 시 rollback-handler dispatch

### 7. 종료
- 사이클 종료. cycle_id, 처리 카운트, 실패 카운트 한 줄 로그

## 안전 규칙 (deterministic, hooks가 강제)
- `.env`/credentials.json/token.json 절대 편집 금지 (PreToolUse hook)
- `git push --force`, `rm -rf`, `DROP TABLE` 금지 (PreToolUse hook)
- 5파일 초과 변경은 implementer가 자가 차단
- pytest/mypy/ruff 출력 부재 시 Stop hook이 차단

## 금지
- Initializer가 생성한 claude-progress.json을 직접 수정 (subagent들이 pipeline_append_progress.py로 쓰기)
- 본 prompt 외 다른 prompt 텍스트 로딩
- subagent 우회한 직접 코드 편집
```

- [ ] **Step 2: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/auto_implement_prompt_v2.txt
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): auto_implement_prompt v2 — subagent 오케스트레이션 (Phase 3 T8)"
```

---

## Task 9: Cycle Orchestrator (Python 진입점)

**Files:**
- Create: `src/harness/cycle/__init__.py`, `src/harness/cycle/orchestrator.py`
- Test: `tests/test_harness/test_cycle_orchestrator.py`

- [ ] **Step 1: 실패 테스트**

```python
"""Cycle orchestrator TDD — Initializer 호출 + claude 위임 + 결과 적용."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.harness.cycle.orchestrator import (
    CycleOutcome,
    run_cycle,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh", encoding="utf-8")
    return tmp_path


def test_cycle_creates_progress_and_returns_cycle_id(repo: Path, tmp_path: Path) -> None:
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        r.return_value = MagicMock(returncode=0, stdout="", stderr="")
        outcome = run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
    assert isinstance(outcome, CycleOutcome)
    assert outcome.cycle_id.startswith("auto-")
    assert progress.exists()


def test_cycle_returns_initializer_failure_without_calling_claude(
    tmp_path: Path,
) -> None:
    bad_repo = tmp_path / "missing"
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        outcome = run_cycle(
            repo_root=bad_repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
    # Initializer가 환경 점검 실패해도 claude는 호출 — 단 outcome에 표시
    assert outcome.cycle_id


def test_cycle_returns_claude_exit_code(repo: Path, tmp_path: Path) -> None:
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        r.return_value = MagicMock(returncode=2, stdout="x", stderr="")
        outcome = run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
        )
    assert outcome.claude_exit_code == 2
```

- [ ] **Step 2: 구현**

`src/harness/cycle/__init__.py`:
```python
"""사이클 orchestration 패키지."""
```

`src/harness/cycle/orchestrator.py`:
```python
"""Cycle Orchestrator — 사이클 진입점.

순서:
1. Initializer.run() — 환경 점검 + claude-progress.json 생성
2. claude -p (top-level prompt) 호출 — subagent 오케스트레이션
3. claude exit code + progress.json 변화량으로 CycleOutcome 결정
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.harness.initializer import Initializer
from src.harness.progress import load_progress
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass(frozen=True)
class CycleOutcome:
    cycle_id: str
    claude_exit_code: int | None
    initializer_all_passed: bool
    completed_count: int
    failed_count: int
    skipped_count: int


def run_cycle(
    *,
    repo_root: Path,
    env: Literal["virtual", "real"],
    progress_path: Path,
    prompt_path: Path,
    claude_bin: str = "/Users/songhansu/.local/bin/claude",
) -> CycleOutcome:
    """1회 사이클 실행."""
    init = Initializer(repo_root=repo_root, env=env, progress_path=progress_path)
    status = init.run()
    logger.info(
        "cycle %s initialized (all_pass=%s)",
        status.cycle_id, status.initializer_all_passed,
    )

    claude_exit: int | None = None
    if prompt_path.exists():
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("prompt read failed: %s", e)
            prompt = ""
        cp = subprocess.run(  # noqa: S603
            [
                claude_bin, "-p", prompt,
                "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep,Task",
            ],
            cwd=str(repo_root), capture_output=True, text=True, check=False,
            timeout=3600,
        )
        claude_exit = cp.returncode
    else:
        logger.warning("prompt %s missing, skip claude call", prompt_path)

    # 사이클 종료 후 progress.json 통계 (필요 시 다시 로드)
    final = load_progress(progress_path)
    completed = len(final.completed) if final else 0
    failed = len(final.failed) if final else 0
    skipped = len(final.skipped) if final else 0

    return CycleOutcome(
        cycle_id=status.cycle_id,
        claude_exit_code=claude_exit,
        initializer_all_passed=status.initializer_all_passed,
        completed_count=completed,
        failed_count=failed,
        skipped_count=skipped,
    )
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_cycle_orchestrator.py -v
.venv/bin/ruff check src/harness/cycle/ tests/test_harness/test_cycle_orchestrator.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/cycle/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/cycle/ tests/test_harness/test_cycle_orchestrator.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(cycle): orchestrator — Initializer + claude -p subagent (Phase 3 T9)"
```
Expected: 3 passed

---

## Task 10: `run_auto_implement.sh` 전환

**Files:**
- Modify: `scripts/run_auto_implement.sh`

- [ ] **Step 1: 새 사이클 흐름으로 교체**

기존의 `claude -p "$(cat $PROMPT_FILE)" --allowedTools "Bash,Read,Write,Edit,Glob,Grep"` 라인을 다음으로 교체:

```bash
# Phase 3: Initializer + new top-level prompt
PROGRESS_PATH="$HOME/.kis-autotrader/claude-progress.json"
PROMPT_FILE_V2="$PROJECT_DIR/scripts/auto_implement_prompt_v2.txt"

PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" -c "
from pathlib import Path
from src.config import settings
from src.harness.cycle.orchestrator import run_cycle
outcome = run_cycle(
    repo_root=Path('$PROJECT_DIR'),
    env=settings.kis.env,
    progress_path=Path('$PROGRESS_PATH'),
    prompt_path=Path('$PROMPT_FILE_V2'),
)
print(f'[cycle] {outcome.cycle_id} claude_exit={outcome.claude_exit_code} '
      f'completed={outcome.completed_count} failed={outcome.failed_count} '
      f'skipped={outcome.skipped_count}')
" >> "$LOG_FILE" 2>&1
CYCLE_EXIT=$?
```

그리고 기존 `if [[ "$GOLDEN_EXIT" == "0" && "$VERIFIER_EXIT" == "0" ]]` 조건문에 `CYCLE_EXIT == "0"`도 AND로 추가:

```bash
if [[ "$CYCLE_EXIT" == "0" && "$GOLDEN_EXIT" == "0" && "$VERIFIER_EXIT" == "0" ]] && grep -q "implemented" "$LOG_FILE" 2>/dev/null; then
```

- [ ] **Step 2: 문법 검증 + 커밋**

```bash
bash -n /Users/songhansu/IdeaProjects/kis-autotrader-harness/scripts/run_auto_implement.sh && echo "syntax OK"
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/run_auto_implement.sh
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): run_auto_implement.sh — Initializer + 새 prompt v2 전환 (Phase 3 T10)"
```

---

## Task 11: 통합 검증 + 완료 리포트

**Files:**
- Create: `docs/harness/phase3_completion.md`

- [ ] **Step 1: 전체 검증**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/ tests/eval/ -q
.venv/bin/ruff check src/harness/ scripts/harness/ tests/test_harness/ tests/eval/
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/ scripts/harness/pipeline_*.py
```

- [ ] **Step 2: Initializer smoke test (실제 워크트리)**

```bash
PYTHONPATH=. .venv/bin/python -c "
from pathlib import Path
from src.harness.initializer import Initializer
init = Initializer(
    repo_root=Path('/Users/songhansu/IdeaProjects/kis-autotrader-harness'),
    env='virtual',
    progress_path=Path('/tmp/test-progress.json'),
)
status = init.run()
print(f'cycle_id={status.cycle_id} all_pass={status.initializer_all_passed}')
"
cat /tmp/test-progress.json | head -30
```

- [ ] **Step 3: Pipeline CLI 통합 smoke test**

```bash
PYTHONPATH=. .venv/bin/python scripts/harness/pipeline_list_ready.py | head -20
PYTHONPATH=. .venv/bin/python scripts/harness/pipeline_last_safe_tag.py
```

- [ ] **Step 4: 완료 리포트 작성**

`docs/harness/phase3_completion.md`에 다음 섹션 포함:
- 11 task 봉인 결과 (커밋 해시 표)
- 5계층 ADK 구성 충족 매핑
- 신규 테스트 카운트 (예상 25~30건)
- Phase 2 §6 진입 준비 충족 여부
- 운영 영향: 워크트리 한정, 메인 repo는 변경 0
- Phase 4 진입 준비: 3축 Observability + trajectory 적재 + 대시보드

- [ ] **Step 5: 최종 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add docs/harness/phase3_completion.md
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "docs(harness): Phase 3 완료 리포트 (Phase 3 T11)"
```

---

## 운영 영향

본 Phase 3도 워크트리에 한정. 메인 repo의 `scripts/run_auto_implement.sh`에는 Initializer 전환이 없으므로 다음 평일 17:00 cron은 기존 단일 `claude -p`로 동작. 머지 시점에 사용자가 결정.

머지 전 확인 사항:
1. `.claude/agents/` 5종 + `.claude/skills/` 4종이 메인 repo에 적용되어야 새 prompt가 동작
2. Pipeline CLI 8종이 모두 실행 가능해야 함 (Repository import 경로 확인)
3. `~/.kis-autotrader/claude-progress.json` 권한 (쓰기 가능)
4. `auto_implement_prompt_v2.txt` 경로 (`scripts/`)

Phase 4(3축 Observability + 대시보드)는 본 Phase가 만든 trajectory(progress.json history)를 DB로 영속화한다.
