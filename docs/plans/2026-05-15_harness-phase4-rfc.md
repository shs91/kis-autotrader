# 하네스 Phase 4 — 3축 Observability + 대시보드 + Telegram 결산 강화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1~3에서 만든 자동 구현 사이클의 trajectory를 **DB 자산화**하고, component·experience·decision 3축으로 분류 가능하게 만들고, 대시보드 + Telegram 결산을 통해 운영자가 한 눈에 사이클 KPI·재발 위험·예측 정확도를 볼 수 있게 한다.

**Architecture:** `trajectory_entries` 신규 테이블이 사이클 단계별 입력/결과/시간/토큰을 적재(experience). `implementation_logs.changed_files`의 각 항목에 component 분류 자동 추가(component). `proposals.prediction` JSONB 컬럼이 제안서의 정량 기대 효과를 적재하고 다음 주간 리포트가 실측 대비 정확도 계산(decision). 모든 적재는 Phase 3 Cycle Orchestrator/Verifier wiring에 통합. 대시보드 `pages/pipeline.py`와 Telegram 3섹션 카드가 이 데이터를 가시화.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 + Alembic, PostgreSQL JSONB, Streamlit(기존), pytest 9.0.2(+sqlite in-memory), ruff/mypy strict, 기존 `src.harness.*`(Phase 1~3) + `src.db.*` + `dashboard/`. 외부 의존 추가 없음.

---

## Spec → Task 매핑

harness plan(`docs/plans/2026-05-14_harness-engineering-improvement.md`) §5 Phase 4 + 축 C.

| 진단/스펙 | 산출물 | Task |
|----------|--------|------|
| D6 관측성: logfile + Telegram 평문에 머무름 | trajectory 테이블 + 대시보드 | T1~T4, T10 |
| 축 C Component Observability | changed_files에 component 자동 채움 | T5, T6 |
| 축 C Experience Observability | 사이클 단계별 trajectory 적재 | T1~T4 |
| 축 C Decision Observability | 제안서 prediction + 실측 calibration | T7, T8 |
| 동일 모듈 N회 수정/동일 사유 N회 실패 자동 집계 | `analytics.get_recurrence_risk()` | T9 |
| 대시보드 신규 페이지 | `dashboard/pages/pipeline.py` | T10 |
| Telegram 결산 3섹션 (적용/회귀 위험/예측 미달) | `formatter.format_pipeline_summary()` | T11 |
| Phase 3 §6 진입 준비 | T1·T4·T10·T11 모두 | — |

---

## File Structure

### Create

| 파일 | 책임 |
|------|------|
| `alembic/versions/<hash>_add_trajectory_entries_and_prediction.py` | trajectory 테이블 + proposals.prediction 컬럼 |
| `src/harness/observability/__init__.py` | 패키지 stub |
| `src/harness/observability/components.py` | 파일 경로 → component 분류 함수 |
| `src/harness/observability/trajectory.py` | trajectory 적재 헬퍼 (`append_entry(...)`) |
| `src/harness/observability/prediction.py` | 제안서 markdown의 "기대 효과" 섹션 파싱 |
| `dashboard/pages/pipeline.py` | Streamlit 페이지 — 사이클 KPI 가시화 |
| `tests/test_harness/test_observability_components.py` | T5 TDD |
| `tests/test_harness/test_observability_trajectory.py` | T3 TDD |
| `tests/test_harness/test_observability_prediction.py` | T7 TDD |
| `tests/test_db/test_trajectory_repository.py` | T2 TDD |
| `tests/test_analytics/__init__.py` | 패키지 stub |
| `tests/test_analytics/test_recurrence.py` | T9 TDD |
| `tests/test_analytics/test_calibration.py` | T8 TDD |
| `tests/test_notify/test_formatter_pipeline.py` | T11 TDD |

### Modify

| 파일 | 변경 |
|------|------|
| `src/db/models.py` | `TrajectoryEntry` 모델 추가 + `Proposal.prediction` JSONB 컬럼 |
| `src/db/repository.py` | `TrajectoryRepository` 신설 + `ProposalRepository.set_prediction()` 추가 |
| `src/db/analytics.py` | `get_recurrence_risk()`, `get_prediction_calibration()` 함수 추가 |
| `src/harness/cycle/orchestrator.py` | trajectory 적재 호출 추가 (initializer/claude/recorder 단계) |
| `src/harness/initializer.py` | 시작/종료 시 trajectory entry 적재 |
| `src/harness/verifier/cycle.py` | apply_verification_result에서 component 자동 채움 + trajectory entry |
| `src/notify/formatter.py` | `format_pipeline_summary()` 신규 — 3섹션 카드 |
| `scripts/harness/sync_proposals_md_to_db.py` | prediction 섹션 파싱 추가 |

---

## Task 1: Trajectory 테이블 모델 + Proposal.prediction 컬럼 + Alembic

**Files:**
- Modify: `src/db/models.py` (TrajectoryEntry 추가 + Proposal.prediction)
- Create: `alembic/versions/<hash>_add_trajectory_entries_and_prediction.py`

- [ ] **Step 1: 모델 추가**

`src/db/models.py`의 `class Proposal(Base)` 정의에 `prediction` 필드 추가:

```python
class Proposal(Base):
    # ... 기존 필드 ...
    prediction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ... 나머지 필드 ...
```

`class Proposal(Base)` 정의 직후에 `TrajectoryEntry` 모델 추가:

```python
class TrajectoryStep(enum.Enum):
    """사이클 trajectory 단계."""

    INITIALIZER = "initializer"
    VALIDATOR = "validator"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    EVALUATOR = "evaluator"
    RECORDER = "recorder"
    ROLLBACK = "rollback"


class TrajectoryStatus(enum.Enum):
    """trajectory entry 결과."""

    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class TrajectoryEntry(Base):
    """사이클 단계별 trajectory entry — Experience Observability."""

    __tablename__ = "trajectory_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step: Mapped[TrajectoryStep] = mapped_column(
        SAEnum(TrajectoryStep, name="trajectory_step_enum"),
        nullable=False, index=True,
    )
    proposal_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    agent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[TrajectoryStatus] = mapped_column(
        SAEnum(TrajectoryStatus, name="trajectory_status_enum"),
        nullable=False,
    )
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_usage_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TrajectoryEntry(cycle={self.cycle_id}, step={self.step.value}, "
            f"status={self.status.value})>"
        )
```

