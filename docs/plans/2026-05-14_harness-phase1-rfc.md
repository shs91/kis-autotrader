# 하네스 Phase 1 — 안전 게이트 코드화 + 수동 트리거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자동 구현 파이프라인의 안전 규칙을 BRIDGE_SPEC 자연어에서 결정적 코드로 옮기고, `proposals` 테이블을 상태 머신의 sole source of truth로 만들고, 운영자가 표준 채널로 사이클을 발동/중단할 수 있게 한다.

**Architecture:** 4개 산출물 — (a) `.claude/settings.json` Hook(테스트 가능한 Python 로직 + 얇은 wrapper) (b) `proposals` 테이블(Alembic 마이그레이션 + Repository) (c) 수동 트리거(CLI 스크립트 + Telegram 3개 명령) (d) `claude-progress.json` v1 스키마. 데이터 계층(b) → Initializer(d) → 안전 게이트(a) → 트리거(c) 순으로 쌓는다.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, pydantic 2.5+, httpx, pytest(+sqlite in-memory), ruff/mypy strict.

---

## Spec → Task 매핑

| 진단 (계획서 §3) | 해결 산출물 | 본 plan의 Task |
|------------------|------------|-----------------|
| D3 안전 게이트가 자연어 텍스트 | (a) Hooks | T6 ~ T8 |
| D4 제안서 상태 머신이 markdown 의존 | (b) `proposals` 테이블 | T1 ~ T4 |
| D5 실패 복구 자동화 부재 | last_safe_tag + `claude-progress.json` | T5 |
| D7 골든 회귀 셋 부재 사전 차단 | DTZ hook(Phase 0과 연결) | T7 |
| D10 트리거가 cron 단일 채널 | (c) CLI + Telegram | T9 ~ T12 |

본 plan은 **Phase 1 게이트** (`docs/harness/phase0_baseline.md` §4) 5종을 모두 충족한다.

---

## File Structure

### Create

| 파일 | 책임 |
|------|------|
| `alembic/versions/<hash>_add_proposals_table.py` | proposals 테이블 + state/priority enum 생성 |
| `scripts/harness/sync_proposals_md_to_db.py` | 기존 37건 markdown → proposals INSERT |
| `src/harness/__init__.py` | 하네스 도메인 패키지 |
| `src/harness/progress.py` | `claude-progress.json` 스키마 (pydantic) + load/save 헬퍼 |
| `src/harness/hooks/__init__.py` | 패키지 stub |
| `src/harness/hooks/pre_tool_use.py` | Edit/Write 금지 경로 차단 로직 |
| `src/harness/hooks/pre_bash.py` | 위험 bash 패턴 차단 로직 |
| `src/harness/hooks/post_edit.py` | ruff --fix + DTZ 검사 트리거 |
| `src/harness/hooks/stop.py` | Verifier 단계 강제 (검증 출력 부재 시 차단) |
| `src/harness/telegram_commands.py` | `/run_implement`, `/status_implement`, `/pause_implement` 핸들러 |
| `src/harness/trigger.py` | 수동 트리거 동시성/인터벌/장중 가드 (CLI·Telegram 공유) |
| `scripts/claude-hooks/run_hook.py` | Claude Code hook 진입점 (stdin JSON → src.harness.hooks 라우팅) |
| `scripts/trigger_implement.sh` | CLI 트리거 (src.harness.trigger 호출) |
| `.claude/settings.json` | Hook 등록 (PreToolUse/PostToolUse/Stop) |
| `tests/test_db/test_proposals_repository.py` | Repository TDD |
| `tests/test_harness/__init__.py` | 패키지 stub |
| `tests/test_harness/test_progress.py` | progress.json 스키마 TDD |
| `tests/test_harness/test_hooks_pre_tool_use.py` | Edit/Write 차단 룰 TDD |
| `tests/test_harness/test_hooks_pre_bash.py` | bash 차단 룰 TDD |
| `tests/test_harness/test_hooks_post_edit.py` | post-edit 동작 TDD |
| `tests/test_harness/test_hooks_stop.py` | Verifier 강제 TDD |
| `tests/test_harness/test_trigger.py` | 트리거 가드 TDD |
| `tests/test_notify/test_harness_commands.py` | Telegram 핸들러 TDD |

### Modify

| 파일 | 변경 내용 |
|------|----------|
| `src/db/models.py` | `ProposalState` enum + `Proposal` 클래스 추가 (Line 405 뒤) |
| `src/db/repository.py` | `ProposalRepository` 추가 (파일 끝) |
| `src/config.py` | `HarnessSettings` 추가 (min_cycle_interval, pause_lock_path) |
| `main.py` | Telegram 3개 명령 등록 (`bot.register("run_implement", ...)` 외 2건) |
| `scripts/run_auto_implement.sh` | `pause-lock` 파일 존재 시 즉시 종료 + 시작 전 cycle_id 발급 |

---

## Task 1: `ProposalState` enum + `Proposal` 모델

**Files:**
- Modify: `src/db/models.py` (Line 405 직후 enum, Line 469 직후 모델)
- Test: `tests/test_db/test_proposals_repository.py` (T3에서 본격 작성, T1에서는 import 가능 여부만)

- [ ] **Step 1: 새 enum과 모델 추가**

`src/db/models.py`의 `class ImplementationCategory(enum.Enum)` 정의 바로 뒤에 추가.

