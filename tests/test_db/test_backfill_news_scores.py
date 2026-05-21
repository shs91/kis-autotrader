"""backfill_news_scores 동작/idempotency 테스트 (SQLite in-memory)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from scripts.backfill_news_scores import backfill_scores
from src.db.models import Base, NewsChunk, NewsSourceType


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]
    if not hasattr(SQLiteTypeCompiler, "visit_VECTOR"):
        def visit_vector(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "TEXT"
        SQLiteTypeCompiler.visit_VECTOR = visit_vector  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _chunk(hash_seed: str, body: str) -> NewsChunk:
    return NewsChunk(
        ticker="005930",
        source_type=NewsSourceType.NEWS,
        source_id=hash_seed,
        chunk_text=body,
        chunk_index=0,
        content_hash=(hash_seed * 64)[:64],
        embedding=[0.0] * 1024,
        event_time=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
    )


def test_backfill_fills_null_scores(session: Session) -> None:
    session.add(_chunk("a", "흑자전환 신규수주"))
    session.add(_chunk("b", "정기 주주총회 개최"))
    session.commit()

    updated = backfill_scores(session, batch_size=10)
    assert updated == 2

    rows = session.execute(select(NewsChunk)).scalars().all()
    for r in rows:
        assert r.sentiment is not None
        assert r.importance is not None
        assert r.chunk_metadata["score_method"] == "rule_v1"


def test_backfill_is_idempotent(session: Session) -> None:
    session.add(_chunk("a", "흑자전환"))
    session.commit()
    assert backfill_scores(session, batch_size=10) == 1
    # 재실행 시 NULL이 없으므로 0건
    assert backfill_scores(session, batch_size=10) == 0