- [ ] **Step 2: import 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -c "
from src.db.models import TrajectoryEntry, TrajectoryStep, TrajectoryStatus, Proposal
print('OK')
print('Proposal.prediction:', Proposal.__table__.columns['prediction'].type)
"
```
Expected: `OK` + `Proposal.prediction: JSONB`

- [ ] **Step 3: Alembic 마이그레이션 생성**

```bash
PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "add_trajectory_entries_and_prediction"
```

생성된 파일 검토:
- `op.create_table('trajectory_entries', ...)` — 15 컬럼, 2 enum 신규
- `op.add_column('proposals', sa.Column('prediction', postgresql.JSONB, nullable=True))`
- `impl_category_enum` 재생성 시도 있으면 제거 (`create_type=False`)
- `op.create_index('ix_trajectory_entries_cycle_id', ...)`, `ix_step`, `ix_started_at`
- downgrade에 drop_table + add_column 역순 + enum drop 포함 (impl_category_enum 제외)

- [ ] **Step 4: 적용 + 검증**

```bash
PYTHONPATH=. .venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/python -c "
from sqlalchemy import inspect
from src.db.session import get_engine
ins = inspect(get_engine())
print('trajectory_entries:', len(ins.get_columns('trajectory_entries')), 'columns')
print('proposals cols:', [c['name'] for c in ins.get_columns('proposals')])
"
```
Expected: `trajectory_entries: 15 columns` + `proposals cols`에 `prediction` 포함

- [ ] **Step 5: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/db/models.py alembic/versions/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(db): trajectory_entries 테이블 + proposals.prediction 컬럼 (Phase 4 T1)"
```

---

## Task 2: TrajectoryRepository

**Files:**
- Modify: `src/db/repository.py` (TrajectoryRepository 추가)
- Test: `tests/test_db/test_trajectory_repository.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_db/test_trajectory_repository.py`:
```python
"""TrajectoryRepository TDD."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    TrajectoryStatus,
    TrajectoryStep,
)
from src.db.repository import TrajectoryRepository


@pytest.fixture
def session():
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def test_append_entry_persists(session) -> None:
    repo = TrajectoryRepository(session)
    now = datetime.now(UTC)
    entry = repo.append(
        cycle_id="c-1",
        step=TrajectoryStep.INITIALIZER,
        status=TrajectoryStatus.OK,
        started_at=now,
        completed_at=now,
        duration_seconds=0.5,
    )
    session.commit()
    assert entry.id is not None
    rows = repo.list_for_cycle("c-1")
    assert len(rows) == 1
    assert rows[0].step == TrajectoryStep.INITIALIZER


def test_list_for_cycle_filters_correctly(session) -> None:
    repo = TrajectoryRepository(session)
    now = datetime.now(UTC)
    repo.append(
        cycle_id="c-a", step=TrajectoryStep.IMPLEMENTER,
        status=TrajectoryStatus.OK, started_at=now, completed_at=now,
    )
    repo.append(
        cycle_id="c-b", step=TrajectoryStep.VERIFIER,
        status=TrajectoryStatus.FAIL, started_at=now, completed_at=now,
    )
    session.commit()
    assert len(repo.list_for_cycle("c-a")) == 1
    assert len(repo.list_for_cycle("c-b")) == 1
    assert repo.list_for_cycle("c-x") == []


def test_list_recent_returns_ordered(session) -> None:
    repo = TrajectoryRepository(session)
    base = datetime.now(UTC)
    for i in range(5):
        repo.append(
            cycle_id=f"c-{i}", step=TrajectoryStep.INITIALIZER,
            status=TrajectoryStatus.OK,
            started_at=base.replace(microsecond=i),
            completed_at=base.replace(microsecond=i),
        )
    session.commit()
    rows = repo.list_recent(limit=3)
    assert len(rows) == 3
    # 최신 순
    assert rows[0].cycle_id == "c-4"


def test_append_with_optional_metadata(session) -> None:
    repo = TrajectoryRepository(session)
    now = datetime.now(UTC)
    entry = repo.append(
        cycle_id="c-2", step=TrajectoryStep.IMPLEMENTER,
        status=TrajectoryStatus.OK, started_at=now, completed_at=now,
        proposal_path="docs/proposals/x.md",
        agent="implementer",
        input_summary="proposal x",
        result_summary="3 files edited",
        token_usage_input=1500, token_usage_output=400,
        meta={"changed_files": ["src/x.py"]},
    )
    session.commit()
    assert entry.agent == "implementer"
    assert entry.token_usage_input == 1500
    assert entry.meta["changed_files"] == ["src/x.py"]
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_db/test_trajectory_repository.py -v
```
Expected: `ImportError: cannot import name 'TrajectoryRepository'`

- [ ] **Step 3: 구현**

`src/db/repository.py` 파일 끝에 추가:

```python
from src.db.models import TrajectoryEntry, TrajectoryStatus, TrajectoryStep


class TrajectoryRepository:
    """사이클 trajectory entries 데이터 접근."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        cycle_id: str,
        step: TrajectoryStep,
        status: TrajectoryStatus,
        started_at: datetime,
        completed_at: datetime,
        proposal_path: str | None = None,
        agent: str | None = None,
        input_summary: str | None = None,
        result_summary: str | None = None,
        duration_seconds: float | None = None,
        token_usage_input: int | None = None,
        token_usage_output: int | None = None,
        meta: dict | None = None,
    ) -> TrajectoryEntry:
        """trajectory entry 한 건 추가."""
        if duration_seconds is None:
            duration_seconds = max(
                (completed_at - started_at).total_seconds(), 0.0,
            )
        entry = TrajectoryEntry(
            cycle_id=cycle_id,
            step=step,
            status=status,
            proposal_path=proposal_path,
            agent=agent,
            input_summary=input_summary,
            result_summary=result_summary,
            duration_seconds=duration_seconds,
            token_usage_input=token_usage_input,
            token_usage_output=token_usage_output,
            started_at=started_at,
            completed_at=completed_at,
            meta=meta,
            created_at=datetime.now(UTC),
        )
        self._session.add(entry)
        self._session.flush()
        logger.info(
            "trajectory entry: cycle=%s step=%s status=%s",
            cycle_id, step.value, status.value,
        )
        return entry

    def list_for_cycle(self, cycle_id: str) -> list[TrajectoryEntry]:
        stmt = (
            select(TrajectoryEntry)
            .where(TrajectoryEntry.cycle_id == cycle_id)
            .order_by(TrajectoryEntry.started_at)
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_recent(self, limit: int = 50) -> list[TrajectoryEntry]:
        stmt = (
            select(TrajectoryEntry)
            .order_by(TrajectoryEntry.started_at.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().all())
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_db/test_trajectory_repository.py -v
.venv/bin/ruff check src/db/repository.py tests/test_db/test_trajectory_repository.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/db/repository.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/db/repository.py tests/test_db/test_trajectory_repository.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(db): TrajectoryRepository + TDD 4건 (Phase 4 T2)"
```
Expected: 4 passed