```python
class ProposalState(enum.Enum):
    """제안서 상태 머신."""

    DRAFT = "draft"
    READY = "ready"
    IN_FLIGHT = "in_flight"
    IMPLEMENTED = "implemented"
    FAILED = "failed"
    SKIPPED = "skipped"
    REVIEW_REQUIRED = "review_required"


class ProposalPriority(enum.Enum):
    """제안서 우선순위."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

`class DailySummary(Base)` 정의 바로 앞에 (즉 `ImplementationLog`와 `DailySummary` 사이) `Proposal` 모델 추가.

```python
class Proposal(Base):
    """자동 구현 파이프라인의 제안서 상태 테이블.

    md 파일은 사람이 읽는 표현. 본 테이블이 상태의 sole source of truth다.
    상태 전이는 ProposalRepository의 mark_* 메소드를 통해서만 일어난다.
    """

    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[ImplementationCategory] = mapped_column(
        SAEnum(ImplementationCategory, name="impl_category_enum", create_type=False),
        nullable=False,
    )
    state: Mapped[ProposalState] = mapped_column(
        SAEnum(ProposalState, name="proposal_state_enum"),
        nullable=False,
        index=True,
    )
    priority: Mapped[ProposalPriority] = mapped_column(
        SAEnum(ProposalPriority, name="proposal_priority_enum"),
        nullable=False,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Proposal(id={self.id}, path={self.path!r}, "
            f"state={self.state.value}, category={self.category.value})>"
        )
```

> **주의:** `create_type=False`는 `impl_category_enum`이 이미 `implementation_logs`에서 생성되었기 때문 (Alembic 마이그레이션에서 중복 생성 방지).

- [ ] **Step 2: import 가능 여부 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -c "from src.db.models import Proposal, ProposalState, ProposalPriority; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/db/models.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(db): Proposal 모델 + 상태/우선순위 enum 추가 (Phase 1 T1)"
```

---

## Task 2: Alembic 마이그레이션

**Files:**
- Create: `alembic/versions/<auto-hash>_add_proposals_table.py`

- [ ] **Step 1: 마이그레이션 자동 생성**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "add_proposals_table"
```
Expected: `Generating alembic/versions/<hash>_add_proposals_table.py ... done`

- [ ] **Step 2: 생성된 마이그레이션 검토 및 정리**

`alembic/versions/<hash>_add_proposals_table.py`를 열어 다음을 확인·수정한다.

- `op.create_table('proposals', ...)`가 정확히 9 컬럼(id/path/title/category/state/priority/last_attempt_at/failure_reason/skip_reason/cycle_id/created_at/updated_at)을 가질 것.
- `proposal_state_enum`, `proposal_priority_enum` 생성 명령 포함.
- `impl_category_enum` 재생성 시도가 있으면 제거 (이미 존재하므로 `existing_type=...` 또는 `sa.Enum(..., create_type=False)`로 처리).
- `op.create_index('ix_proposals_state', 'proposals', ['state'])` 와 `ix_proposals_cycle_id` 포함.
- `downgrade()`에 `op.drop_table('proposals')` + 두 enum drop.

`op.create_table` 직후에 unique 제약을 명시:
```python
sa.UniqueConstraint('path', name='uq_proposals_path'),
```

- [ ] **Step 3: 테스트 DB에 적용해 스키마 검증**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/alembic upgrade head
```
Expected: `Running upgrade <prev_hash> -> <new_hash>, add_proposals_table`

`psql`로 컬럼 확인:
```bash
psql "$DATABASE_URL" -c "\d proposals"
```
Expected: 12 columns + 2 indexes.

- [ ] **Step 4: downgrade 1단계로 검증**

```bash
PYTHONPATH=. .venv/bin/alembic downgrade -1
psql "$DATABASE_URL" -c "\d proposals" 2>&1 | grep -q "관계.*없음\|does not exist" && echo "DROP OK"
```
Expected: `DROP OK`

다시 upgrade:
```bash
PYTHONPATH=. .venv/bin/alembic upgrade head
```

- [ ] **Step 5: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add alembic/versions/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(db): proposals 테이블 마이그레이션 (Phase 1 T2)"
```

---

## Task 3: `ProposalRepository`

**Files:**
- Modify: `src/db/repository.py` (파일 끝)
- Test: `tests/test_db/test_proposals_repository.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_db/test_proposals_repository.py` 신설:

```python
"""ProposalRepository TDD."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    ImplementationCategory,
    Proposal,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _make_proposal(repo: ProposalRepository, path: str, state: ProposalState) -> Proposal:
    return repo.create(
        path=path,
        title=f"T-{path}",
        category=ImplementationCategory.BUG_FIX,
        state=state,
        priority=ProposalPriority.MEDIUM,
    )


def test_create_and_find_by_path(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "docs/proposals/2026-05-14_x.md", ProposalState.READY)
    session.commit()
    assert repo.find_by_path("docs/proposals/2026-05-14_x.md").id == p.id


def test_create_duplicate_path_raises(session):
    repo = ProposalRepository(session)
    _make_proposal(repo, "docs/proposals/dup.md", ProposalState.READY)
    session.commit()
    with pytest.raises(Exception):
        _make_proposal(repo, "docs/proposals/dup.md", ProposalState.READY)
        session.commit()


def test_list_ready_returns_only_ready_in_priority_order(session):
    repo = ProposalRepository(session)
    repo.create(
        path="a.md", title="A", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.LOW,
    )
    repo.create(
        path="b.md", title="B", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.CRITICAL,
    )
    repo.create(
        path="c.md", title="C", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.DRAFT, priority=ProposalPriority.CRITICAL,
    )
    session.commit()
    paths = [p.path for p in repo.list_ready()]
    assert paths == ["b.md", "a.md"]


def test_mark_in_flight_sets_state_and_cycle_id(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "x.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p.id, cycle_id="cycle-001")
    session.commit()
    refreshed = repo.find_by_path("x.md")
    assert refreshed.state == ProposalState.IN_FLIGHT
    assert refreshed.cycle_id == "cycle-001"
    assert refreshed.last_attempt_at is not None


def test_mark_in_flight_rejects_non_ready(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "y.md", ProposalState.IMPLEMENTED)
    session.commit()
    with pytest.raises(ValueError):
        repo.mark_in_flight(p.id, cycle_id="cycle-002")


def test_mark_implemented_clears_cycle_and_sets_state(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "z.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p.id, cycle_id="cycle-003")
    session.commit()
    repo.mark_implemented(p.id)
    session.commit()
    refreshed = repo.find_by_path("z.md")
    assert refreshed.state == ProposalState.IMPLEMENTED
    assert refreshed.cycle_id is None


def test_mark_failed_records_reason(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "f.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p.id, cycle_id="cycle-004")
    session.commit()
    repo.mark_failed(p.id, reason="ruff DTZ violation")
    session.commit()
    refreshed = repo.find_by_path("f.md")
    assert refreshed.state == ProposalState.FAILED
    assert refreshed.failure_reason == "ruff DTZ violation"


def test_mark_skipped_records_reason(session):
    repo = ProposalRepository(session)
    p = _make_proposal(repo, "s.md", ProposalState.READY)
    session.commit()
    repo.mark_skipped(p.id, reason="safety_gate_violation")
    session.commit()
    refreshed = repo.find_by_path("s.md")
    assert refreshed.state == ProposalState.SKIPPED
    assert refreshed.skip_reason == "safety_gate_violation"


def test_list_in_flight_for_cycle(session):
    repo = ProposalRepository(session)
    p1 = _make_proposal(repo, "p1.md", ProposalState.READY)
    p2 = _make_proposal(repo, "p2.md", ProposalState.READY)
    session.commit()
    repo.mark_in_flight(p1.id, cycle_id="cycle-X")
    repo.mark_in_flight(p2.id, cycle_id="cycle-Y")
    session.commit()
    rows = repo.list_in_flight_for_cycle("cycle-X")
    assert [r.path for r in rows] == ["p1.md"]
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_db/test_proposals_repository.py -v
```
Expected: 모두 `ImportError: cannot import name 'ProposalRepository'` 등의 실패.

- [ ] **Step 3: ProposalRepository 구현**

`src/db/repository.py` 파일 끝에 추가:

```python
from src.db.models import Proposal, ProposalPriority, ProposalState


class ProposalRepository:
    """제안서 상태 머신 데이터 접근 클래스.

    상태 전이는 본 클래스의 mark_* 메소드를 통해서만 일어난다.
    """

    _PRIORITY_ORDER = {
        ProposalPriority.CRITICAL: 0,
        ProposalPriority.HIGH: 1,
        ProposalPriority.MEDIUM: 2,
        ProposalPriority.LOW: 3,
    }

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        path: str,
        title: str,
        category: ImplementationCategory,
        state: ProposalState,
        priority: ProposalPriority,
    ) -> Proposal:
        """제안서를 신규 생성한다. path UNIQUE 제약 위반 시 예외."""
        now = datetime.now(UTC)
        p = Proposal(
            path=path,
            title=title,
            category=category,
            state=state,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        self._session.add(p)
        self._session.flush()
        logger.info("제안서 생성: %s (%s, %s)", path, state.value, priority.value)
        return p

    def find_by_path(self, path: str) -> Proposal | None:
        stmt = select(Proposal).where(Proposal.path == path)
        return self._session.execute(stmt).scalar_one_or_none()

    def list_ready(self) -> list[Proposal]:
        """READY 상태 제안서를 우선순위순(critical→low), 같은 우선순위는 path순."""
        stmt = select(Proposal).where(Proposal.state == ProposalState.READY)
        rows = list(self._session.execute(stmt).scalars().all())
        rows.sort(key=lambda r: (self._PRIORITY_ORDER[r.priority], r.path))
        return rows

    def list_in_flight_for_cycle(self, cycle_id: str) -> list[Proposal]:
        stmt = select(Proposal).where(
            Proposal.state == ProposalState.IN_FLIGHT,
            Proposal.cycle_id == cycle_id,
        )
        return list(self._session.execute(stmt).scalars().all())

    def mark_in_flight(self, proposal_id: int, *, cycle_id: str) -> None:
        """READY → IN_FLIGHT 전이."""
        p = self._require(proposal_id)
        if p.state != ProposalState.READY:
            raise ValueError(
                f"mark_in_flight requires READY, got {p.state.value} (id={proposal_id})"
            )
        now = datetime.now(UTC)
        p.state = ProposalState.IN_FLIGHT
        p.cycle_id = cycle_id
        p.last_attempt_at = now
        p.updated_at = now
        logger.info("제안서 IN_FLIGHT: %s (cycle=%s)", p.path, cycle_id)

    def mark_implemented(self, proposal_id: int) -> None:
        """IN_FLIGHT → IMPLEMENTED 전이."""
        p = self._require(proposal_id)
        if p.state != ProposalState.IN_FLIGHT:
            raise ValueError(
                f"mark_implemented requires IN_FLIGHT, got {p.state.value}"
            )
        now = datetime.now(UTC)
        p.state = ProposalState.IMPLEMENTED
        p.cycle_id = None
        p.updated_at = now
        logger.info("제안서 IMPLEMENTED: %s", p.path)

    def mark_failed(self, proposal_id: int, *, reason: str) -> None:
        """IN_FLIGHT → FAILED 전이 (사유 기록)."""
        p = self._require(proposal_id)
        if p.state != ProposalState.IN_FLIGHT:
            raise ValueError(f"mark_failed requires IN_FLIGHT, got {p.state.value}")
        now = datetime.now(UTC)
        p.state = ProposalState.FAILED
        p.failure_reason = reason
        p.cycle_id = None
        p.updated_at = now
        logger.info("제안서 FAILED: %s — %s", p.path, reason)

    def mark_skipped(self, proposal_id: int, *, reason: str) -> None:
        """READY → SKIPPED 전이 (안전 게이트 거절 등)."""
        p = self._require(proposal_id)
        if p.state not in (ProposalState.READY, ProposalState.DRAFT):
            raise ValueError(f"mark_skipped requires READY|DRAFT, got {p.state.value}")
        now = datetime.now(UTC)
        p.state = ProposalState.SKIPPED
        p.skip_reason = reason
        p.updated_at = now
        logger.info("제안서 SKIPPED: %s — %s", p.path, reason)

    def _require(self, proposal_id: int) -> Proposal:
        p = self._session.get(Proposal, proposal_id)
        if p is None:
            raise LookupError(f"Proposal id={proposal_id} not found")
        return p
```

> **datetime import:** 파일 상단의 datetime import에 `UTC`가 빠져있으면 `from datetime import UTC, datetime`로 보강. 이미 있다면 건드리지 않음.

- [ ] **Step 4: 테스트 실행해 통과 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_db/test_proposals_repository.py -v
```
Expected: `9 passed`

- [ ] **Step 5: ruff/mypy 검증**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
.venv/bin/ruff check src/db/repository.py tests/test_db/test_proposals_repository.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/db/repository.py
```
Expected: `All checks passed!` and `Success: no issues found`

- [ ] **Step 6: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/db/repository.py tests/test_db/test_proposals_repository.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(db): ProposalRepository + TDD 9건 (Phase 1 T3)"
```

---

## Task 4: 기존 markdown → DB 동기화 스크립트

**Files:**
- Create: `scripts/harness/sync_proposals_md_to_db.py`
- Test: `tests/test_harness/test_sync_md_to_db.py`

- [ ] **Step 1: 패키지 stub + 실패 테스트**

`tests/test_harness/__init__.py`:
```python
"""하네스 도메인 테스트 패키지."""
```

`tests/test_harness/test_sync_md_to_db.py`:
```python
"""sync_proposals_md_to_db.py TDD."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.db.repository import ProposalRepository
from scripts.harness.sync_proposals_md_to_db import (
    parse_proposal,
    sync_directory,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def test_parse_proposal_extracts_meta(tmp_path: Path):
    f = tmp_path / "2026-05-14_x.md"
    f.write_text(
        "# 제목\n\n## 메타데이터\n- 작성: Cowork\n- 일자: 2026-05-14\n"
        "- 상태: implemented\n- 우선순위: high\n- 카테고리: bug_fix\n"
        "- 관련파일: src/x.py\n\n## 본문\n…",
        encoding="utf-8",
    )
    parsed = parse_proposal(f)
    assert parsed["state"] == "implemented"
    assert parsed["category"] == "bug_fix"
    assert parsed["priority"] == "high"
    assert parsed["title"] == "제목"


def test_parse_proposal_unknown_priority_defaults_to_medium(tmp_path: Path):
    f = tmp_path / "y.md"
    f.write_text("# T\n\n## 메타데이터\n- 상태: ready\n- 카테고리: refactor\n", encoding="utf-8")
    parsed = parse_proposal(f)
    assert parsed["priority"] == "medium"


def test_sync_directory_inserts_all_then_skips_existing(tmp_path: Path, session):
    (tmp_path / "a.md").write_text(
        "# A\n\n## 메타데이터\n- 상태: implemented\n- 카테고리: bug_fix\n- 우선순위: high\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        "# B\n\n## 메타데이터\n- 상태: ready\n- 카테고리: param_tuning\n- 우선순위: medium\n",
        encoding="utf-8",
    )
    inserted, skipped = sync_directory(tmp_path, session)
    session.commit()
    assert (inserted, skipped) == (2, 0)

    repo = ProposalRepository(session)
    assert repo.find_by_path(str((tmp_path / "a.md").resolve())) is not None

    # 두 번째 실행은 모두 skip
    inserted2, skipped2 = sync_directory(tmp_path, session)
    session.commit()
    assert (inserted2, skipped2) == (0, 2)
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_sync_md_to_db.py -v
```
Expected: `ModuleNotFoundError: scripts.harness.sync_proposals_md_to_db`

- [ ] **Step 3: 구현**

`scripts/harness/sync_proposals_md_to_db.py`:

```python
"""기존 docs/proposals/*.md를 proposals 테이블로 일괄 동기화.

상태/우선순위/카테고리를 markdown 메타데이터에서 추출하고, path UNIQUE 위반은 skip한다.
한 번 실행하고 끝나는 일회성 스크립트.

CLI:
    python -m scripts.harness.sync_proposals_md_to_db [--dir docs/proposals]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import ImplementationCategory, ProposalPriority, ProposalState
from src.db.repository import ProposalRepository
from src.db.session import get_session

REPO_ROOT = Path(__file__).resolve().parents[2]
META_LINE = re.compile(r"^-\s*([^:]+?)\s*:\s*(.+?)\s*$")
TITLE_LINE = re.compile(r"^#\s+(.+?)\s*$")

# 한글 키 → 코드 키
_KEY_MAP = {
    "상태": "state",
    "우선순위": "priority",
    "카테고리": "category",
    "일자": "date",
    "작성": "author",
}

# 알 수 없는 값은 기본값으로 매핑
_STATE_DEFAULT = "draft"
_PRIORITY_DEFAULT = "medium"
_CATEGORY_DEFAULT = "enhancement"


def parse_proposal(path: Path) -> dict[str, Any]:
    """제안서 markdown에서 title + 메타데이터를 추출한다."""
    title = path.stem
    meta: dict[str, str] = {}
    in_meta = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        tm = TITLE_LINE.match(line)
        if tm and title == path.stem:
            title = tm.group(1)
        if line.startswith("## 메타데이터") or line.startswith("## 메타 정보"):
            in_meta = True
            continue
        if in_meta:
            if line.startswith("## "):
                break
            m = META_LINE.match(line)
            if m:
                korean_key = m.group(1)
                code_key = _KEY_MAP.get(korean_key)
                if code_key:
                    meta[code_key] = m.group(2)
    return {
        "title": title[:300],
        "state": meta.get("state", _STATE_DEFAULT),
        "priority": meta.get("priority", _PRIORITY_DEFAULT),
        "category": meta.get("category", _CATEGORY_DEFAULT),
    }


def _coerce_state(raw: str) -> ProposalState:
    try:
        return ProposalState(raw)
    except ValueError:
        return ProposalState.DRAFT


def _coerce_priority(raw: str) -> ProposalPriority:
    try:
        return ProposalPriority(raw)
    except ValueError:
        return ProposalPriority.MEDIUM


def _coerce_category(raw: str) -> ImplementationCategory:
    try:
        return ImplementationCategory(raw)
    except ValueError:
        return ImplementationCategory.ENHANCEMENT


def sync_directory(directory: Path, session: Session) -> tuple[int, int]:
    """디렉토리 내 모든 *.md를 proposals 테이블로 INSERT. (inserted, skipped) 반환."""
    repo = ProposalRepository(session)
    inserted = skipped = 0
    for md in sorted(directory.glob("*.md")):
        path_str = str(md.resolve())
        if repo.find_by_path(path_str) is not None:
            skipped += 1
            continue
        parsed = parse_proposal(md)
        repo.create(
            path=path_str,
            title=parsed["title"],
            category=_coerce_category(parsed["category"]),
            state=_coerce_state(parsed["state"]),
            priority=_coerce_priority(parsed["priority"]),
        )
        inserted += 1
    return inserted, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=REPO_ROOT / "docs" / "proposals",
        help="제안서 디렉토리",
    )
    args = parser.parse_args(argv)

    with get_session() as session:
        inserted, skipped = sync_directory(args.dir, session)

    print(f"inserted={inserted}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_sync_md_to_db.py -v
```
Expected: `3 passed`

- [ ] **Step 5: 실제 docs/proposals/ 동기화**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m scripts.harness.sync_proposals_md_to_db
```
Expected: `inserted=37, skipped=0`

재실행으로 idempotency 확인:
```bash
PYTHONPATH=. .venv/bin/python -m scripts.harness.sync_proposals_md_to_db
```
Expected: `inserted=0, skipped=37`

- [ ] **Step 6: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/harness/sync_proposals_md_to_db.py tests/test_harness/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): md → proposals DB 동기화 스크립트 + TDD (Phase 1 T4)"
```

---

## Task 5: `claude-progress.json` v1 스키마 + Initializer 헬퍼

**Files:**
- Create: `src/harness/__init__.py`, `src/harness/progress.py`
- Test: `tests/test_harness/test_progress.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_harness/test_progress.py`:
```python
"""claude-progress.json 스키마 TDD."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.harness.progress import (
    CycleProgress,
    InitializerCheck,
    InitializerCheckResult,
    load_progress,
    save_progress,
)


def test_create_minimal_cycle():
    c = CycleProgress(
        cycle_id="c-1",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
    )
    assert c.cycle_id == "c-1"
    assert c.initializer_checks == []
    assert c.pending == []
    assert c.history == []


def test_roundtrip_save_load(tmp_path: Path):
    c = CycleProgress(
        cycle_id="c-2",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
        last_safe_tag="v0.2.4",
    )
    c.initializer_checks.append(
        InitializerCheck(name="alembic_head", result=InitializerCheckResult.PASS)
    )
    c.pending.append("docs/proposals/x.md")
    p = tmp_path / "claude-progress.json"
    save_progress(p, c)
    loaded = load_progress(p)
    assert loaded.cycle_id == "c-2"
    assert loaded.last_safe_tag == "v0.2.4"
    assert loaded.initializer_checks[0].name == "alembic_head"


def test_transition_records_history():
    c = CycleProgress(
        cycle_id="c-3",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
    )
    c.transition("docs/proposals/a.md", from_state="pending", to_state="in_flight")
    assert len(c.history) == 1
    assert c.history[0].path == "docs/proposals/a.md"
    assert c.history[0].to_state == "in_flight"


def test_load_missing_file_returns_none(tmp_path: Path):
    assert load_progress(tmp_path / "nope.json") is None


def test_save_creates_parent_dir(tmp_path: Path):
    target = tmp_path / "deep" / "deeper" / "progress.json"
    c = CycleProgress(
        cycle_id="c-4",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="real",
    )
    save_progress(target, c)
    assert target.exists()
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_progress.py -v
```
Expected: `ModuleNotFoundError: src.harness.progress`

- [ ] **Step 3: 구현**

`src/harness/__init__.py`:
```python
"""하네스 엔지니어링 도메인 패키지."""
```

`src/harness/progress.py`:
```python
"""claude-progress.json v1 스키마와 load/save 헬퍼.

매 사이클의 단일 상태 파일. Initializer가 생성하고 모든 워커가 읽는다.
스키마 변경 시 v1 → v2로 bump하고 본 모듈을 호환 어댑터로 만든다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


SCHEMA_VERSION = 1


class InitializerCheckResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class InitializerCheck(BaseModel):
    """환경 점검 항목 1건."""

    name: str
    result: InitializerCheckResult
    detail: str | None = None


class StateTransition(BaseModel):
    """제안서 상태 전이 1건."""

    path: str
    from_state: str
    to_state: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = None


class CycleProgress(BaseModel):
    """단일 사이클의 진행 상태."""

    schema_version: int = SCHEMA_VERSION
    cycle_id: str
    started_at: datetime
    env: Literal["virtual", "real"]
    last_safe_tag: str | None = None
    initializer_checks: list[InitializerCheck] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    in_flight: list[str] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    history: list[StateTransition] = Field(default_factory=list)

    def transition(
        self,
        path: str,
        *,
        from_state: str,
        to_state: str,
        reason: str | None = None,
    ) -> None:
        """제안서 상태 전이를 history에 기록한다."""
        self.history.append(
            StateTransition(
                path=path,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
            )
        )


def load_progress(path: Path) -> CycleProgress | None:
    """파일이 없거나 비어 있으면 None."""
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return CycleProgress.model_validate_json(raw)


def save_progress(path: Path, progress: CycleProgress) -> None:
    """JSON으로 저장. 상위 디렉토리는 자동 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        progress.model_dump_json(indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_progress.py -v
```
Expected: `5 passed`

- [ ] **Step 5: ruff/mypy**

```bash
.venv/bin/ruff check src/harness/ tests/test_harness/test_progress.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/progress.py
```
Expected: `All checks passed!` and `Success`

- [ ] **Step 6: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/ tests/test_harness/test_progress.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): claude-progress.json v1 스키마 + 헬퍼 (Phase 1 T5)"
```

---

## Task 6: 안전 게이트 hook 로직 (Python 모듈)

**Files:**
- Create: `src/harness/hooks/__init__.py`, `pre_tool_use.py`, `pre_bash.py`, `post_edit.py`, `stop.py`
- Test: `tests/test_harness/test_hooks_pre_tool_use.py`, `test_hooks_pre_bash.py`, `test_hooks_post_edit.py`, `test_hooks_stop.py`

> **설계 노트:** Claude Code hooks는 stdin으로 JSON 받고 exit code로 allow(0)/block(2)을 알린다. 본 task는 그 의사결정 로직만 모듈화하고, 진입점 wrapper는 T7에서 만든다.

### Task 6a: pre_tool_use 차단 룰

- [ ] **Step 1: 실패 테스트**

`tests/test_harness/test_hooks_pre_tool_use.py`:
```python
"""PreToolUse(Edit|Write) hook 차단 룰 TDD."""

from __future__ import annotations

import pytest

from src.harness.hooks.pre_tool_use import HookDecision, evaluate


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
def test_blocks_forbidden_paths(tool: str, path: str):
    decision = evaluate(tool, {"file_path": path})
    assert decision.blocked is True
    assert path.split("/")[-1] in decision.reason.lower() or path in decision.reason


def test_allows_normal_src_edit():
    decision = evaluate("Edit", {"file_path": "src/strategy/rsi.py"})
    assert decision.blocked is False


def test_blocks_pyproject_dependency_lines_via_marker():
    # dependency 라인 차단은 patch content를 보지 않으면 불가능하므로
    # 본 모듈에서는 pyproject.toml 자체 편집을 경고 수준으로 처리한다.
    decision = evaluate("Edit", {"file_path": "pyproject.toml"})
    assert decision.warning is True
    assert decision.blocked is False  # 경고만 (블록은 PostToolUse에서)


def test_unknown_tool_passes_through():
    decision = evaluate("Read", {"file_path": ".env"})
    assert decision.blocked is False
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_hooks_pre_tool_use.py -v
```

- [ ] **Step 3: 구현**

`src/harness/hooks/__init__.py`:
```python
"""Claude Code hook 의사결정 로직 모음."""
```

`src/harness/hooks/pre_tool_use.py`:
```python
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
            return HookDecision(blocked=True, reason=f"forbidden path prefix: {prefix}")

    if leaf in _WARN_EXACT:
        return HookDecision(blocked=False, warning=True, reason=f"warn: {leaf} edit detected")

    return HookDecision(blocked=False)
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_hooks_pre_tool_use.py -v
```
Expected: `4 passed`

### Task 6b: pre_bash 차단 룰

- [ ] **Step 5: 실패 테스트**

`tests/test_harness/test_hooks_pre_bash.py`:
```python
"""PreToolUse(Bash) — 위험 명령 차단 TDD."""

import pytest

from src.harness.hooks.pre_bash import evaluate


@pytest.mark.parametrize(
    "cmd",
    [
        "git push --force",
        "git push -f origin main",
        "rm -rf /Users/songhansu/IdeaProjects/kis-autotrader",
        "psql -c 'DROP TABLE proposals'",
        "psql -d kis_trader -c \"DROP DATABASE kis_trader\"",
        "launchctl unload ~/Library/LaunchAgents/com.kis.autotrader.plist",
    ],
)
def test_blocks_dangerous_commands(cmd: str):
    decision = evaluate(cmd)
    assert decision.blocked is True


@pytest.mark.parametrize(
    "cmd",
    [
        "ls -la",
        "git status",
        "pytest tests/",
        "rm logs/*.log",
        "rm -rf .pytest_cache",
        "psql -c 'SELECT count(*) FROM proposals'",
    ],
)
def test_allows_safe_commands(cmd: str):
    decision = evaluate(cmd)
    assert decision.blocked is False
```

- [ ] **Step 6: 구현**

`src/harness/hooks/pre_bash.py`:
```python
"""PreToolUse(Bash) — 운영 영향이 큰 명령을 즉시 차단."""

from __future__ import annotations

import re

from src.harness.hooks.pre_tool_use import HookDecision


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgit\s+push\s+(--force|-f)\b"), "git push --force"),
    (re.compile(r"\brm\s+-rf\s+/(?!tmp/|var/folders/)"), "rm -rf on root-level path"),
    (re.compile(r"\bdrop\s+(table|database|schema)\b", re.IGNORECASE), "DROP SQL"),
    (re.compile(r"\blaunchctl\s+unload\s+.*com\.kis\.autotrader"), "unload autotrader"),
    (re.compile(r"\blaunchctl\s+unload\s+.*com\.kis\.watchdog"), "unload watchdog"),
    (re.compile(r"\bgit\s+config\s+(--global|--system)\b"), "git global config"),
)


def evaluate(command: str) -> HookDecision:
    for pat, label in _PATTERNS:
        if pat.search(command):
            return HookDecision(blocked=True, reason=f"dangerous: {label}")
    return HookDecision(blocked=False)
```

- [ ] **Step 7: 통과 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_hooks_pre_bash.py -v
```
Expected: `12 passed`

### Task 6c: post_edit + stop hook

- [ ] **Step 8: 실패 테스트**

`tests/test_harness/test_hooks_post_edit.py`:
```python
"""PostToolUse(Edit|Write) — ruff/DTZ 자동 검사 TDD."""

import pytest

from src.harness.hooks.post_edit import HookDecision, evaluate


def test_non_python_file_no_action():
    d = evaluate("docs/x.md", file_count_in_cycle=1)
    assert d.run_ruff is False
    assert d.warn is False


def test_python_file_triggers_ruff():
    d = evaluate("src/strategy/rsi.py", file_count_in_cycle=1)
    assert d.run_ruff is True


def test_exceeding_file_threshold_warns():
    d = evaluate("src/strategy/rsi.py", file_count_in_cycle=6)
    assert d.warn is True
    assert "5" in d.message  # 5파일 임계
```

`tests/test_harness/test_hooks_stop.py`:
```python
"""Stop hook — 검증 단계 미실행 차단 TDD."""

from src.harness.hooks.stop import evaluate


def test_blocks_when_verification_artifacts_missing():
    d = evaluate(verification_artifacts={})
    assert d.blocked is True


def test_blocks_when_only_partial_artifacts():
    d = evaluate(verification_artifacts={"pytest": "ok"})
    assert d.blocked is True
    assert "mypy" in d.reason.lower()


def test_allows_when_all_artifacts_present():
    d = evaluate(verification_artifacts={"pytest": "ok", "mypy": "ok", "ruff": "ok"})
    assert d.blocked is False
```

- [ ] **Step 9: 구현**

`src/harness/hooks/post_edit.py`:
```python
"""PostToolUse(Edit|Write) — Python 변경에 대한 ruff/DTZ 검사 신호."""

from __future__ import annotations

from dataclasses import dataclass

_FILE_THRESHOLD = 5


@dataclass(frozen=True)
class HookDecision:
    run_ruff: bool
    warn: bool = False
    message: str = ""


def evaluate(file_path: str, *, file_count_in_cycle: int) -> HookDecision:
    if not file_path.endswith(".py"):
        return HookDecision(run_ruff=False)
    warn = file_count_in_cycle > _FILE_THRESHOLD
    msg = (
        f"이번 사이클에서 {file_count_in_cycle}개 파일 편집 — {_FILE_THRESHOLD} 초과 경고"
        if warn
        else ""
    )
    return HookDecision(run_ruff=True, warn=warn, message=msg)
```

`src/harness/hooks/stop.py`:
```python
"""Stop hook — Verifier 단계의 검증 출력이 모두 첨부되지 않으면 종료 차단."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_REQUIRED = ("pytest", "mypy", "ruff")


@dataclass(frozen=True)
class HookDecision:
    blocked: bool
    reason: str = ""


def evaluate(*, verification_artifacts: dict[str, Any]) -> HookDecision:
    missing = [k for k in _REQUIRED if k not in verification_artifacts]
    if missing:
        return HookDecision(
            blocked=True,
            reason=f"verification artifacts missing: {', '.join(missing)}",
        )
    return HookDecision(blocked=False)
```

- [ ] **Step 10: 모든 hook 테스트 통과**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_hooks_post_edit.py tests/test_harness/test_hooks_stop.py -v
```
Expected: `6 passed`

- [ ] **Step 11: ruff/mypy 일괄**

```bash
.venv/bin/ruff check src/harness/hooks/ tests/test_harness/test_hooks_*.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/hooks/
```
Expected: `All checks passed!` and `Success`

- [ ] **Step 12: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/hooks/ tests/test_harness/test_hooks_*.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): hook 의사결정 로직 4종 + TDD (Phase 1 T6)"
```

---

## Task 7: `.claude/settings.json` Hook 등록 + wrapper

**Files:**
- Create: `.claude/settings.json`, `scripts/claude-hooks/run_hook.py`
- Test: `tests/test_harness/test_hook_wrapper.py`

- [ ] **Step 1: Wrapper 실패 테스트**

`tests/test_harness/test_hook_wrapper.py`:
```python
"""Claude Code hook wrapper TDD — stdin JSON → exit code 매핑."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "claude-hooks" / "run_hook.py"


def _run(payload: dict[str, object]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(WRAPPER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(WRAPPER.parents[2])},
        check=False,
    )
    return proc.returncode, proc.stderr


def test_pre_tool_use_blocks_env_edit():
    code, err = _run({
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": ".env"},
    })
    assert code == 2
    assert "forbidden" in err.lower()


def test_pre_tool_use_allows_normal_edit():
    code, _ = _run({
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": "src/strategy/rsi.py"},
    })
    assert code == 0


def test_pre_bash_blocks_force_push():
    code, err = _run({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push --force"},
    })
    assert code == 2
    assert "dangerous" in err.lower()


def test_stop_blocks_when_artifacts_missing(tmp_path: Path, monkeypatch):
    code, err = _run({
        "hook_event_name": "Stop",
        "verification_artifacts": {},
    })
    assert code == 2
    assert "verification" in err.lower()
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_hook_wrapper.py -v
```
Expected: `FileNotFoundError: scripts/claude-hooks/run_hook.py`

- [ ] **Step 3: Wrapper 구현**

`scripts/claude-hooks/run_hook.py`:
```python
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
            decision = pre_bash.evaluate(tool_input.get("command", ""))
            if decision.blocked:
                print(f"[pre_bash] BLOCKED: {decision.reason}", file=sys.stderr)
                return 2
            return 0
        decision = pre_tool_use.evaluate(tool, tool_input)
        if decision.blocked:
            print(f"[pre_tool_use] BLOCKED: {decision.reason}", file=sys.stderr)
            return 2
        if decision.warning:
            print(f"[pre_tool_use] WARN: {decision.reason}", file=sys.stderr)
        return 0

    if event == "PostToolUse" and tool in ("Edit", "Write", "MultiEdit"):
        decision = post_edit.evaluate(
            tool_input.get("file_path", ""),
            file_count_in_cycle=int(payload.get("file_count_in_cycle", 1)),
        )
        if decision.warn:
            print(f"[post_edit] WARN: {decision.message}", file=sys.stderr)
        if decision.run_ruff:
            # ruff 실행은 wrapper 책임 밖 — Stop hook 시점에서 verifier가 수행
            pass
        return 0

    if event == "Stop":
        decision = stop.evaluate(
            verification_artifacts=payload.get("verification_artifacts", {}) or {},
        )
        if decision.blocked:
            print(f"[stop] BLOCKED: {decision.reason}", file=sys.stderr)
            return 2
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

```bash
chmod +x scripts/claude-hooks/run_hook.py
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_hook_wrapper.py -v
```
Expected: `4 passed`

- [ ] **Step 5: `.claude/settings.json` 작성**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=$CLAUDE_PROJECT_DIR $CLAUDE_PROJECT_DIR/.venv/bin/python $CLAUDE_PROJECT_DIR/scripts/claude-hooks/run_hook.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=$CLAUDE_PROJECT_DIR $CLAUDE_PROJECT_DIR/.venv/bin/python $CLAUDE_PROJECT_DIR/scripts/claude-hooks/run_hook.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=$CLAUDE_PROJECT_DIR $CLAUDE_PROJECT_DIR/.venv/bin/python $CLAUDE_PROJECT_DIR/scripts/claude-hooks/run_hook.py"
          }
        ]
      }
    ]
  }
}
```

> **워크트리 주의:** 본 `.claude/settings.json`은 워크트리에 한정해 적용된다. 메인 repo로 머지 시점에는 운영 영향을 고려해 사용자가 명시적으로 wire한다.

- [ ] **Step 6: 사이드 이펙트 sanity — 실제 Claude Code에서 hook이 발동하는지**

본 단계는 manual smoke test. 다음 명령 실행 시 차단됨을 확인:

```bash
# Claude Code 세션에서 (이 plan을 실행 중인 세션 아닌 별도 세션 권장):
# Edit ".env" → 차단되어야 함
```
Expected: hook에서 BLOCKED 메시지

- [ ] **Step 7: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add .claude/settings.json scripts/claude-hooks/ tests/test_harness/test_hook_wrapper.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): .claude/settings.json + hook wrapper (Phase 1 T7)"
```

