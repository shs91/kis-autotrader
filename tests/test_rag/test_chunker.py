"""Chunker (source_type별 청킹 전략) 단위 테스트.

Phase 2b — 본문을 임베딩 친화적 chunk로 분할.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.db.models import NewsSourceType
from src.rag.chunker import (
    Chunk,
    DisclosureChunker,
    NewsChunker,
    RawDocument,
    get_chunker,
)


def _doc(
    source_type: NewsSourceType = NewsSourceType.NEWS,
    title: str | None = "기본 제목",
    body: str = "기본 본문",
) -> RawDocument:
    return RawDocument(
        ticker="005930",
        source_type=source_type,
        source_id="20260518000001",
        title=title,
        body=body,
        event_time=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
    )


class TestRawDocumentDataclass:
    def test_required_fields(self) -> None:
        doc = _doc()
        assert doc.ticker == "005930"
        assert doc.source_type == NewsSourceType.NEWS
        assert doc.event_time.tzinfo is not None


class TestChunkDataclass:
    def test_fields(self) -> None:
        c = Chunk(text="x", chunk_index=0, section="lead")
        assert c.text == "x"
        assert c.chunk_index == 0
        assert c.section == "lead"


class TestNewsChunker:
    def test_short_body_produces_lead_plus_body(self) -> None:
        """짧은 본문: 제목+리드(첫 2문단)와 본문이 분리된 청크 2개."""
        body = (
            "삼성전자는 2026년 3분기 영업이익 8조원을 발표했다. 시장 예상치를 상회한다.\n\n"
            "메모리 부문이 호조를 보였다. HBM3E 출하가 전년 대비 70% 증가했다.\n\n"
            "비메모리 부문은 부진했다. 파운드리 가동률 회복이 더디다."
        )
        chunks = NewsChunker().chunk(_doc(body=body))
        assert len(chunks) >= 2
        # 첫 청크는 제목+리드
        assert "기본 제목" in chunks[0].text
        assert "8조원" in chunks[0].text  # 첫 문단 포함
        assert chunks[0].chunk_index == 0
        # 마지막 청크는 본문 일부
        assert any("비메모리" in c.text for c in chunks[1:])

    def test_chunk_indexes_sequential(self) -> None:
        body = "p1\n\np2\n\np3\n\np4\n\np5"
        chunks = NewsChunker().chunk(_doc(body=body))
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_empty_body_returns_lead_only(self) -> None:
        chunks = NewsChunker().chunk(_doc(body=""))
        assert len(chunks) == 1
        assert "기본 제목" in chunks[0].text

    def test_no_title_uses_body_only(self) -> None:
        body = "본문이 시작된다. 두 번째 문장.\n\n두 번째 문단이다."
        chunks = NewsChunker().chunk(_doc(title=None, body=body))
        assert len(chunks) >= 1
        # 첫 청크는 리드(본문 처음)부터 시작
        assert "본문이 시작" in chunks[0].text

    def test_long_body_uses_sliding_window(self) -> None:
        """본문이 chunk_size를 초과하면 슬라이딩 윈도우로 분할된다."""
        # 2000자 본문 (chunk_size 1500 초과)
        long_body = ("문장. " * 500)
        chunker = NewsChunker(chunk_size=1500, overlap=300)
        chunks = chunker.chunk(_doc(body=long_body))
        # 제목+리드 1개 + 본문 슬라이딩 N개
        assert len(chunks) >= 2
        # 모든 청크는 chunk_size 이내
        assert all(len(c.text) <= 1500 + 100 for c in chunks)  # 약간의 여유

    def test_empty_title_and_body_returns_empty(self) -> None:
        chunks = NewsChunker().chunk(_doc(title=None, body=""))
        assert chunks == []


class TestDisclosureChunker:
    def test_short_disclosure_single_chunk(self) -> None:
        doc = _doc(
            source_type=NewsSourceType.DISCLOSURE,
            title="주요사항보고서(자기주식취득결정)",
            body="삼성전자는 자기주식 100만주 취득을 결의했다.",
        )
        chunks = DisclosureChunker().chunk(doc)
        assert len(chunks) == 1
        assert "자기주식" in chunks[0].text
        assert chunks[0].chunk_index == 0

    def test_long_disclosure_splits(self) -> None:
        doc = _doc(
            source_type=NewsSourceType.DISCLOSURE,
            title="감사보고서",
            body="감사 의견은 다음과 같다. " * 200,
        )
        chunks = DisclosureChunker(chunk_size=1000, overlap=200).chunk(doc)
        assert len(chunks) >= 2

    def test_empty_disclosure_returns_empty(self) -> None:
        chunks = DisclosureChunker().chunk(_doc(
            source_type=NewsSourceType.DISCLOSURE, title=None, body="",
        ))
        assert chunks == []


class TestGetChunker:
    def test_returns_news_chunker_for_news(self) -> None:
        assert isinstance(get_chunker(NewsSourceType.NEWS), NewsChunker)

    def test_returns_disclosure_chunker_for_disclosure(self) -> None:
        assert isinstance(
            get_chunker(NewsSourceType.DISCLOSURE), DisclosureChunker
        )

    def test_earnings_and_report_use_disclosure_fallback(self) -> None:
        """EARNINGS/REPORT는 Phase 3에서 정교화. 현재는 Disclosure와 동일 fallback."""
        assert isinstance(
            get_chunker(NewsSourceType.EARNINGS), DisclosureChunker
        )
        assert isinstance(
            get_chunker(NewsSourceType.REPORT), DisclosureChunker
        )