---

## Task 3: Trajectory 적재 헬퍼

**Files:**
- Create: `src/harness/observability/__init__.py`, `src/harness/observability/trajectory.py`
- Test: `tests/test_harness/test_observability_trajectory.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_harness/test_observability_trajectory.py`:
```python
"""Trajectory 적재 헬퍼 TDD."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.db.models import TrajectoryStatus, TrajectoryStep
from src.harness.observability.trajectory import (
    append_entry,
    time_step,
)


def test_append_entry_uses_provided_repo() -> None:
    fake_repo = MagicMock()
    append_entry(
        repo=fake_repo,
        cycle_id="c-1",
        step=TrajectoryStep.INITIALIZER,
        status=TrajectoryStatus.OK,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    fake_repo.append.assert_called_once()
    kw = fake_repo.append.call_args.kwargs
    assert kw["cycle_id"] == "c-1"
    assert kw["step"] == TrajectoryStep.INITIALIZER


def test_time_step_context_manager_records_duration() -> None:
    fake_repo = MagicMock()
    with time_step(
        repo=fake_repo, cycle_id="c-2", step=TrajectoryStep.VERIFIER,
    ) as ctx:
        ctx.set_status(TrajectoryStatus.OK)
        ctx.set_result_summary("verified")
    fake_repo.append.assert_called_once()
    kw = fake_repo.append.call_args.kwargs
    assert kw["status"] == TrajectoryStatus.OK
    assert kw["result_summary"] == "verified"
    assert kw["duration_seconds"] >= 0.0


def test_time_step_exception_marks_fail() -> None:
    fake_repo = MagicMock()
    with pytest.raises(ValueError):
        with time_step(
            repo=fake_repo, cycle_id="c-3", step=TrajectoryStep.IMPLEMENTER,
        ) as ctx:
            ctx.set_status(TrajectoryStatus.OK)  # 무효화될 것
            raise ValueError("boom")
    fake_repo.append.assert_called_once()
    kw = fake_repo.append.call_args.kwargs
    assert kw["status"] == TrajectoryStatus.FAIL
    assert "boom" in (kw.get("result_summary") or "")
```

- [ ] **Step 2: 구현**

`src/harness/observability/__init__.py`:
```python
"""3축 Observability 도메인."""
```

`src/harness/observability/trajectory.py`:
```python
"""Trajectory 적재 헬퍼.

`append_entry`는 단발 호출용. `time_step`은 with-context로 시간 측정 + 예외 처리.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterator

from src.db.models import TrajectoryStatus, TrajectoryStep


def append_entry(
    *,
    repo: Any,
    cycle_id: str,
    step: TrajectoryStep,
    status: TrajectoryStatus,
    started_at: datetime,
    completed_at: datetime,
    proposal_path: str | None = None,
    agent: str | None = None,
    input_summary: str | None = None,
    result_summary: str | None = None,
    token_usage_input: int | None = None,
    token_usage_output: int | None = None,
    meta: dict[str, Any] | None = None,
) -> Any:
    """trajectory entry 1건을 repo.append로 위임."""
    return repo.append(
        cycle_id=cycle_id,
        step=step,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        proposal_path=proposal_path,
        agent=agent,
        input_summary=input_summary,
        result_summary=result_summary,
        token_usage_input=token_usage_input,
        token_usage_output=token_usage_output,
        meta=meta,
    )


@dataclass
class TimeStepContext:
    """time_step with-context의 부속 객체.

    호출자가 set_status/set_result_summary로 결과를 표시한다.
    """

    cycle_id: str
    step: TrajectoryStep
    started_at: datetime
    status: TrajectoryStatus = TrajectoryStatus.OK
    result_summary: str | None = None
    proposal_path: str | None = None
    agent: str | None = None

    def set_status(self, status: TrajectoryStatus) -> None:
        self.status = status

    def set_result_summary(self, summary: str) -> None:
        self.result_summary = summary

    def set_proposal_path(self, path: str) -> None:
        self.proposal_path = path

    def set_agent(self, agent: str) -> None:
        self.agent = agent


@contextmanager
def time_step(
    *,
    repo: Any,
    cycle_id: str,
    step: TrajectoryStep,
) -> Iterator[TimeStepContext]:
    """with-context로 trajectory entry 시간 측정.

    예외 발생 시 status=FAIL + 예외 메시지를 result_summary에 기록 후 re-raise.
    """
    started = datetime.now(UTC)
    perf_start = time.perf_counter()
    ctx = TimeStepContext(cycle_id=cycle_id, step=step, started_at=started)
    raised: BaseException | None = None
    try:
        yield ctx
    except BaseException as exc:
        ctx.status = TrajectoryStatus.FAIL
        ctx.result_summary = (
            (ctx.result_summary + " | " if ctx.result_summary else "")
            + f"exception: {exc!s:.200}"
        )
        raised = exc
    completed = datetime.now(UTC)
    duration = time.perf_counter() - perf_start
    repo.append(
        cycle_id=cycle_id,
        step=step,
        status=ctx.status,
        started_at=started,
        completed_at=completed,
        proposal_path=ctx.proposal_path,
        agent=ctx.agent,
        result_summary=ctx.result_summary,
        duration_seconds=duration,
    )
    if raised is not None:
        raise raised
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_observability_trajectory.py -v
.venv/bin/ruff check src/harness/observability/ tests/test_harness/test_observability_trajectory.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/observability/trajectory.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/observability/ tests/test_harness/test_observability_trajectory.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(observability): trajectory 적재 헬퍼 + TDD 3건 (Phase 4 T3)"
```
Expected: 3 passed

---

## Task 4: Cycle Orchestrator + Initializer trajectory wiring

**Files:**
- Modify: `src/harness/cycle/orchestrator.py`, `src/harness/initializer.py`

- [ ] **Step 1: Initializer에 trajectory 호출 추가**

`src/harness/initializer.py`의 `Initializer.__init__`에 optional `trajectory_repo` 파라미터 추가하고, `run()` 끝에 entry 적재:

