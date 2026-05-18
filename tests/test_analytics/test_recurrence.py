"""재발 위험 집계 TDD — 같은 component를 7일 내 N회 수정한 케이스."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.analytics import get_recurrence_risk
from src.db.models import Base, ImplementationCategory, ImplementationLog


@pytest.fixture
def session() -> Iterator[Session]:
    """SQLite in-memory 세션 (JSONB → JSON 폴백)."""
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


def _log(session: Session, days_ago: int, paths: list[str]) -> None:
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


def test_no_recurrence(session: Session) -> None:
    _log(session, days_ago=0, paths=["src/strategy/rsi.py"])
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=2)
    assert result["risk_components"] == []
    assert result["risk_files"] == []


def test_detects_3_edits_in_window(session: Session) -> None:
    for d in (0, 2, 5):
        _log(session, days_ago=d, paths=["src/strategy/rsi.py"])
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=3)
    files = {r["path"]: r for r in result["risk_files"]}
    assert "src/strategy/rsi.py" in files
    assert files["src/strategy/rsi.py"]["edit_count"] == 3


def test_groups_by_component(session: Session) -> None:
    _log(session, days_ago=0, paths=["src/strategy/rsi.py"])
    _log(session, days_ago=2, paths=["src/strategy/macd.py"])
    _log(session, days_ago=5, paths=["src/strategy/ensemble.py"])
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=3)
    comps = {r["component"]: r for r in result["risk_components"]}
    assert comps["code/strategy"]["edit_count"] == 3


def test_excludes_outside_window(session: Session) -> None:
    _log(session, days_ago=0, paths=["src/x.py"])
    _log(session, days_ago=10, paths=["src/x.py"])  # 윈도우 밖
    session.commit()
    result = get_recurrence_risk(session, window_days=7, min_edits=2)
    assert result["risk_files"] == []
