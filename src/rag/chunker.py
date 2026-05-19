"""source_type별 청킹 전략.

설계 원칙:
- 한 chunk는 BGE-M3 컨텍스트 한계(8192 tokens) 안. 한국어는 토큰 효율이
  낮으므로 char-level 가드(기본 1500자, overlap 300자)로 안전 마진.
- NewsChunker: 제목+리드(첫 2문단)와 본문을 분리하면 RAG retriever가
  핵심 정보만 빠르게 매칭할 수 있다.
- DisclosureChunker: 공시는 본문 자체가 핵심이라 단일 청크로 유지.
  토큰 한계 초과 시에만 슬라이딩 윈도우.

향후 확장 (Phase 3에서 점진):
- DART XBRL 항목별 분리 (DisclosureChunker)
- EARNINGS 사업부문별 / 가이던스 섹션 분리
- REPORT 투자의견 변경 / 핵심 코멘트 분리
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from src.db.models import NewsSourceType

DEFAULT_CHUNK_SIZE = 1500  # 한국어 ~600~700 토큰 추정. 8192 한계 대비 충분.
DEFAULT_OVERLAP = 300


@dataclass
class RawDocument:
    """Collector → Chunker 입력."""

    ticker: str
    source_type: NewsSourceType
    source_id: str
    title: str | None
    body: str
    event_time: datetime
    source_url: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class Chunk:
    """Chunker → Embedder/Repository 입력."""

    text: str
    chunk_index: int
    section: str  # "lead", "body", "disclosure" 등


class Chunker(Protocol):
    """source_type별 청킹 인터페이스."""

    def chunk(self, doc: RawDocument) -> list[Chunk]:
        ...


def _split_sliding(text: str, chunk_size: int, overlap: int) -> list[str]:
    """char-level 슬라이딩 윈도우. 짧으면 1개 그대로 반환."""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    step = chunk_size - overlap
    return [text[i : i + chunk_size] for i in range(0, len(text), step) if i < len(text)]


def _resolve(value: int | None, env_key: str, default: int) -> int:
    if value is not None:
        return value
    raw = os.getenv(env_key)
    return int(raw) if raw else default


class NewsChunker:
    """뉴스: 제목+리드(첫 2문단)와 본문을 분리. 본문이 길면 슬라이딩 분할."""

    def __init__(self, chunk_size: int | None = None, overlap: int | None = None) -> None:
        self._chunk_size = _resolve(chunk_size, "NEWS_CHUNK_SIZE", DEFAULT_CHUNK_SIZE)
        self._overlap = _resolve(overlap, "NEWS_CHUNK_OVERLAP", DEFAULT_OVERLAP)

    def chunk(self, doc: RawDocument) -> list[Chunk]:
        paragraphs = [p.strip() for p in doc.body.split("\n\n") if p.strip()]
        chunks: list[Chunk] = []

        # 리드 청크: 제목 + 첫 2문단. 토큰 한계 초과 시 슬라이딩.
        lead_paragraphs = paragraphs[:2]
        lead_text_parts: list[str] = []
        if doc.title:
            lead_text_parts.append(doc.title)
        lead_text_parts.extend(lead_paragraphs)
        lead_text = "\n\n".join(lead_text_parts).strip()
        for segment in _split_sliding(lead_text, self._chunk_size, self._overlap):
            chunks.append(
                Chunk(text=segment, chunk_index=len(chunks), section="lead")
            )

        # 본문 청크: 리드를 제외한 나머지 문단들
        body_paragraphs = paragraphs[2:]
        body_text = "\n\n".join(body_paragraphs).strip()
        for segment in _split_sliding(body_text, self._chunk_size, self._overlap):
            chunks.append(
                Chunk(text=segment, chunk_index=len(chunks), section="body")
            )

        return chunks


class DisclosureChunker:
    """공시: 본문 전체를 단일 청크. 토큰 한계 초과 시에만 슬라이딩."""

    def __init__(self, chunk_size: int | None = None, overlap: int | None = None) -> None:
        self._chunk_size = _resolve(chunk_size, "NEWS_CHUNK_SIZE", DEFAULT_CHUNK_SIZE)
        self._overlap = _resolve(overlap, "NEWS_CHUNK_OVERLAP", DEFAULT_OVERLAP)

    def chunk(self, doc: RawDocument) -> list[Chunk]:
        # 제목 + 본문을 하나로 연결
        parts: list[str] = []
        if doc.title:
            parts.append(doc.title)
        if doc.body:
            parts.append(doc.body)
        merged = "\n\n".join(parts).strip()
        if not merged:
            return []

        return [
            Chunk(text=segment, chunk_index=i, section="disclosure")
            for i, segment in enumerate(
                _split_sliding(merged, self._chunk_size, self._overlap)
            )
        ]


def get_chunker(source_type: NewsSourceType) -> Chunker:
    """source_type에 맞는 chunker 인스턴스를 반환한다.

    EARNINGS/REPORT는 Phase 3에서 정교화 예정 — 현재는 Disclosure와 동일 fallback.
    """
    if source_type == NewsSourceType.NEWS:
        return NewsChunker()
    return DisclosureChunker()
