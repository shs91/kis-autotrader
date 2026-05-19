"""notify_cycle_summary.py TDD — Phase 4 wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scripts.harness.notify_cycle_summary import (
    build_message,
    collect_applied,
    collect_prediction_misses,
    collect_recurrence_risks,
)
from src.db.models import (
    Base,
    ImplementationCategory,
    ImplementationLog,
)


@pytest.fixture
def session():
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"

        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


# ── collect_applied ─────────────────────────────────────────────


def test_collect_applied_returns_logs_after_since(session):
    now = datetime.now(UTC)
    older = ImplementationLog(
        title="OLD", category=ImplementationCategory.BUG_FIX,
        implemented_at=now - timedelta(days=2), version="0.1.0",
    )
    recent = ImplementationLog(
        title="NEW", category=ImplementationCategory.PERFORMANCE,
        implemented_at=now - timedelta(hours=1), version="0.1.1",
    )
    session.add_all([older, recent])
    session.flush()

    items = collect_applied(session, since=now - timedelta(hours=12))
    assert items == [{"title": "NEW", "version": "0.1.1"}]


def test_collect_applied_orders_by_implemented_at(session):
    now = datetime.now(UTC)
    a = ImplementationLog(
        title="FIRST", category=ImplementationCategory.BUG_FIX,
        implemented_at=now - timedelta(hours=10), version="0.2.0",
    )
    b = ImplementationLog(
        title="SECOND", category=ImplementationCategory.BUG_FIX,
        implemented_at=now - timedelta(hours=2), version="0.2.1",
    )
    session.add_all([b, a])  # insertion 순서 역전
    session.flush()

    items = collect_applied(session, since=now - timedelta(hours=24))
    assert [i["title"] for i in items] == ["FIRST", "SECOND"]


def test_collect_applied_empty_when_no_logs(session):
    items = collect_applied(session, since=datetime.now(UTC))
    assert items == []


# ── collect_recurrence_risks ────────────────────────────────────


def test_collect_recurrence_risks_returns_components_above_threshold(session):
    now = datetime.now(UTC)
    # 동일 component "code/strategy"를 3건 (min_edits=3)
    for i in range(3):
        session.add(ImplementationLog(
            title=f"L{i}", category=ImplementationCategory.PARAM_TUNING,
            implemented_at=now - timedelta(days=i),
            changed_files={"files": [
                {"path": f"src/strategy/file{i}.py", "component": "code/strategy"},
            ]},
        ))
    session.flush()

    risks = collect_recurrence_risks(session, window_days=7, min_edits=3)
    assert {r["component"] for r in risks} == {"code/strategy"}
    assert risks[0]["edit_count"] == 3


def test_collect_recurrence_risks_below_threshold_empty(session):
    now = datetime.now(UTC)
    session.add(ImplementationLog(
        title="L", category=ImplementationCategory.BUG_FIX,
        implemented_at=now - timedelta(hours=1),
        changed_files={"files": [{"path": "x.py", "component": "code/strategy"}]},
    ))
    session.flush()
    assert collect_recurrence_risks(session, min_edits=3) == []


# ── collect_prediction_misses (Phase 5 자리) ────────────────────


def test_collect_prediction_misses_returns_empty_placeholder(session):
    # Phase 5에서 실측 매핑이 채워지기 전까지는 빈 리스트.
    assert collect_prediction_misses(session) == []


# ── build_message 통합 ─────────────────────────────────────────


def test_build_message_includes_cycle_id_and_applied(session):
    now = datetime.now(UTC)
    session.add(ImplementationLog(
        title="X 적용", category=ImplementationCategory.BUG_FIX,
        implemented_at=now - timedelta(hours=1), version="0.3.0",
    ))
    session.flush()

    msg = build_message(
        cycle_id="auto-20260519-171501",
        session=session,
        since=now - timedelta(hours=24),
    )
    assert "auto-20260519-171501" in msg
    assert "X 적용" in msg
    assert "0.3.0" in msg


def test_build_message_handles_no_data(session):
    msg = build_message(
        cycle_id="auto-empty",
        session=session,
        since=datetime.now(UTC) - timedelta(hours=24),
    )
    assert "auto-empty" in msg
    assert "변경 없음" in msg
    assert "회귀 위험 없음" in msg
    assert "예측 미달 없음" in msg