```python
class Initializer:
    def __init__(
        self,
        repo_root: Path,
        env: Literal["virtual", "real"],
        progress_path: Path | None = None,
        disk_threshold_gb: float = _DEFAULT_DISK_THRESHOLD_GB,
        trajectory_repo: Any = None,  # 신규
    ) -> None:
        # ... 기존 ...
        self.trajectory_repo = trajectory_repo

    def run(self) -> InitializerStatus:
        started_at = datetime.now(_KST)
        cycle_id = "auto-" + started_at.strftime("%Y%m%d-%H%M%S")
        # ... 기존 점검 로직 ...
        completed_at = datetime.now(_KST)
        if self.trajectory_repo is not None:
            from src.db.models import TrajectoryStatus, TrajectoryStep
            self.trajectory_repo.append(
                cycle_id=cycle_id,
                step=TrajectoryStep.INITIALIZER,
                status=(
                    TrajectoryStatus.OK if all_passed
                    else TrajectoryStatus.FAIL
                ),
                started_at=started_at,
                completed_at=completed_at,
                result_summary=", ".join(
                    f"{c.name}={c.result.value}" for c in checks
                ),
            )
        return InitializerStatus(
            cycle_id=cycle_id,
            progress_path=self.progress_path,
            all_passed=all_passed,
        )
```

`Any` import 추가 필요 (`from typing import Any, Literal`).

- [ ] **Step 2: Cycle Orchestrator에 trajectory 적재 추가**

`src/harness/cycle/orchestrator.py`의 `run_cycle` 함수에 claude -p 단계 entry 적재:

```python
def run_cycle(
    *,
    repo_root: Path,
    env: Literal["virtual", "real"],
    progress_path: Path,
    prompt_path: Path,
    claude_bin: str = "/Users/songhansu/.local/bin/claude",
    trajectory_repo: Any = None,  # 신규
) -> CycleOutcome:
    init = Initializer(
        repo_root=repo_root, env=env, progress_path=progress_path,
        trajectory_repo=trajectory_repo,
    )
    status = init.run()
    # ... 기존 claude 호출 ...
    if trajectory_repo is not None and prompt_path.exists():
        from datetime import UTC, datetime as dt
        from src.db.models import TrajectoryStatus, TrajectoryStep
        # claude 호출 직전 시각 기록 + 호출 후 종료 시각 기록
        # (실제 호출 시각은 subprocess.run 라인 직전/직후로 옮길 것 — 본 step은 통합 자리만 표시)
        started = dt.now(UTC)
        cp = subprocess.run(  # noqa: S603
            [claude_bin, "-p", prompt, "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep,Task"],
            cwd=str(repo_root), capture_output=True, text=True, check=False,
            timeout=3600,
        )
        completed = dt.now(UTC)
        claude_exit = cp.returncode
        trajectory_repo.append(
            cycle_id=status.cycle_id,
            step=TrajectoryStep.IMPLEMENTER,
            status=TrajectoryStatus.OK if cp.returncode == 0 else TrajectoryStatus.FAIL,
            started_at=started, completed_at=completed,
            result_summary=f"claude exit={cp.returncode}",
            duration_seconds=(completed - started).total_seconds(),
        )
```

> **참고**: 위 `run_cycle` 변경은 기존 subprocess 호출 위치에 trajectory 호출 추가하는 형식. 기존 코드 흐름 유지하면서 entry만 끼워 넣는다.

- [ ] **Step 3: 회귀 + 새 호출 검증**

기존 T9의 `tests/test_harness/test_cycle_orchestrator.py`는 `trajectory_repo=None`로 기본 동작 유지. 새 테스트 1건 추가:

`tests/test_harness/test_cycle_orchestrator.py` 끝에 append:
```python
def test_cycle_records_trajectory_when_repo_provided(repo: Path, tmp_path: Path) -> None:
    fake_traj = MagicMock()
    progress = tmp_path / "p.json"
    with patch("src.harness.cycle.orchestrator.subprocess.run") as r:
        r.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_cycle(
            repo_root=repo, env="virtual", progress_path=progress,
            prompt_path=tmp_path / "prompt.txt", claude_bin="/bin/true",
            trajectory_repo=fake_traj,
        )
    # Initializer entry + (prompt 없으니 claude entry는 적재 안 됨)
    assert fake_traj.append.call_count >= 1
```

(`prompt.txt`가 존재하지 않으면 claude entry는 적재되지 않음 — initializer entry만 1건)

- [ ] **Step 4: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_cycle_orchestrator.py tests/test_harness/test_initializer.py -v
.venv/bin/ruff check src/harness/cycle/ src/harness/initializer.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/cycle/ src/harness/initializer.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/cycle/ src/harness/initializer.py tests/test_harness/test_cycle_orchestrator.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(cycle): Initializer + Orchestrator trajectory 적재 wiring (Phase 4 T4)"
```

---

## Task 5: Component metadata 분류기

**Files:**
- Create: `src/harness/observability/components.py`
- Test: `tests/test_harness/test_observability_components.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_harness/test_observability_components.py`:
```python
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
```

- [ ] **Step 2: 실패 확인 + 구현**

`src/harness/observability/components.py`:
```python
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
    normalized = path.lstrip("./")
    for pattern, label in _RULES:
        if pattern.search(normalized):
            return label
    return "other"
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_observability_components.py -v
.venv/bin/ruff check src/harness/observability/components.py tests/test_harness/test_observability_components.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/observability/components.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/observability/components.py tests/test_harness/test_observability_components.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(observability): component metadata 분류기 + TDD 31건 (Phase 4 T5)"
```
Expected: 31 passed (parametrized)

---

## Task 6: Verifier wiring 갱신 — changed_files에 component 자동 채움

**Files:**
- Modify: `src/harness/verifier/diff.py`, `src/harness/verifier/cycle.py`

- [ ] **Step 1: `DiffSummary.to_jsonb()`에 component 포함**

`src/harness/verifier/diff.py`의 `DiffSummary.to_jsonb()` 메소드를 다음으로 교체:

```python
    def to_jsonb(self) -> dict[str, Any]:
        from src.harness.observability.components import classify_component
        return {
            "files": [
                {
                    "path": f.path,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "component": classify_component(f.path),
                }
                for f in self.files
            ],
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "file_count": self.file_count,
        }
```

> **이유**: changed_files를 implementation_logs/verification JSONB에 적재할 때 자동으로 component가 포함됨. T5의 분류기를 시점에 호출.

- [ ] **Step 2: 기존 테스트(`tests/test_harness/test_verifier_diff.py`) 갱신**

`test_jsonb_serializable` 테스트의 expected를 갱신:
```python
def test_jsonb_serializable() -> None:
    raw = "10\t5\tsrc/strategy/rsi.py\n"
    diff = parse_numstat(raw)
    payload = diff.to_jsonb()
    assert payload == {
        "files": [{
            "path": "src/strategy/rsi.py",
            "additions": 10, "deletions": 5,
            "component": "code/strategy",
        }],
        "total_additions": 10,
        "total_deletions": 5,
        "file_count": 1,
    }
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_diff.py tests/test_harness/test_observability_components.py -v
.venv/bin/ruff check src/harness/verifier/diff.py tests/test_harness/test_verifier_diff.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/diff.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/diff.py tests/test_harness/test_verifier_diff.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): changed_files JSONB에 component 자동 분류 추가 (Phase 4 T6)"
```

---

## Task 7: Decision prediction — 제안서 파서 + Repository 메소드

**Files:**
- Create: `src/harness/observability/prediction.py`
- Modify: `src/db/repository.py` (`ProposalRepository.set_prediction()`), `scripts/harness/sync_proposals_md_to_db.py` (prediction 파싱)
- Test: `tests/test_harness/test_observability_prediction.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_harness/test_observability_prediction.py`:
```python
"""제안서 prediction 파싱 TDD."""

