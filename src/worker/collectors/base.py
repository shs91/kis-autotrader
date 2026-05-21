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
from src.db.repository import SystemMetricRepository
from src.db.session import get_session
from src.rag.chunker import Chunk, RawDocument, get_chunker
from src.rag.scorer import get_scorer
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.db.repository import NewsChunkRepository
    from src.rag.embedder import Embedder
    from src.rag.scorer import Scorer

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
        metric_repo: SystemMetricRepository | None = None,
        scorer: Scorer | None = None,
    ) -> None:
        self._embedder = embedder
        self._repo = repo
        self._metric_repo = metric_repo
        self._scorer = scorer or get_scorer()

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
            self._record_metric(
                docs=0, inserted=0, elapsed_ms=elapsed_ms, error=str(e),
            )
            return CollectionResult(
                source_name=self.source_name,
                documents_fetched=0,
                chunks_inserted=0,
                elapsed_ms=elapsed_ms,
                error=str(e),
            )

        chunks = self._build_new_chunks(docs)
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
        self._record_metric(
            docs=len(docs), inserted=inserted, elapsed_ms=elapsed_ms,
        )
        return CollectionResult(
            source_name=self.source_name,
            documents_fetched=len(docs),
            chunks_inserted=inserted,
            elapsed_ms=elapsed_ms,
        )

    def _record_metric(
        self, docs: int, inserted: int, elapsed_ms: int, error: str | None = None,
    ) -> None:
        """사이클 종료 시 NEWS_COLLECTED 메트릭 1건 기록.

        worker가 들고 있는 장기 session 대신 별도 get_session() 컨텍스트로 매
        사이클마다 commit 보장. (worker의 session은 무한 루프라 컨텍스트 종료
        시점이 없어 metric flush가 commit되지 않는다.) metric_repo는 enable
        flag 역할만 한다.
        """
        if self._metric_repo is None:
            return
        detail: dict[str, object] = {
            "source": self.source_name,
            "documents": docs,
            "chunks_inserted": inserted,
            "elapsed_ms": elapsed_ms,
        }
        if error is not None:
            detail["error"] = error
        try:
            with get_session() as session:
                SystemMetricRepository(session).record_metric("NEWS_COLLECTED", detail)
        except Exception:  # noqa: BLE001 — 메트릭 기록 실패가 사이클 결과 막지 않음
            logger.exception("NEWS_COLLECTED 메트릭 기록 실패 (%s)", self.source_name)

    def _build_new_chunks(self, docs: list[RawDocument]) -> list[NewsChunk]:
        """doc을 chunk로 분할 → 중복 제거 → **신규 청크만 임베딩** → NewsChunk 변환.

        `content_hash`는 text만으로 계산 가능하므로 임베딩 전에 (배치 내 +
        DB 적재분) 중복을 거른 뒤, 살아남은 청크에 대해서만 `embedder.encode`를
        호출한다. 과거에는 모든 청크를 임베딩한 뒤 `insert_chunks`에서 버려
        컴퓨트가 낭비됐다.
        """
        if not docs:
            return []

        # 1) 모든 doc을 chunk로 분할 + content_hash 계산 (임베딩 없음)
        triples: list[tuple[RawDocument, Chunk, str]] = []
        for doc in docs:
            chunker = get_chunker(doc.source_type)
            for chunk in chunker.chunk(doc):
                content_hash = _content_hash(
                    doc.ticker, doc.source_id, chunk.chunk_index, chunk.text,
                )
                triples.append((doc, chunk, content_hash))
        if not triples:
            return []

        # 2) 배치 내 (ticker, content_hash) 중복 제거 — 첫 항목 유지
        seen: set[tuple[str, str]] = set()
        deduped: list[tuple[RawDocument, Chunk, str]] = []
        for doc, chunk, content_hash in triples:
            key = (doc.ticker, content_hash)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((doc, chunk, content_hash))

        # 3) 이미 DB에 적재된 키 제외 (단일 쿼리)
        existing = self._repo.existing_keys([(d.ticker, h) for d, _, h in deduped])
        survivors = [t for t in deduped if (t[0].ticker, t[2]) not in existing]
        if not survivors:
            return []

        # 4) 신규 청크만 일괄 임베딩 (배치 사이즈는 Embedder가 관리)
        vectors = self._embedder.encode([c.text for _, c, _ in survivors])

        # 5) 스코어링 + NewsChunk 생성
        out: list[NewsChunk] = []
        for (doc, chunk, content_hash), vec in zip(survivors, vectors, strict=True):
            score = self._scorer.score(
                chunk.text, doc.source_type, doc.title, doc.metadata,
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
                sentiment=score.sentiment,
                importance=score.importance,
                chunk_metadata={
                    "section": chunk.section,
                    "score_method": score.method,
                    **doc.metadata,
                },
            ))
        return out