---

## Task 8: `src/harness/trigger.py` — 동시성·인터벌·장중 가드

**Files:**
- Create: `src/harness/trigger.py`
- Modify: `src/config.py` (HarnessSettings 추가)
- Test: `tests/test_harness/test_trigger.py`

- [ ] **Step 1: `HarnessSettings` 추가**

`src/config.py`에서 기존 `class TelegramSettings`와 같은 패턴을 찾아 그 옆에 추가:

```python
@dataclass(frozen=True)
class HarnessSettings:
    """하네스 자동 구현 파이프라인 운영 설정."""

    min_cycle_interval_seconds: int = field(
        default_factory=lambda: int(_env("HARNESS_MIN_CYCLE_INTERVAL_SECONDS", "300"))
    )
    pause_lock_path: str = field(
        default_factory=lambda: _env(
            "HARNESS_PAUSE_LOCK_PATH",
            os.path.expanduser("~/.kis-autotrader/harness-paused"),
        )
    )
    cycle_lock_path: str = field(
        default_factory=lambda: _env(
            "HARNESS_CYCLE_LOCK_PATH",
            os.path.expanduser("~/.kis-autotrader/harness-cycle-in-flight"),
        )
    )
```

그리고 `Settings` 클래스에 필드 추가:
```python
harness: HarnessSettings = field(default_factory=HarnessSettings)
```