from __future__ import annotations

from pathlib import Path

from src.harness.observability.prediction import parse_prediction


def test_parse_full_prediction_block(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    f.write_text(
        "# 제목\n\n## 기대 효과\n"
        "- win_rate_delta_pp: +2.0\n"
        "- error_count_delta_ratio: -0.30\n"
        "- signal_count_delta: +50\n\n"
        "## 본문\n…",
        encoding="utf-8",
    )
    pred = parse_prediction(f)
    assert pred == {
        "win_rate_delta_pp": 2.0,
        "error_count_delta_ratio": -0.30,
        "signal_count_delta": 50.0,
    }


def test_parse_missing_section_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "y.md"
    f.write_text("# 제목\n\n## 메타데이터\n- 상태: ready\n", encoding="utf-8")
    assert parse_prediction(f) == {}


def test_parse_ignores_non_numeric_lines(tmp_path: Path) -> None:
    f = tmp_path / "z.md"
    f.write_text(
        "# X\n\n## 기대 효과\n"
        "- win_rate_delta_pp: +1.5\n"
        "- 안정성 개선 (정성)\n"
        "- error_count_delta_ratio: not measured\n",
        encoding="utf-8",
    )
    pred = parse_prediction(f)
    assert pred == {"win_rate_delta_pp": 1.5}
```

- [ ] **Step 2: 구현**

`src/harness/observability/prediction.py`:
```python
"""제안서 markdown의 '## 기대 효과' 섹션 → JSONB prediction.

키 형식 (BRIDGE_SPEC v3 도입 예정):
- win_rate_delta_pp: float (퍼센트 포인트)
- error_count_delta_ratio: float (비율, -0.3 = 30% 감소)
- signal_count_delta: float (개수, 절대값)
- 등 자유 형식 key: value (float 변환 가능한 라인만 적재)
"""

from __future__ import annotations

import re
from pathlib import Path

_LINE_RE = re.compile(
    r"^-\s*(?P<key>[a-z_][a-z0-9_]*)\s*:\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*$"
)


def parse_prediction(path: Path) -> dict[str, float]:
    """`## 기대 효과` 섹션에서 정량 key:value 라인을 추출."""
    in_section = False
    result: dict[str, float] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for raw in lines:
        line = raw.strip()
        if line.startswith("## 기대 효과") or line.startswith("## 예상 효과"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            m = _LINE_RE.match(line)
            if m:
                try:
                    result[m.group("key")] = float(m.group("value"))
                except ValueError:
                    continue
    return result
```

- [ ] **Step 3: ProposalRepository.set_prediction**

`src/db/repository.py`의 `ProposalRepository`에 추가:
```python
    def set_prediction(self, proposal_id: int, prediction: dict) -> None:
        """제안서의 prediction JSONB를 갱신."""
        p = self._require(proposal_id)
        now = datetime.now(UTC)
        p.prediction = prediction or None
        p.updated_at = now
        logger.info("제안서 prediction 갱신: %s — %d keys", p.path, len(prediction or {}))
```

- [ ] **Step 4: sync_proposals_md_to_db.py에 prediction 적재**

`scripts/harness/sync_proposals_md_to_db.py`의 `sync_directory`에서 `repo.create(...)` 직후에 prediction 적재:

```python
from src.harness.observability.prediction import parse_prediction

# ...

for md in sorted(directory.glob("*.md")):
    # ... 기존 코드 ...
    proposal = repo.create(...)
    pred = parse_prediction(md)
    if pred:
        repo.set_prediction(proposal.id, pred)
    inserted += 1
```

- [ ] **Step 5: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_observability_prediction.py tests/test_harness/test_sync_md_to_db.py -v
.venv/bin/ruff check src/harness/observability/prediction.py src/db/repository.py scripts/harness/sync_proposals_md_to_db.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/observability/prediction.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/observability/prediction.py src/db/repository.py scripts/harness/sync_proposals_md_to_db.py tests/test_harness/test_observability_prediction.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(observability): 제안서 prediction 파싱 + Repository.set_prediction + sync 적재 (Phase 4 T7)"
```

---

## Task 8: Prediction calibration 분석

**Files:**
- Modify: `src/db/analytics.py` (append `get_prediction_calibration`)
- Test: `tests/test_analytics/__init__.py`, `tests/test_analytics/test_calibration.py`

- [ ] **Step 1: 패키지 stub + 실패 테스트**

`tests/test_analytics/__init__.py`:
```python
"""analytics 패키지 테스트."""
```

`tests/test_analytics/test_calibration.py`:
```python
"""Prediction calibration TDD."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.analytics import get_prediction_calibration
from src.db.models import (
    Base,
    ImplementationCategory,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository


@pytest.fixture
def session():
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def test_calibration_empty(session) -> None:
    result = get_prediction_calibration(session, window_days=30)
    assert result["proposal_count"] == 0
    assert result["categories"] == {}


def test_calibration_with_predictions(session) -> None:
    repo = ProposalRepository(session)
    p1 = repo.create(
        path="a.md", title="A", category=ImplementationCategory.PARAM_TUNING,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
    repo.set_prediction(p1.id, {"win_rate_delta_pp": 2.0})
    p2 = repo.create(
        path="b.md", title="B", category=ImplementationCategory.PARAM_TUNING,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
    repo.set_prediction(p2.id, {"win_rate_delta_pp": 1.0, "error_count_delta_ratio": -0.2})
    p3 = repo.create(
        path="c.md", title="C", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
    # no prediction for p3
    session.commit()

    result = get_prediction_calibration(session, window_days=30)
    assert result["proposal_count"] == 3
    assert result["with_prediction_count"] == 2
    # 카테고리별 평균 키
    cats = result["categories"]
    assert "param_tuning" in cats
    assert "win_rate_delta_pp" in cats["param_tuning"]
    # 평균 (2.0 + 1.0) / 2
    assert abs(cats["param_tuning"]["win_rate_delta_pp"]["avg_predicted"] - 1.5) < 0.001
```

- [ ] **Step 2: 구현 (analytics.py 끝에 추가)**

`src/db/analytics.py` 끝에 추가:
```python
def get_prediction_calibration(
    session: Session,
    window_days: int = 30,
) -> dict[str, Any]:
    """제안서의 prediction과 실측을 카테고리별로 집계한다.

    Phase 4 Decision Observability. 실측 비교는 후속 Phase 5(리포트 사이클)에서
    win_rate 등을 매핑해 채운다. 본 함수는 prediction 분포만 우선 노출.
    """
    from datetime import UTC as _UTC
    since = datetime.now(_UTC) - timedelta(days=window_days)
    stmt = select(Proposal).where(Proposal.created_at >= since)
    rows = list(session.execute(stmt).scalars().all())
    categories: dict[str, dict[str, dict[str, Any]]] = {}
    with_pred = 0
    for p in rows:
        if not p.prediction:
            continue
        with_pred += 1
        cat_key = p.category.value
        cat_bucket = categories.setdefault(cat_key, {})
        for k, v in p.prediction.items():
            metric = cat_bucket.setdefault(
                k, {"count": 0, "sum_predicted": 0.0, "avg_predicted": 0.0},
            )
            metric["count"] += 1
            metric["sum_predicted"] += float(v)
            metric["avg_predicted"] = metric["sum_predicted"] / metric["count"]
    return {
        "window_days": window_days,
        "proposal_count": len(rows),
        "with_prediction_count": with_pred,
        "categories": categories,
    }
```

> **import 추가**: `from src.db.models import Proposal`가 없으면 추가.

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_analytics/test_calibration.py -v
.venv/bin/ruff check src/db/analytics.py tests/test_analytics/
PYTHONPATH=. .venv/bin/python -m mypy --strict tests/test_analytics/test_calibration.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/db/analytics.py tests/test_analytics/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(analytics): get_prediction_calibration + TDD 2건 (Phase 4 T8)"
```

---

## Task 9: 재발 위험 집계

**Files:**
- Modify: `src/db/analytics.py` (append `get_recurrence_risk`)
- Test: `tests/test_analytics/test_recurrence.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_analytics/test_recurrence.py`:
```python
"""재발 위험 집계 TDD — 같은 component를 7일 내 N회 수정한 케이스."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.analytics import get_recurrence_risk
from src.db.models import Base, ImplementationCategory, ImplementationLog


@pytest.fixture
def session():
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _log(session, days_ago: int, paths: list[str]) -> None:
    log = ImplementationLog(
        title=f"log {days_ago}d",
        category=ImplementationCategory.BUG_FIX,
        implemented_at=datetime.now(UTC) - timedelta(days=days_ago),
        created_at=datetime.now(UTC),
        changed_files={
            "files": [{"path": p, "component": "code/strategy",
                       "additions": 1, "deletions": 0} for p in paths],
            "file_count": len(paths),
        },
    )
    session.add(log)


def test_no_recurrence(session) -> None:
    _log(session, days_ago=0, paths=["src/strategy/rsi.py"])
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=2)
    assert result["risk_components"] == []
    assert result["risk_files"] == []


def test_detects_3_edits_in_window(session) -> None:
    for d in (0, 2, 5):
        _log(session, days_ago=d, paths=["src/strategy/rsi.py"])
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=3)
    files = {r["path"]: r for r in result["risk_files"]}
    assert "src/strategy/rsi.py" in files
    assert files["src/strategy/rsi.py"]["edit_count"] == 3


def test_groups_by_component(session) -> None:
    _log(session, days_ago=0, paths=["src/strategy/rsi.py"])
    _log(session, days_ago=2, paths=["src/strategy/macd.py"])
    _log(session, days_ago=5, paths=["src/strategy/ensemble.py"])
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=3)
    comps = {r["component"]: r for r in result["risk_components"]}
    assert comps["code/strategy"]["edit_count"] == 3


def test_excludes_outside_window(session) -> None:
    _log(session, days_ago=0, paths=["src/x.py"])
    _log(session, days_ago=10, paths=["src/x.py"])  # 윈도우 밖
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=2)
    assert result["risk_files"] == []
```

- [ ] **Step 2: 구현 (analytics.py 끝에 추가)**

```python
def get_recurrence_risk(
    session: Session,
    window_days: int = 7,
    min_edits: int = 3,
) -> dict[str, Any]:
    """동일 component/파일을 윈도우 내 min_edits회 이상 수정한 케이스 집계.

    재발 위험 신호 — 같은 모듈을 단기에 반복 수정한다는 것은 일회성 fix가
    부족했음을 의미. Telegram 결산과 대시보드에 노출.
    """
    from datetime import UTC as _UTC
    since = datetime.now(_UTC) - timedelta(days=window_days)
    stmt = (
        select(ImplementationLog)
        .where(ImplementationLog.implemented_at >= since)
        .order_by(ImplementationLog.implemented_at)
    )
    logs = list(session.execute(stmt).scalars().all())

    file_counts: dict[str, int] = {}
    comp_counts: dict[str, int] = {}
    for log in logs:
        if not log.changed_files:
            continue
        files = (
            log.changed_files.get("files")
            if isinstance(log.changed_files, dict)
            else None
        )
        if not files:
            continue
        seen_in_log_files: set[str] = set()
        seen_in_log_comps: set[str] = set()
        for f in files:
            if not isinstance(f, dict):
                continue
            path = f.get("path", "")
            comp = f.get("component", "other")
            if path and path not in seen_in_log_files:
                file_counts[path] = file_counts.get(path, 0) + 1
                seen_in_log_files.add(path)
            if comp and comp not in seen_in_log_comps:
                comp_counts[comp] = comp_counts.get(comp, 0) + 1
                seen_in_log_comps.add(comp)

    risk_files = sorted(
        (
            {"path": p, "edit_count": c}
            for p, c in file_counts.items()
            if c >= min_edits
        ),
        key=lambda x: -x["edit_count"],
    )
    risk_components = sorted(
        (
            {"component": comp, "edit_count": c}
            for comp, c in comp_counts.items()
            if c >= min_edits
        ),
        key=lambda x: -x["edit_count"],
    )
    return {
        "window_days": window_days,
        "min_edits": min_edits,
        "risk_files": risk_files,
        "risk_components": risk_components,
    }
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_analytics/test_recurrence.py -v
.venv/bin/ruff check src/db/analytics.py tests/test_analytics/test_recurrence.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/db/analytics.py tests/test_analytics/test_recurrence.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(analytics): get_recurrence_risk + TDD 4건 (Phase 4 T9)"
```

---

## Task 10: 대시보드 `pages/pipeline.py`

**Files:**
- Create: `dashboard/pages/pipeline.py`

- [ ] **Step 1: Streamlit 페이지 작성**

`dashboard/pages/pipeline.py`:
```python
"""하네스 사이클 KPI 대시보드 페이지 — Phase 4."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from src.db.analytics import (
    get_prediction_calibration,
    get_recurrence_risk,
)
from src.db.models import (
    ImplementationLog,
    Proposal,
    ProposalState,
    TrajectoryEntry,
    TrajectoryStatus,
)
from src.db.session import get_session


st.set_page_config(page_title="Pipeline KPI", layout="wide")
st.title("🛠 하네스 사이클 KPI")

with get_session() as session:
    # ── Section 1: 사이클 성공률 (30일)
    since_30d = datetime.now(UTC) - timedelta(days=30)
    impl_count = session.execute(
        select(func.count(ImplementationLog.id)).where(
            ImplementationLog.implemented_at >= since_30d
        )
    ).scalar() or 0
    failed_count = session.execute(
        select(func.count(Proposal.id)).where(
            Proposal.state == ProposalState.FAILED,
            Proposal.last_attempt_at >= since_30d,
        )
    ).scalar() or 0
    skipped_count = session.execute(
        select(func.count(Proposal.id)).where(
            Proposal.state == ProposalState.SKIPPED,
            Proposal.last_attempt_at >= since_30d,
        )
    ).scalar() or 0
    denom = impl_count + failed_count + skipped_count
    success_rate = (impl_count / denom * 100) if denom else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("30일 성공률", f"{success_rate:.1f}%")
    col2.metric("적용 건수", impl_count)
    col3.metric("실패/스킵", f"{failed_count} / {skipped_count}")

    # ── Section 2: MTTR (mean time to revert) — trajectory 기반
    st.subheader("MTTR (mean time to revert)")
    rollback_rows = list(session.execute(
        select(TrajectoryEntry).where(
            TrajectoryEntry.step.in_(["rollback"]),
            TrajectoryEntry.started_at >= since_30d,
        )
    ).scalars().all())
    if rollback_rows:
        avg_seconds = sum(r.duration_seconds or 0 for r in rollback_rows) / len(rollback_rows)
        st.write(f"평균 {avg_seconds:.0f}초, 총 {len(rollback_rows)}회")
    else:
        st.info("30일 내 rollback 이벤트 없음")

    # ── Section 3: Top failure reasons
    st.subheader("Top failure reasons (30일)")
    fail_rows = list(session.execute(
        select(Proposal.failure_reason, func.count(Proposal.id))
        .where(Proposal.state == ProposalState.FAILED,
               Proposal.last_attempt_at >= since_30d)
        .group_by(Proposal.failure_reason)
        .order_by(func.count(Proposal.id).desc())
        .limit(10)
    ).all())
    if fail_rows:
        df_fail = pd.DataFrame(fail_rows, columns=["reason", "count"])
        st.dataframe(df_fail, hide_index=True)
    else:
        st.info("실패 이력 없음")

    # ── Section 4: Component edit heatmap (재발 위험)
    st.subheader("Component edit heatmap (7일 / 재발 위험 ≥ 3회)")
    recur = get_recurrence_risk(session, window_days=7, min_edits=3)
    if recur["risk_components"]:
        st.dataframe(pd.DataFrame(recur["risk_components"]), hide_index=True)
    else:
        st.info("재발 위험 component 없음")
    if recur["risk_files"]:
        st.write("**파일 단위 재발**")
        st.dataframe(pd.DataFrame(recur["risk_files"]), hide_index=True)

    # ── Section 5: Prediction calibration (현재 prediction 분포만)
    st.subheader("Prediction calibration (30일)")
    cal = get_prediction_calibration(session, window_days=30)
    st.write(
        f"제안서 {cal['proposal_count']}건 중 "
        f"{cal['with_prediction_count']}건이 prediction 보유"
    )
    if cal["categories"]:
        cal_rows = []
        for category, metrics in cal["categories"].items():
            for metric_name, stats in metrics.items():
                cal_rows.append({
                    "category": category,
                    "metric": metric_name,
                    "count": stats["count"],
                    "avg_predicted": round(stats["avg_predicted"], 3),
                })
        st.dataframe(pd.DataFrame(cal_rows), hide_index=True)
    else:
        st.info("prediction 데이터 없음 (제안서 ## 기대 효과 섹션 미작성)")
```

- [ ] **Step 2: import 확인 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -c "import dashboard.pages.pipeline; print('OK')" 2>&1 | tail -3
.venv/bin/ruff check dashboard/pages/pipeline.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add dashboard/pages/pipeline.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(dashboard): pipeline KPI 페이지 — 성공률/MTTR/failure/재발/calibration (Phase 4 T10)"
```

> **참고**: Streamlit 페이지는 import 시점에 `st.set_page_config` 호출하므로 단순 import는 부작용이 있을 수 있음. 단순 ruff 검증으로 충분.

---

## Task 11: Telegram 결산 3섹션 카드

**Files:**
- Modify: `src/notify/formatter.py` (append `format_pipeline_summary`)
- Test: `tests/test_notify/test_formatter_pipeline.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_notify/test_formatter_pipeline.py`:
```python
"""Telegram 사이클 결산 3섹션 카드 TDD."""

from __future__ import annotations

from src.notify.formatter import format_pipeline_summary


def test_format_with_all_sections() -> None:
    msg = format_pipeline_summary(
        cycle_id="auto-20260515-170000",
        applied=[{"title": "스크리닝 임계값 조정", "version": "0.2.5"}],
        recurrence_risks=[{"component": "code/strategy", "edit_count": 4}],
        prediction_misses=[{"category": "param_tuning", "metric": "win_rate_delta_pp"}],
    )
    assert "auto-20260515-170000" in msg
    assert "오늘 적용" in msg
    assert "스크리닝 임계값" in msg
    assert "회귀 위험" in msg
    assert "code/strategy" in msg
    assert "예측 미달" in msg


def test_format_with_empty_sections_shows_no_data() -> None:
    msg = format_pipeline_summary(
        cycle_id="c-x",
        applied=[],
        recurrence_risks=[],
        prediction_misses=[],
    )
    assert "변경 없음" in msg
    assert "회귀 위험 없음" in msg
    assert "예측 미달 없음" in msg


def test_truncates_long_lists() -> None:
    applied = [{"title": f"T{i}", "version": "0.0.0"} for i in range(20)]
    msg = format_pipeline_summary(
        cycle_id="c-y", applied=applied,
        recurrence_risks=[], prediction_misses=[],
    )
    # 상위 N개만 노출
    assert msg.count("T0") == 1
    # 너무 길어지지 않도록 절단 표시
    assert "외 " in msg or "and " in msg or "..." in msg
```

- [ ] **Step 2: 구현 (formatter.py 끝에 추가)**

`src/notify/formatter.py` 끝에 추가:
```python
_MAX_APPLIED = 5
_MAX_RECURRENCE = 5
_MAX_PREDICTION = 5


def format_pipeline_summary(
    *,
    cycle_id: str,
    applied: list[dict[str, Any]],
    recurrence_risks: list[dict[str, Any]],
    prediction_misses: list[dict[str, Any]],
) -> str:
    """사이클 종료 후 3섹션 결산 카드 — Phase 4."""
    lines = [f"🛠 <b>하네스 사이클 결산</b> ({cycle_id})", ""]

    # 1. 오늘 적용
    lines.append("<b>📦 오늘 적용된 변경</b>")
    if not applied:
        lines.append("  변경 없음")
    else:
        for entry in applied[:_MAX_APPLIED]:
            title = entry.get("title", "(no title)")
            version = entry.get("version") or "-"
            lines.append(f"  • <code>{version}</code> {title}")
        if len(applied) > _MAX_APPLIED:
            lines.append(f"  외 {len(applied) - _MAX_APPLIED}건")
    lines.append("")

    # 2. 회귀 위험
    lines.append("<b>⚠️ 회귀 위험 (7일)</b>")
    if not recurrence_risks:
        lines.append("  회귀 위험 없음")
    else:
        for r in recurrence_risks[:_MAX_RECURRENCE]:
            comp = r.get("component") or r.get("path", "?")
            count = r.get("edit_count", 0)
            lines.append(f"  • {comp} — {count}회")
        if len(recurrence_risks) > _MAX_RECURRENCE:
            lines.append(f"  외 {len(recurrence_risks) - _MAX_RECURRENCE}건")
    lines.append("")

    # 3. 예측 미달
    lines.append("<b>📉 예측 미달 (지난주 대비)</b>")
    if not prediction_misses:
        lines.append("  예측 미달 없음")
    else:
        for m in prediction_misses[:_MAX_PREDICTION]:
            cat = m.get("category", "?")
            metric = m.get("metric", "?")
            lines.append(f"  • {cat} / {metric}")
        if len(prediction_misses) > _MAX_PREDICTION:
            lines.append(f"  외 {len(prediction_misses) - _MAX_PREDICTION}건")

    return "\n".join(lines)
```

> `Any` import 확인: formatter.py 상단에 `from typing import Any` 있는지 점검.

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_notify/test_formatter_pipeline.py -v
.venv/bin/ruff check src/notify/formatter.py tests/test_notify/test_formatter_pipeline.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/notify/formatter.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/notify/formatter.py tests/test_notify/test_formatter_pipeline.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(notify): format_pipeline_summary 3섹션 카드 + TDD 3건 (Phase 4 T11)"
```

---

## Task 12: 통합 검증 + 완료 리포트

**Files:**
- Create: `docs/harness/phase4_completion.md`

- [ ] **Step 1: 전체 검증**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/ tests/eval/ tests/test_analytics/ tests/test_notify/ tests/test_db/test_proposals_repository.py tests/test_db/test_trajectory_repository.py -q
.venv/bin/ruff check src/harness/observability/ src/db/repository.py src/db/analytics.py dashboard/pages/pipeline.py src/notify/formatter.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/observability/ src/db/repository.py
```
Expected: 신규 테스트 약 50건 추가, 누적 170+ passed

- [ ] **Step 2: 대시보드 페이지 manual smoke (선택)**

```bash
# Streamlit 서버를 잠시 띄워 페이지 동작 확인 (선택)
.venv/bin/streamlit run dashboard/app.py --server.port 18923 --server.headless true &
sleep 5
curl -s http://localhost:18923 > /dev/null && echo "dashboard up"
kill %1 2>/dev/null || true
```

- [ ] **Step 3: 완료 리포트 작성**

`docs/harness/phase4_completion.md`에 다음 섹션 포함:
- 12 task 봉인 결과 (커밋 해시 표)
- 3축 Observability 충족 매핑 (Component/Experience/Decision)
- 진단 D6 해결 + Phase 3 §6 진입 준비 충족 여부
- 신규 테스트 카운트 (예상 50건)
- 운영 영향: 워크트리 한정, 머지 시 마이그레이션 + 대시보드 페이지 활성화
- Phase 5 진입 준비 (4 cadence 리포트 파이프라인의 하네스화)

- [ ] **Step 4: 최종 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add docs/harness/phase4_completion.md
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "docs(harness): Phase 4 완료 리포트 (Phase 4 T12)"
```

---

## 운영 영향 / 머지 시 주의

본 Phase 4도 워크트리에 한정. 핵심 영향:

### 4.1 시스템 영향 (현재 = 워크트리 한정)

- `trajectory_entries` 테이블: 운영 DB에 신규 추가됨 (Alembic 적용 시점). autotrader는 사용 안 함 → 운영 영향 0
- `proposals.prediction` 컬럼: nullable이라 기존 행에 영향 없음
- `dashboard/pages/pipeline.py`: 메인 repo 대시보드도 동일 모델·analytics 사용하면 그대로 동작
- `format_pipeline_summary`: 사이클 종료 후 Telegram 전송 wiring은 Phase 5에서 (cycle orchestrator가 호출하도록)

### 4.2 머지 시 결정 사항

1. **마이그레이션 적용 타이밍**: 머지 PR 머지 후 `alembic upgrade head` 호출 (운영 DB). autotrader 영향 없음
2. **대시보드 페이지 활성화**: 머지 후 `streamlit run dashboard/app.py` 자동 재시작 (com.kis.dashboard) — `launchctl stop com.kis.dashboard && launchctl start com.kis.dashboard`
3. **prediction 적재 backfill**: 기존 37건 제안서 markdown에 `## 기대 효과` 섹션이 있으면 sync_proposals_md_to_db.py 재실행으로 backfill
4. **Telegram 카드 활성화**: Phase 5에서 사이클 종료 시 자동 발송 wiring 예정 (본 Phase는 포매터만)

### 4.3 운영 상태 (현재)

서비스 정상 (Phase 2/3 완료 시 재로드 확인): `com.kis.autotrader` PID 81079, dashboard PID 785, 그 외 스케줄 대기.

Phase 5는 본 Phase가 만든 trajectory + prediction + recurrence 데이터를 4-cadence(일/주/월/분기) 리포트 파이프라인에 통합한다.
