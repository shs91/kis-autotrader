"""Collector 추상 베이스 + 공통 run_cycle 흐름.

각 source-specific collector (DART/RSS 등)는 `collect(since)`만 구현하면
chunking → embedding → DB 적재 → state 갱신이 일관되게 처리된다.
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.db.models import NewsChunk
from src.rag.chunker import Chunk, RawDocument, get_chunker
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.db.repository import NewsChunkRepository
    from src.rag.embedder import Embedder

logger = setup_logger(__name__)

# state가 없는 첫 사이클에서 since로 사용할 lookback.
DEFAULT_LOOKBACK_HOURS = 24


@dataclass
class CollectionResult:
    """한 사이클 결과 요약 — 모니터링/리포트용."""

    source_name: str
    documents_fetched: int
    chunks_inserted: int
    elapsed_ms: int
    error: str | None = None


def _content_hash(ticker: str, source_id: str | None, chunk_index: int, text: str) -> str:
    """청크의 sha256 hash. (ticker, content_hash) unique 제약과 짝."""
    h = hashlib.sha256()
    h.update(ticker.encode("utf-8"))
    h.update(b"\x00")
    h.update((source_id or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(str(chunk_index).encode("utf-8"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


class BaseCollector(ABC):
    """수집 사이클의 공통 흐름.

    하위 클래스는 `collect(since)`와 `source_name`만 구현하면 된다.
    한 RawDocument는 단일 ticker에 매핑되며 — 본문에서 여러 종목이 매칭되는
    RSS의 경우 collector가 매칭 결과별로 doc을 복제해 반환한다.
    """

    source_name: str = "base"  # subclass에서 override

    def __init__(
        self,
        embedder: Embedder,
        repo: NewsChunkRepository,
    ) -> None:
        self._embedder = embedder
        self._repo = repo

    @abstractmethod
    async def collect(self, since: datetime) -> list[RawDocument]:
        """`since` 이후의 신규 문서를 반환한다."""

    async def run_cycle(self) -> CollectionResult:
        """1) state 조회 → 2) collect → 3) chunk → 4) embed → 5) insert → 6) state 갱신."""
        start = time.monotonic()
        since = self._repo.get_collection_state(self.source_name) or (
            datetime.now(UTC).replace(microsecond=0)
            - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
        )

        try:
            docs = await self.collect(since)
        except Exception as e:  # noqa: BLE001 — collector 실패는 사이클 단위로 격리
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.exception("collect 실패: %s", self.source_name)
            return CollectionResult(
                source_name=self.source_name,
                documents_fetched=0,
                chunks_inserted=0,
                elapsed_ms=elapsed_ms,
                error=str(e),
            )

        chunks = self._build_chunks(docs)
        inserted = self._repo.insert_chunks(chunks) if chunks else 0

        # 수집 결과가 있을 때만 state 갱신 — 비면 다음 사이클에서 같은 since로 재시도.
        if docs:
            self._repo.update_collection_state(
                self.source_name,
                datetime.now(UTC),
                cursor=None,
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "사이클 완료 %s: docs=%d chunks=%d elapsed=%dms",
            self.source_name, len(docs), inserted, elapsed_ms,
        )
        return CollectionResult(
            source_name=self.source_name,
            documents_fetched=len(docs),
            chunks_inserted=inserted,
            elapsed_ms=elapsed_ms,
        )

    def _build_chunks(self, docs: list[RawDocument]) -> list[NewsChunk]:
        """모든 doc을 chunker → embedder → NewsChunk 변환."""
        if not docs:
            return []

        # 1) 모든 doc을 chunk로 분할 + (doc, chunk) 페어 유지
        pairs: list[tuple[RawDocument, Chunk]] = []
        for doc in docs:
            chunker = get_chunker(doc.source_type)
            for chunk in chunker.chunk(doc):
                pairs.append((doc, chunk))
        if not pairs:
            return []

        # 2) 일괄 임베딩 (배치 사이즈는 Embedder가 관리)
        texts = [c.text for _, c in pairs]
        vectors = self._embedder.encode(texts)

        # 3) NewsChunk 생성
        out: list[NewsChunk] = []
        for (doc, chunk), vec in zip(pairs, vectors, strict=True):
            content_hash = _content_hash(
                doc.ticker, doc.source_id, chunk.chunk_index, chunk.text,
            )
            out.append(NewsChunk(
                ticker=doc.ticker,
                source_type=doc.source_type,
                source_url=doc.source_url,
                source_id=doc.source_id,
                title=doc.title,
                chunk_text=chunk.text,
                chunk_index=chunk.chunk_index,
                content_hash=content_hash,
                embedding=vec.tolist(),
                event_time=doc.event_time,
                chunk_metadata={"section": chunk.section, **doc.metadata},
            ))
        return out