> **import 보강:** `import os`가 src/config.py 상단에 없으면 추가.

- [ ] **Step 2: 실패 테스트**

`tests/test_harness/test_trigger.py`:
```python
"""harness trigger 가드 TDD."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.harness.trigger import (
    TriggerDecision,
    can_trigger,
    paused,
    set_paused,
)


@pytest.fixture
def tmp_lock_paths(tmp_path: Path, monkeypatch):
    pause = tmp_path / "paused"
    cycle = tmp_path / "in-flight"
    monkeypatch.setenv("HARNESS_PAUSE_LOCK_PATH", str(pause))
    monkeypatch.setenv("HARNESS_CYCLE_LOCK_PATH", str(cycle))
    return pause, cycle


def test_no_locks_allows(tmp_lock_paths):
    decision = can_trigger(env="virtual", market_hour=False)
    assert decision.allowed is True


def test_pause_lock_blocks(tmp_lock_paths):
    pause, _ = tmp_lock_paths
    pause.touch()
    decision = can_trigger(env="virtual", market_hour=False)
    assert decision.allowed is False
    assert "paused" in decision.reason.lower()


def test_cycle_in_flight_blocks(tmp_lock_paths):
    _, cycle = tmp_lock_paths
    cycle.write_text("cycle-xx")
    decision = can_trigger(env="virtual", market_hour=False)
    assert decision.allowed is False
    assert "in-flight" in decision.reason.lower() or "in_flight" in decision.reason.lower()


def test_min_interval_blocks_if_too_recent(tmp_lock_paths, monkeypatch):
    monkeypatch.setenv("HARNESS_MIN_CYCLE_INTERVAL_SECONDS", "300")
    # 마지막 완료 시각을 60초 전으로 시뮬레이션
    decision = can_trigger(
        env="virtual",
        market_hour=False,
        last_completed_at=time.time() - 60,
    )
    assert decision.allowed is False
    assert "interval" in decision.reason.lower()


def test_real_env_market_hour_requires_force(tmp_lock_paths):
    decision = can_trigger(env="real", market_hour=True, force=False)
    assert decision.allowed is False
    assert "force" in decision.reason.lower()


def test_real_env_market_hour_with_force_allows(tmp_lock_paths):
    decision = can_trigger(env="real", market_hour=True, force=True)
    assert decision.allowed is True


def test_set_paused_creates_and_clears(tmp_lock_paths):
    set_paused(True)
    assert paused() is True
    set_paused(False)
    assert paused() is False
```

