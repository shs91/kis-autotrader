"""BaseCollector.run_cycle 흐름 테스트.

collect()는 추상이라 테스트용 stub Collector를 만들고, embedder/repo는 mock한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.db.models import NewsSourceType
from src.rag.chunker import RawDocument
from src.worker.collectors.base import BaseCollector, CollectionResult


class StubCollector(BaseCollector):
    """테스트 전용: collect()가 미리 정한 docs를 반환."""

    source_name = "stub"

    def __init__(
        self,
        embedder: MagicMock,
        repo: MagicMock,
        docs: list[RawDocument],
        metric_repo: MagicMock | None = None,
        scorer: object | None = None,
    ) -> None:
        super().__init__(
            embedder=embedder, repo=repo, metric_repo=metric_repo, scorer=scorer,
        )
        self._docs = docs

    async def collect(self, since: datetime) -> list[RawDocument]:
        return self._docs


def _doc(
    ticker: str = "005930",
    source_id: str = "id-1",
    body: str = "삼성전자 영업이익 발표",
) -> RawDocument:
    return RawDocument(
        ticker=ticker,
        source_type=NewsSourceType.NEWS,
        source_id=source_id,
        title="제목",
        body=body,
        event_time=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
    )


def _mock_embedder(dim: int = 1024) -> MagicMock:
    e = MagicMock()
    # 입력 텍스트 개수에 맞춰 (N, dim) 반환
    e.encode.side_effect = lambda texts, **kw: np.zeros((len(texts), dim), dtype=np.float32)
    return e


def _mock_repo(prev_state: datetime | None = None) -> MagicMock:
    r = MagicMock()
    r.get_collection_state.return_value = prev_state
    r.insert_chunks.side_effect = lambda chunks: len(chunks)
    # 기본: 기존 키 없음 (모든 청크 신규) — 실제 set 반환해야 `in` 판정 가능
    r.existing_keys.return_value = set()
    return r


@pytest.mark.asyncio
class TestRunCycle:
    async def test_empty_docs_returns_zero_inserted(self) -> None:
        repo = _mock_repo()
        collector = StubCollector(_mock_embedder(), repo, docs=[])
        result = await collector.run_cycle()
        assert isinstance(result, CollectionResult)
        assert result.source_name == "stub"
        assert result.documents_fetched == 0
        assert result.chunks_inserted == 0
        repo.insert_chunks.assert_not_called()

    async def test_uses_state_as_since(self) -> None:
        prev = datetime(2026, 5, 17, 0, 0, tzinfo=UTC)
        repo = _mock_repo(prev_state=prev)
        collector = StubCollector(_mock_embedder(), repo, docs=[_doc()])

        captured_since: list[datetime] = []
        original_collect = collector.collect

        async def spy_collect(since: datetime) -> list[RawDocument]:
            captured_since.append(since)
            return await original_collect(since)

        collector.collect = spy_collect  # type: ignore[method-assign]
        await collector.run_cycle()
        assert captured_since == [prev]

    async def test_pipelines_docs_through_chunker_embedder_repo(self) -> None:
        repo = _mock_repo()
        embedder = _mock_embedder()
        docs = [_doc(source_id="a"), _doc(source_id="b", body="다른 본문")]
        collector = StubCollector(embedder, repo, docs=docs)

        result = await collector.run_cycle()
        # 임베딩 호출 1회 (전체 chunk 일괄)
        assert embedder.encode.call_count >= 1
        # insert_chunks 호출됨, 0보다 큰 결과
        assert repo.insert_chunks.call_count == 1
        chunks_arg = repo.insert_chunks.call_args.args[0]
        assert len(chunks_arg) > 0
        assert result.chunks_inserted == len(chunks_arg)
        assert result.documents_fetched == 2

    async def test_updates_collection_state_after_success(self) -> None:
        repo = _mock_repo()
        collector = StubCollector(_mock_embedder(), repo, docs=[_doc()])
        await collector.run_cycle()
        repo.update_collection_state.assert_called_once()
        args = repo.update_collection_state.call_args
        assert args.args[0] == "stub"
        # last_time은 aware datetime
        last_time = args.args[1]
        assert isinstance(last_time, datetime)
        assert last_time.tzinfo is not None

    async def test_skips_state_update_on_empty_collect(self) -> None:
        """수집 결과가 비면 state 갱신을 건너뛴다 — 다음 사이클에서 같은 since로 재시도."""
        repo = _mock_repo()
        collector = StubCollector(_mock_embedder(), repo, docs=[])
        await collector.run_cycle()
        repo.update_collection_state.assert_not_called()

    async def test_content_hash_is_stable_and_unique_per_chunk(self) -> None:
        repo = _mock_repo()
        collector = StubCollector(_mock_embedder(), repo, docs=[_doc()])
        await collector.run_cycle()
        chunks = repo.insert_chunks.call_args.args[0]
        hashes = {c.content_hash for c in chunks}
        # 동일 doc 내에서 chunk별로 hash 다름 + 64자
        assert len(hashes) == len(chunks)
        assert all(len(h) == 64 for h in hashes)

    async def test_chunks_get_sentiment_importance_and_method(self) -> None:
        repo = _mock_repo()
        # 호재 키워드 포함 본문 → sentiment > 0
        docs = [_doc(body="삼성전자 흑자전환 신규수주 사상최대 실적")]
        collector = StubCollector(_mock_embedder(), repo, docs=docs)
        await collector.run_cycle()

        chunks = repo.insert_chunks.call_args.args[0]
        assert len(chunks) > 0
        for c in chunks:
            assert c.sentiment is not None
            assert -1.0 <= c.sentiment <= 1.0
            assert c.importance is not None
            assert 0.0 <= c.importance <= 1.0
            assert c.chunk_metadata["score_method"] == "rule_v1"
        # 호재 본문이므로 양수 sentiment
        assert chunks[0].sentiment > 0

    async def test_negative_keyword_body_yields_negative_sentiment(self) -> None:
        repo = _mock_repo()
        docs = [_doc(body="횡령 혐의 압수수색, 영업손실 적자전환")]
        collector = StubCollector(_mock_embedder(), repo, docs=docs)
        await collector.run_cycle()
        chunks = repo.insert_chunks.call_args.args[0]
        assert chunks[0].sentiment < 0


@pytest.mark.asyncio
class TestEmbedOnlyNewChunks:
    """중복 판정을 임베딩 *앞단*에서 수행 — 이미 적재된 청크는 임베딩하지 않는다.

    `_content_hash`는 임베딩 없이 text만으로 계산 가능하므로 dedup을 앞으로
    옮길 수 있다 (컴퓨트 낭비 제거).
    """

    async def test_embeds_only_new_chunks(self) -> None:
        repo = _mock_repo()
        # repo가 첫 번째 키를 '이미 적재됨'으로 보고 → 나머지만 신규
        repo.existing_keys.side_effect = lambda keys: {keys[0]} if keys else set()
        embedder = _mock_embedder()
        docs = [_doc(source_id="a"), _doc(source_id="b", body="다른 본문")]
        collector = StubCollector(embedder, repo, docs=docs)

        await collector.run_cycle()

        # 신규 1건만 임베딩
        repo.existing_keys.assert_called_once()
        assert embedder.encode.call_count == 1
        embedded_texts = embedder.encode.call_args.args[0]
        assert len(embedded_texts) == 1
        # insert_chunks에는 신규 청크만 전달
        inserted_chunks = repo.insert_chunks.call_args.args[0]
        assert len(inserted_chunks) == 1

    async def test_no_embedding_when_all_duplicates(self) -> None:
        repo = _mock_repo()
        repo.existing_keys.side_effect = lambda keys: set(keys)
        embedder = _mock_embedder()
        docs = [_doc(source_id="a"), _doc(source_id="b", body="다른 본문")]
        collector = StubCollector(embedder, repo, docs=docs)

        result = await collector.run_cycle()

        embedder.encode.assert_not_called()
        assert result.chunks_inserted == 0
        # 신규 청크가 없으면 insert_chunks는 빈 리스트이거나 미호출
        if repo.insert_chunks.called:
            assert repo.insert_chunks.call_args.args[0] == []


@pytest.mark.asyncio
class TestMetricRecording:
    """metric_repo 인자는 enable flag로 사용. 실제 기록은 별도 get_session()
    컨텍스트로 매 사이클 commit 보장. patch 대상: base 모듈의 module-level
    get_session / SystemMetricRepository.
    """

    async def test_records_news_collected_metric_on_success(self) -> None:
        from unittest.mock import patch as _patch
        repo = _mock_repo()
        collector = StubCollector(
            _mock_embedder(), repo, docs=[_doc()],
            metric_repo=MagicMock(),  # truthy enable flag
        )
        with _patch("src.worker.collectors.base.get_session") as mock_gs, \
             _patch("src.worker.collectors.base.SystemMetricRepository") as mock_smr:
            mock_session = MagicMock()
            mock_gs.return_value.__enter__.return_value = mock_session
            mock_smr_instance = MagicMock()
            mock_smr.return_value = mock_smr_instance
            await collector.run_cycle()
            mock_smr_instance.record_metric.assert_called_once()
            call = mock_smr_instance.record_metric.call_args
            assert call.args[0] == "NEWS_COLLECTED"
            detail = call.args[1]
            assert detail["source"] == "stub"
            assert detail["documents"] == 1
            assert "error" not in detail or detail["error"] is None

    async def test_records_metric_with_error_on_collect_failure(self) -> None:
        from unittest.mock import patch as _patch

        class FailingCollector(StubCollector):
            async def collect(self, since: datetime) -> list[RawDocument]:
                raise RuntimeError("API down")

        repo = _mock_repo()
        collector = FailingCollector(
            _mock_embedder(), repo, docs=[],
            metric_repo=MagicMock(),
        )
        with _patch("src.worker.collectors.base.get_session") as mock_gs, \
             _patch("src.worker.collectors.base.SystemMetricRepository") as mock_smr:
            mock_session = MagicMock()
            mock_gs.return_value.__enter__.return_value = mock_session
            mock_smr_instance = MagicMock()
            mock_smr.return_value = mock_smr_instance
            await collector.run_cycle()
            detail = mock_smr_instance.record_metric.call_args.args[1]
            assert "error" in detail
            assert "API down" in detail["error"]

    async def test_no_metric_when_repo_not_provided(self) -> None:
        """metric_repo=None이면 get_session 자체를 호출하지 않는다."""
        from unittest.mock import patch as _patch
        repo = _mock_repo()
        collector = StubCollector(_mock_embedder(), repo, docs=[_doc()])
        with _patch("src.worker.collectors.base.get_session") as mock_gs:
            await collector.run_cycle()
            mock_gs.assert_not_called()
