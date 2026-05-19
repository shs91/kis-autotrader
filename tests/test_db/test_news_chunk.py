"""NewsChunk / NewsCollectionState 모델 테스트.

Phase 1a — DB 스키마 단위 검증.
- 모델 인스턴스 생성·읽기
- NewsSourceType enum
- UniqueConstraint(ticker, content_hash)
- timezone-aware 강제 (CHANGELOG 2026-05-13 회귀 방지)
- 정정공시 체인 (corr_source_id)

Vector 컬럼은 SQLite로 의미있는 검증 불가 → pgvector 통합 테스트는 별도.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, NewsChunk, NewsCollectionState, NewsSourceType
from src.db.session import validate_timezone_aware


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    """SQLite in-memory 세션. JSONB→JSON, Vector→TEXT 변환 + timezone listener.

    pgvector의 Vector 타입은 SQLite에 없으므로 TEXT로 폴백한다. 차원 검증과
    유사도 쿼리는 SQLite에서 의미가 없으므로 통합 테스트(PG)로 분리한다.
    """
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


def _embedding_stub() -> list[float]:
    """SQLite 폴백에서는 차원 검증이 없으므로 임의 길이 허용."""
    return [0.0] * 1024


class TestNewsSourceType:
    """NewsSourceType enum 정의 확인."""

    def test_has_four_source_types(self) -> None:
        assert {e.value for e in NewsSourceType} == {
            "disclosure",
            "news",
            "earnings",
            "report",
        }


class TestNewsChunkModel:
    """NewsChunk 모델 인스턴스 생성·필드 접근."""

    def test_create_minimal_chunk(self, session: Session) -> None:
        chunk = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.DISCLOSURE,
            source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260518000001",
            source_id="20260518000001",
            title="주요사항보고서(자기주식취득결정)",
            chunk_text="삼성전자는 2026-05-18 이사회에서 자기주식 100만주 취득을 결의...",
            chunk_index=0,
            content_hash="a" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 16, 30, tzinfo=UTC),
            chunk_metadata={"category": "주요사항"},
        )
        session.add(chunk)
        session.commit()

        assert chunk.id is not None
        assert chunk.ticker == "005930"
        assert chunk.source_type == NewsSourceType.DISCLOSURE
        assert chunk.chunk_index == 0
        assert chunk.fetched_at is not None
        assert chunk.created_at is not None
        # corr_source_id는 평소 None
        assert chunk.corr_source_id is None

    def test_corr_source_id_for_correction(self, session: Session) -> None:
        """정정공시는 corr_source_id로 원본 공시를 가리킨다."""
        original = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.DISCLOSURE,
            source_id="20260518000001",
            chunk_text="원본 공시 본문",
            chunk_index=0,
            content_hash="o" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        )
        correction = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.DISCLOSURE,
            source_id="20260519000007",
            corr_source_id="20260518000001",
            chunk_text="정정공시 본문",
            chunk_index=0,
            content_hash="c" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 19, 11, 0, tzinfo=UTC),
        )
        session.add_all([original, correction])
        session.commit()

        # 원본을 corr_source_id로 역추적
        from sqlalchemy import select
        rows = session.scalars(
            select(NewsChunk).where(NewsChunk.corr_source_id == "20260518000001")
        ).all()
        assert len(rows) == 1
        assert rows[0].source_id == "20260519000007"


class TestNewsChunkUniqueConstraint:
    """UniqueConstraint(ticker, content_hash) — 중복 적재 차단."""

    def test_duplicate_ticker_content_hash_rejected(self, session: Session) -> None:
        c1 = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.NEWS,
            chunk_text="삼성전자 기사 본문",
            chunk_index=0,
            content_hash="x" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        )
        session.add(c1)
        session.commit()

        c2 = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.NEWS,
            chunk_text="삼성전자 기사 본문",  # 같은 ticker + 같은 hash
            chunk_index=0,
            content_hash="x" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 9, 1, tzinfo=UTC),
        )
        session.add(c2)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_same_hash_different_ticker_allowed(self, session: Session) -> None:
        """동일 hash라도 ticker가 다르면 OK (시장전반 기사가 여러 종목에 매칭 가능)."""
        common_text = "한국은행 기준금리 동결"
        c1 = NewsChunk(
            ticker="MARKET",
            source_type=NewsSourceType.NEWS,
            chunk_text=common_text,
            chunk_index=0,
            content_hash="m" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        )
        c2 = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.NEWS,
            chunk_text=common_text,
            chunk_index=0,
            content_hash="m" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        )
        session.add_all([c1, c2])
        session.commit()
        assert c1.id != c2.id


class TestNewsChunkTimezoneAware:
    """validate_timezone_aware listener — naive event_time / fetched_at 차단."""

    def test_naive_event_time_rejected(self, session: Session) -> None:
        chunk = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.NEWS,
            chunk_text="x",
            chunk_index=0,
            content_hash="t" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 9, 0),  # naive — 차단되어야 함
        )
        session.add(chunk)
        with pytest.raises(ValueError, match="Naive datetime"):
            session.flush()

    def test_naive_fetched_at_rejected(self, session: Session) -> None:
        chunk = NewsChunk(
            ticker="005930",
            source_type=NewsSourceType.NEWS,
            chunk_text="x",
            chunk_index=0,
            content_hash="f" * 64,
            embedding=_embedding_stub(),
            event_time=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 5, 18, 9, 5),  # naive — 차단되어야 함
        )
        session.add(chunk)
        with pytest.raises(ValueError, match="Naive datetime"):
            session.flush()


class TestNewsCollectionState:
    """소스별 마지막 수집 시각 상태 추적."""

    def test_upsert_state(self, session: Session) -> None:
        state = NewsCollectionState(
            source_name="dart",
            last_collected_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
            last_cursor="20260518000010",
        )
        session.add(state)
        session.commit()

        # 동일 source_name 재조회 + 갱신
        fetched = session.get(NewsCollectionState, "dart")
        assert fetched is not None
        assert fetched.last_cursor == "20260518000010"

        fetched.last_collected_at = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
        fetched.last_cursor = "20260518000020"
        session.commit()

        again = session.get(NewsCollectionState, "dart")
        assert again is not None
        assert again.last_cursor == "20260518000020"