- [ ] **Step 3: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_trigger.py -v
```
Expected: `ImportError`

- [ ] **Step 4: 구현**

`src/harness/trigger.py`:
```python
"""사이클 트리거 가드 — CLI/Telegram 공통.

다음을 강제한다.
- 동시 실행 금지 (cycle_lock_path 존재 시 차단)
- 최소 인터벌 (마지막 완료로부터 N초 이내 재발동 차단)
- KIS_ENV=real + 장중 시간 → --force 없이는 차단
- pause_lock_path 존재 시 모든 발동 차단
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import settings


@dataclass(frozen=True)
class TriggerDecision:
    allowed: bool
    reason: str = ""


def _pause_path() -> Path:
    return Path(os.environ.get("HARNESS_PAUSE_LOCK_PATH", settings.harness.pause_lock_path))


def _cycle_path() -> Path:
    return Path(os.environ.get("HARNESS_CYCLE_LOCK_PATH", settings.harness.cycle_lock_path))


def _min_interval() -> int:
    return int(
        os.environ.get(
            "HARNESS_MIN_CYCLE_INTERVAL_SECONDS",
            str(settings.harness.min_cycle_interval_seconds),
        )
    )


def paused() -> bool:
    return _pause_path().exists()


def set_paused(value: bool) -> None:
    p = _pause_path()
    if value:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def can_trigger(
    *,
    env: str,
    market_hour: bool,
    force: bool = False,
    last_completed_at: float | None = None,
) -> TriggerDecision:
    """발동 가드 평가."""
    if paused():
        return TriggerDecision(allowed=False, reason="harness paused (pause lock present)")
    if _cycle_path().exists():
        return TriggerDecision(allowed=False, reason="cycle in-flight (lock present)")
    if env == "real" and market_hour and not force:
        return TriggerDecision(
            allowed=False, reason="KIS_ENV=real + market hour requires --force",
        )
    if last_completed_at is not None:
        elapsed = time.time() - last_completed_at
        if elapsed < _min_interval():
            return TriggerDecision(
                allowed=False,
                reason=f"min interval not met (elapsed={elapsed:.0f}s, required={_min_interval()}s)",
            )
    return TriggerDecision(allowed=True)


def acquire_cycle_lock(cycle_id: str) -> Path:
    """사이클 시작 시 lock 파일을 만들고 cycle_id를 적는다."""
    p = _cycle_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(cycle_id)
    return p


def release_cycle_lock() -> None:
    try:
        _cycle_path().unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 5: 통과 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_trigger.py -v
```
Expected: `7 passed`

- [ ] **Step 6: ruff/mypy**

```bash
.venv/bin/ruff check src/harness/trigger.py src/config.py tests/test_harness/test_trigger.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/trigger.py
```

- [ ] **Step 7: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/trigger.py src/config.py tests/test_harness/test_trigger.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): trigger 가드 (동시성·인터벌·장중) + HarnessSettings (Phase 1 T8)"
```

---

## Task 9: `scripts/trigger_implement.sh` CLI 트리거

**Files:**
- Create: `scripts/trigger_implement.sh`

- [ ] **Step 1: 스크립트 작성**

```bash
#!/usr/bin/env bash
# 수동 자동 구현 사이클 트리거.
#
# 사용:
#   scripts/trigger_implement.sh                     # 기본
#   scripts/trigger_implement.sh --dry              # 안전 게이트만 돌리고 구현 안 함
#   scripts/trigger_implement.sh --proposal X.md    # 단일 제안서만
#   scripts/trigger_implement.sh --force            # real+장중 가드 우회

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY=""
PROPOSAL=""
FORCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry) DRY="1"; shift ;;
    --proposal) PROPOSAL="$2"; shift 2 ;;
    --force) FORCE="--force"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

# Python 가드 평가
PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" -c "
import sys
from datetime import datetime, timezone, timedelta
from src.harness.trigger import can_trigger
from src.config import settings

# 한국 표준시
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
in_market = (
    now_kst.weekday() < 5
    and (now_kst.hour, now_kst.minute) >= (9, 0)
    and (now_kst.hour, now_kst.minute) <= (15, 30)
)
force = '$FORCE' == '--force'
d = can_trigger(env=settings.kis.env, market_hour=in_market, force=force)
if not d.allowed:
    print(f'BLOCKED: {d.reason}', file=sys.stderr)
    sys.exit(2)
print('OK')
"

if [[ -n "$DRY" ]]; then
  echo "[trigger] --dry: 가드만 통과, 구현 단계 생략"
  exit 0
fi

# 자동 구현 사이클 호출 (기존 launchd 작업 재사용)
exec launchctl start com.kis.autoimplement
```

> **참조 attribute**: `settings.kis.env`는 `src/config.py:140`의 `KISConfig.env` 필드 (default `"virtual"`).

- [ ] **Step 2: 권한 부여 + dry-run 검증**

```bash
chmod +x scripts/trigger_implement.sh
HARNESS_PAUSE_LOCK_PATH=/tmp/h-pause HARNESS_CYCLE_LOCK_PATH=/tmp/h-cycle scripts/trigger_implement.sh --dry
```
Expected: `[trigger] --dry: 가드만 통과...`

- [ ] **Step 3: pause lock으로 차단 확인**

```bash
touch /tmp/h-pause
HARNESS_PAUSE_LOCK_PATH=/tmp/h-pause HARNESS_CYCLE_LOCK_PATH=/tmp/h-cycle scripts/trigger_implement.sh --dry || echo "blocked OK ($?)"
rm /tmp/h-pause
```
Expected: `BLOCKED: harness paused ...` then `blocked OK (2)`

- [ ] **Step 4: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/trigger_implement.sh
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): scripts/trigger_implement.sh CLI 트리거 (Phase 1 T9)"
```

---

## Task 10: Telegram `/run_implement` 명령

**Files:**
- Create: `src/harness/telegram_commands.py`
- Test: `tests/test_notify/test_harness_commands.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_notify/test_harness_commands.py`:
```python
"""Telegram 하네스 명령 TDD."""

from __future__ import annotations

import pytest

from src.harness.telegram_commands import (
    cmd_pause_implement,
    cmd_run_implement,
    cmd_status_implement,
)
from src.harness.trigger import paused, set_paused


@pytest.fixture
def tmp_lock_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_PAUSE_LOCK_PATH", str(tmp_path / "p"))
    monkeypatch.setenv("HARNESS_CYCLE_LOCK_PATH", str(tmp_path / "c"))
    yield


@pytest.mark.asyncio
async def test_run_implement_blocked_when_paused(tmp_lock_paths):
    set_paused(True)
    try:
        msg = await cmd_run_implement("")
        assert "차단" in msg or "blocked" in msg.lower()
    finally:
        set_paused(False)


@pytest.mark.asyncio
async def test_pause_implement_toggles(tmp_lock_paths):
    msg = await cmd_pause_implement("")
    assert paused() is True
    assert "일시 중단" in msg

    msg = await cmd_pause_implement("resume")
    assert paused() is False
    assert "재개" in msg


@pytest.mark.asyncio
async def test_status_implement_returns_summary(tmp_lock_paths):
    msg = await cmd_status_implement("")
    assert "harness" in msg.lower() or "사이클" in msg
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_notify/test_harness_commands.py -v
```
Expected: `ModuleNotFoundError: src.harness.telegram_commands`

- [ ] **Step 3: 구현**

`src/harness/telegram_commands.py`:
```python
"""Telegram bot 하네스 명령 핸들러.

