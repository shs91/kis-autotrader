"""NewsChunkRepository 테스트.

Phase 1b — 청크/상태 CRUD + ON CONFLICT 처리.

dialect-portable 패턴 (try/except per chunk)으로 구현하여 SQLite로도
동작. PG에서는 unique 위반 시 같은 흐름.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, NewsChunk, NewsCollectionState, NewsSourceType
from src.db.repository import NewsChunkRepository
from src.db.session import validate_timezone_aware


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
    event.listen(sess, "before_flush", validate_timezone_aware)
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _pad_hash(seed: str) -> str:
    """64자 미만 시드를 반복으로 채워 64자 hash로 만든다."""
    return (seed * (64 // len(seed) + 1))[:64]


def _make_chunk(
    ticker: str = "005930",
    content_hash: str | None = None,
    source_id: str = "20260518000001",
    event_time: datetime | None = None,
) -> NewsChunk:
    return NewsChunk(
        ticker=ticker,
        source_type=NewsSourceType.NEWS,
        source_id=source_id,
        chunk_text=f"기사 본문 {content_hash or 'x'}",
        chunk_index=0,
        content_hash=_pad_hash(content_hash or "h"),
        embedding=[0.0] * 1024,
        event_time=event_time or datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
    )


class TestInsertChunks:
    def test_empty_list_returns_zero(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        assert repo.insert_chunks([]) == 0

    def test_inserts_new_chunks(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        chunks = [
            _make_chunk(content_hash="a"),
            _make_chunk(content_hash="b"),
            _make_chunk(content_hash="c"),
        ]
        inserted = repo.insert_chunks(chunks)
        assert inserted == 3
        rows = session.scalars(select(NewsChunk)).all()
        assert len(rows) == 3

    def test_skips_duplicates_by_content_hash(self, session: Session) -> None:
        """동일 (ticker, content_hash)는 ON CONFLICT처럼 건너뛴다."""
        repo = NewsChunkRepository(session)
        # 1차 적재
        repo.insert_chunks([_make_chunk(content_hash="a"), _make_chunk(content_hash="b")])

        # 2차: 1건 중복 + 2건 신규
        chunks = [
            _make_chunk(content_hash="a"),  # 중복 — skip
            _make_chunk(content_hash="c"),  # 신규
            _make_chunk(content_hash="d"),  # 신규
        ]
        inserted = repo.insert_chunks(chunks)
        assert inserted == 2

        rows = session.scalars(select(NewsChunk)).all()
        assert len(rows) == 4

    def test_same_hash_different_ticker_both_inserted(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        chunks = [
            _make_chunk(ticker="005930", content_hash="m"),
            _make_chunk(ticker="MARKET", content_hash="m"),
        ]
        assert repo.insert_chunks(chunks) == 2

    def test_intra_batch_duplicates_deduped(self, session: Session) -> None:
        """같은 호출 안의 (ticker, content_hash) 중복은 1건만 적재된다."""
        repo = NewsChunkRepository(session)
        chunks = [
            _make_chunk(content_hash="dup"),
            _make_chunk(content_hash="dup"),
            _make_chunk(content_hash="dup"),
        ]
        assert repo.insert_chunks(chunks) == 1
        assert len(session.scalars(select(NewsChunk)).all()) == 1

    def test_large_all_duplicate_rebatch_returns_zero(self, session: Session) -> None:
        """대량 중복 재적재(장 마감 시나리오)는 삽입 없이 0을 반환한다."""
        repo = NewsChunkRepository(session)
        first = [_make_chunk(content_hash=f"h{i}") for i in range(50)]
        assert repo.insert_chunks(first) == 50
        # 동일 배치 재적재 — 전부 중복
        assert repo.insert_chunks(list(first)) == 0
        assert len(session.scalars(select(NewsChunk)).all()) == 50


class TestExistsByHash:
    def test_returns_false_when_absent(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        assert repo.exists_by_hash("005930", "z" * 64) is False

    def test_returns_true_when_present(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        repo.insert_chunks([_make_chunk(content_hash="present")])
        assert repo.exists_by_hash("005930", _pad_hash("present")) is True


class TestExistingKeys:
    def test_empty_keys_returns_empty_set(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        assert repo.existing_keys([]) == set()

    def test_returns_only_present_keys(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        repo.insert_chunks([_make_chunk(content_hash="a"), _make_chunk(content_hash="b")])

        present = (_make_chunk(content_hash="a").ticker, _pad_hash("a"))
        absent = ("005930", _pad_hash("z"))
        result = repo.existing_keys([present, absent])
        assert result == {present}
    def test_get_returns_none_when_absent(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        assert repo.get_collection_state("dart") is None

    def test_update_inserts_when_absent(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        ts = datetime(2026, 5, 18, 9, 0, tzinfo=UTC)
        repo.update_collection_state("dart", ts, cursor="20260518000010")

        state = session.get(NewsCollectionState, "dart")
        assert state is not None
        assert state.last_collected_at == ts
        assert state.last_cursor == "20260518000010"

    def test_update_overrides_existing(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        ts1 = datetime(2026, 5, 18, 9, 0, tzinfo=UTC)
        ts2 = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)

        repo.update_collection_state("dart", ts1, cursor="20260518000010")
        repo.update_collection_state("dart", ts2, cursor="20260518000020")

        state = session.get(NewsCollectionState, "dart")
        assert state is not None
        assert state.last_collected_at == ts2
        assert state.last_cursor == "20260518000020"

    def test_get_returns_last_collected_at(self, session: Session) -> None:
        repo = NewsChunkRepository(session)
        ts = datetime(2026, 5, 18, 9, 0, tzinfo=UTC)
        repo.update_collection_state("rss", ts, cursor=None)

        last = repo.get_collection_state("rss")
        assert last == ts
