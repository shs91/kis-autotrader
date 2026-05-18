"""Prediction calibration TDD."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.analytics import get_prediction_calibration
from src.db.models import (
    Base,
    ImplementationCategory,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository


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


def test_calibration_empty(session: Session) -> None:
    result = get_prediction_calibration(session, window_days=30)
    assert result["proposal_count"] == 0
    assert result["categories"] == {}


def test_calibration_with_predictions(session: Session) -> None:
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
    # no prediction for p3 (BUG_FIX 카테고리)
    repo.create(
        path="c.md", title="C", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
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