/run_implement [--dry]      → 즉시 1회 사이클 시작 (가드 통과 시)
/status_implement           → 현재 사이클 상태와 가드 상태
/pause_implement [resume]   → 일시 중단/재개
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import settings
from src.harness.progress import load_progress
from src.harness.trigger import (
    acquire_cycle_lock,
    can_trigger,
    paused,
    release_cycle_lock,
    set_paused,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_KST = timezone(timedelta(hours=9))


def _is_market_hour(now: datetime | None = None) -> bool:
    now = now or datetime.now(_KST)
    if now.weekday() >= 5:
        return False
    return (now.hour, now.minute) >= (9, 0) and (now.hour, now.minute) <= (15, 30)


async def cmd_run_implement(args: str) -> str:
    dry = "--dry" in args
    force = "--force" in args
    decision = can_trigger(
        env=settings.kis.env, market_hour=_is_market_hour(), force=force,
    )
    if not decision.allowed:
        return f"❌ 발동 차단: {decision.reason}"

    if dry:
        return "✅ 가드 통과 — 구현은 생략(--dry)"

    cycle_id = f"manual-{datetime.now(_KST).strftime('%Y%m%d-%H%M%S')}"
    acquire_cycle_lock(cycle_id)
    try:
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "start", "com.kis.autoimplement",
        )
        await proc.wait()
        return f"🚀 사이클 발동: {cycle_id} (launchctl start 호출)"
    finally:
        # 실제 사이클 lock은 run_auto_implement.sh가 진입 시 다시 잡고 끝나면 release.
        # 본 함수는 launchctl 호출 완료 후 즉시 lock을 풀어 다음 발동이 가능하도록 한다.
        release_cycle_lock()


