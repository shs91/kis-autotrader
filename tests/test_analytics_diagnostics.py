"""매매 진단 집계(build_daily_diagnostics) 테스트."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.analytics import build_daily_diagnostics
from src.db.models import Base, Stock, SystemMetric

# ── Fixture ────────────────────────────────────────────────


@pytest.fixture()
def session() -> Session:
    """SQLite in-memory 세션 (JSONB→JSON 호환)."""
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):

        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"

        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess  # type: ignore[misc]
    sess.close()
    engine.dispose()


# ── 테스트 ─────────────────────────────────────────────────


def test_build_daily_diagnostics_zero_trades(session: Session) -> None:
    rec = datetime(2026, 6, 8, 12, 0)
    session.add_all(
        [
            Stock(code="027360", name="아주IB투자", market="KOSDAQ"),
            Stock(code="036170", name="에이치엠넥스", market="KOSDAQ"),
            SystemMetric(
                metric_type="EVAL_TARGETS",
                detail={
                    "targets": ["027360", "036170"],
                    "counts": {"positions": 0, "watchlist": 0, "screening": 2},
                },
                recorded_at=rec,
            ),
            SystemMetric(
                metric_type="SIGNAL_SUMMARY", detail={"max_confidence": 0.0}, recorded_at=rec
            ),
            SystemMetric(
                metric_type="SIGNAL_SKIP",
                detail={"stock_code": "027360", "confidence": 0.0, "signal_type": "HOLD"},
                recorded_at=rec,
            ),
            SystemMetric(
                metric_type="SCREENING_CANDIDATE",
                detail={"ranked_total": 30, "candidate_count": 0},
                recorded_at=rec,
            ),
            SystemMetric(
                metric_type="SCREENING_RISK_EXCLUDED",
                detail={"codes": ["271830"]},
                recorded_at=rec,
            ),
        ]
    )
    session.commit()

    diag = build_daily_diagnostics(session, date(2026, 6, 8))

    assert diag["trade_count"] == 0
    assert diag["monitored_counts"]["screening"] == 2
    assert [m["code"] for m in diag["monitored"]] == ["027360", "036170"]
    assert diag["monitored"][0]["name"] == "아주IB투자"
    assert diag["screening"]["ranked_total"] == 30
    assert diag["screening"]["risk_excluded"] == ["271830"]
    assert diag["buy_rejects"] == {}
    assert "매매 0건" in diag["headline"]


def test_build_daily_diagnostics_with_buy_reject(session: Session) -> None:
    rec = datetime(2026, 6, 8, 12, 0)
    session.add(
        SystemMetric(
            metric_type="BUY_REJECT",
            detail={"reason": "DAILY_TRADE_LIMIT", "stock_code": "005880"},
            recorded_at=rec,
        )
    )
    session.commit()

    diag = build_daily_diagnostics(session, date(2026, 6, 8))

    assert diag["buy_rejects"] == {"DAILY_TRADE_LIMIT": 1}