async def cmd_pause_implement(args: str) -> str:
    if args.strip() in ("resume", "off"):
        set_paused(False)
        return "▶️ 하네스 재개 (pause lock 제거)"
    set_paused(True)
    return "⏸️ 하네스 일시 중단 (pause lock 설치 — 자동/수동 트리거 모두 차단)"


async def cmd_status_implement(args: str) -> str:
    lines = ["🛠 하네스 상태"]
    lines.append(f"  paused: {'YES' if paused() else 'no'}")
    progress_path = Path.home() / ".kis-autotrader" / "claude-progress.json"
    cp = load_progress(progress_path)
    if cp is None:
        lines.append("  현재 사이클: 없음")
    else:
        lines.append(f"  현재 사이클: {cp.cycle_id} (started_at={cp.started_at.isoformat()})")
        lines.append(f"  pending={len(cp.pending)} in_flight={len(cp.in_flight)}")
        lines.append(f"  completed={len(cp.completed)} failed={len(cp.failed)}")
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_notify/test_harness_commands.py -v
```
Expected: `3 passed`

- [ ] **Step 5: ruff/mypy**

```bash
.venv/bin/ruff check src/harness/telegram_commands.py tests/test_notify/test_harness_commands.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/telegram_commands.py
```

- [ ] **Step 6: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/telegram_commands.py tests/test_notify/test_harness_commands.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): Telegram run/pause/status_implement 명령 + TDD (Phase 1 T10)"
```

---

## Task 11: `main.py`에 새 명령 등록

**Files:**
- Modify: `main.py` (Line 535 근처, `bot.register("help", cmd_help)` 직전)

- [ ] **Step 1: 핸들러 import + 등록**

`main.py`의 기존 import 영역에 추가:

```python
from src.harness.telegram_commands import (
    cmd_pause_implement,
    cmd_run_implement,
    cmd_status_implement,
)
```

`bot.register("help", cmd_help)` 라인 직전에 다음 3줄 삽입:

```python
    bot.register("run_implement", cmd_run_implement)
    bot.register("status_implement", cmd_status_implement)
    bot.register("pause_implement", cmd_pause_implement)
```

- [ ] **Step 2: import 확인**

```bash
PYTHONPATH=. .venv/bin/python -c "import main; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: ruff/mypy**

```bash
.venv/bin/ruff check main.py
PYTHONPATH=. .venv/bin/python -m mypy --strict main.py 2>&1 | tail -5
```
> **참고:** main.py가 기존 mypy strict 통과 상태라면 새 3줄도 통과. 기존 위반 있는 상태였으면 본 단계는 신규 줄에 한정해 검사.

- [ ] **Step 4: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add main.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(main): Telegram /run_implement /status_implement /pause_implement 등록 (Phase 1 T11)"
```

---

## Task 12: `run_auto_implement.sh`에 pause lock 가드 추가

**Files:**
- Modify: `scripts/run_auto_implement.sh` (스크립트 시작부)

- [ ] **Step 1: pause lock 체크 삽입**

`scripts/run_auto_implement.sh`의 `set -euo pipefail` 직후, `export HOME=...` 직전에 삽입:

```bash
# 하네스 pause lock 체크 (Phase 1)
PAUSE_LOCK="${HARNESS_PAUSE_LOCK_PATH:-$HOME/.kis-autotrader/harness-paused}"
if [[ -f "$PAUSE_LOCK" ]]; then
  echo "[auto-implement] paused (lock=$PAUSE_LOCK) — skip cycle at $(date)" >> "${LOG_FILE:-/tmp/auto_implement.log}"
  exit 0
fi
```

> **순서 주의:** `LOG_FILE` 변수가 위 코드 시점에서 미정의이므로 `:-/tmp/auto_implement.log` fallback 필수.

- [ ] **Step 2: 동작 확인**

```bash
touch ~/.kis-autotrader/harness-paused
HARNESS_PAUSE_LOCK_PATH=$HOME/.kis-autotrader/harness-paused bash scripts/run_auto_implement.sh || echo "exit=$?"
cat /tmp/auto_implement.log | tail -3
rm ~/.kis-autotrader/harness-paused
```
Expected: `[auto-implement] paused ... — skip cycle` + exit 0

- [ ] **Step 3: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/run_auto_implement.sh
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): run_auto_implement.sh pause lock 가드 (Phase 1 T12)"
```

---

## Task 13: Phase 1 통합 검증

**Files:** 없음 (read-only 검증)

- [ ] **Step 1: 전체 pytest**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q
```
Expected: 모든 신규 테스트(35+ 케이스) 통과 + 기존 테스트 변동 없음 (Phase 0의 사전 존재 1건 실패는 유지 가능)

- [ ] **Step 2: 전체 ruff**

```bash
.venv/bin/ruff check src/ scripts/harness/ scripts/claude-hooks/ tests/test_harness/ tests/test_notify/test_harness_commands.py
```
Expected: `All checks passed!`

- [ ] **Step 3: 전체 mypy (신규 모듈)**

```bash
PYTHONPATH=. .venv/bin/python -m mypy --strict \
  src/harness/ \
  scripts/harness/sync_proposals_md_to_db.py \
  scripts/claude-hooks/run_hook.py
```
Expected: `Success: no issues found`

- [ ] **Step 4: Phase 1 게이트 확인 (phase0_baseline.md §4)**

| 지표 | 목표 | 본 plan 충족 위치 |
|------|------|------------------|
| DTZ/B/S 신규 위반 | 0 | Phase 0 룰셋(이미 활성) + pre-commit hook(미설치) |
| `proposals` 상태 머신 sole source | DB | T1~T4 |
| `failed` DB 적재 | 100% (신규부터) | T3의 `mark_failed` |
| `changed_files` JSONB | 100% (신규부터) | 본 plan 범위 밖 — Phase 2 Verifier가 채움 |
| 수동 트리거 표준 채널 | Telegram 3개 + CLI 1개 | T9~T11 |
| Initializer `claude-progress.json` | 매 사이클 생성 | T5 스키마 + 사이클 진입 wiring은 Phase 2 |

> **남는 항목 (Phase 2로 이관)**: `changed_files` JSONB 자동 채움, Initializer가 실제 사이클 시작 시 progress.json 생성, Verifier 서브에이전트 분리.

- [ ] **Step 5: 베이스라인 baseline_kpis 재실행해 변화 확인**

```bash
PYTHONPATH=. .venv/bin/python -m scripts.harness.baseline_kpis \
  --out docs/harness/phase1_baseline.json --days 90
```
Expected: 제안서 37건 모두 `state_distribution`에 정확한 분포로 반영 (markdown parser 기반이라 동일하지만, T4 동기화 이후로는 향후 DB 기반 KPI 측정 모듈로 교체 가능).

- [ ] **Step 6: Phase 1 완료 리포트**

`docs/harness/phase1_completion.md`에 다음 섹션 포함:
- 본 plan의 13개 task 체크리스트 결과
- 게이트 §4 통과 여부
- Phase 2로 이관된 항목과 그 사유
- 운영 가이드: pause lock 사용법, /run_implement 사용법

- [ ] **Step 7: 최종 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add docs/harness/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "docs(harness): Phase 1 완료 리포트 (Phase 1 T13)"
```

---

## 운영 재개 절차 (모든 task 완료 후)

```bash
# pause lock 제거 (있다면)
rm -f ~/.kis-autotrader/harness-paused

# autotrader, watchdog, autoimplement 재로드
launchctl load ~/Library/LaunchAgents/com.kis.autotrader.plist
launchctl load ~/Library/LaunchAgents/com.kis.watchdog.plist
launchctl load ~/Library/LaunchAgents/com.kis.autoimplement.plist

# 동작 확인
launchctl list | grep kis
```

`.claude/settings.json`은 **워크트리에 한정 적용** — 메인 repo로 머지할지 여부는 머지 PR 시점에 사용자가 결정.
