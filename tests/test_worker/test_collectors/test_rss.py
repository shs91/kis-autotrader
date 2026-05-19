"""RSSCollector 테스트.

여러 피드 (label/category/provider 메타 포함) → metadata에 기록 + 종목 매칭별
doc 복제.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.models import NewsSourceType
from src.rag.ticker_matcher import TickerMatcher
from src.worker.collectors.robots_checker import RobotsChecker
from src.worker.collectors.rss import FeedSource, RSSCollector

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 피드</title>
    <item>
      <title>삼성전자 3분기 영업이익 8조원 발표</title>
      <link>https://news.example.com/1</link>
      <description>삼성전자가 시장 예상치를 상회하는 실적을 발표했다.</description>
      <pubDate>Mon, 18 May 2026 09:00:00 +0900</pubDate>
      <guid>news-1</guid>
    </item>
    <item>
      <title>한국은행 기준금리 동결</title>
      <link>https://news.example.com/2</link>
      <description>금융통화위원회는 기준금리를 동결했다.</description>
      <pubDate>Mon, 18 May 2026 10:00:00 +0900</pubDate>
      <guid>news-2</guid>
    </item>
    <item>
      <title>삼성전자와 SK하이닉스 메모리 호조</title>
      <link>https://news.example.com/3</link>
      <description>HBM 수요 폭증으로 양사 동반 강세.</description>
      <pubDate>Mon, 18 May 2026 11:00:00 +0900</pubDate>
      <guid>news-3</guid>
    </item>
  </channel>
</rss>
"""


def _mock_client(xml: str = RSS_XML) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.text = xml
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    return client


def _feed(
    label: str = "yonhap_market",
    category: str = "증권",
    url: str = "https://www.yna.co.kr/rss/market.xml",
    provider: str = "yonhap",
) -> FeedSource:
    return FeedSource(label=label, category=category, url=url, provider=provider)


def _allow_all_robots() -> MagicMock:
    """기본 RobotsChecker mock — 모든 URL 허용, crawl_delay 0."""
    robots = MagicMock(spec=RobotsChecker)
    robots.can_fetch = AsyncMock(return_value=True)
    robots.crawl_delay = MagicMock(return_value=0.0)
    return robots


def _make_collector(
    feeds: list[FeedSource] | None = None,
    client: MagicMock | None = None,
    matcher: TickerMatcher | None = None,
    robots: MagicMock | None = None,
) -> RSSCollector:
    return RSSCollector(
        embedder=MagicMock(),
        repo=MagicMock(),
        feeds=feeds or [_feed()],
        ticker_matcher=matcher or TickerMatcher([
            ("005930", "삼성전자"),
            ("000660", "SK하이닉스"),
        ]),
        user_agent="test-agent",
        client=client or _mock_client(),
        robots_checker=robots or _allow_all_robots(),
    )


@pytest.mark.asyncio
class TestCollect:
    async def test_matched_news_produces_doc(self) -> None:
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        tickers = sorted(d.ticker for d in docs)
        assert "005930" in tickers
        assert "000660" in tickers
        assert "MARKET" in tickers

    async def test_doc_fields(self) -> None:
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        doc = next(d for d in docs if d.ticker == "005930")
        assert doc.source_type == NewsSourceType.NEWS
        assert "삼성전자" in (doc.title or "")
        assert doc.event_time.tzinfo is not None
        assert (doc.source_url or "").startswith("https://news.example.com/")

    async def test_metadata_carries_feed_label_and_category(self) -> None:
        feed = _feed(label="yonhap_market", category="증권", provider="yonhap")
        collector = _make_collector(feeds=[feed])
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        for doc in docs:
            assert doc.metadata["feed_label"] == "yonhap_market"
            assert doc.metadata["category"] == "증권"
            assert doc.metadata["provider"] == "yonhap"

    async def test_source_id_namespaced_by_feed_label(self) -> None:
        """같은 guid가 다른 피드에서 들어와도 source_id가 겹치지 않는다."""
        feed_a = _feed(label="yonhap_market")
        feed_b = _feed(label="edaily_stock_news", category="증권", provider="edaily")
        # 같은 RSS XML을 두 피드에서 받았다고 가정
        collector = _make_collector(feeds=[feed_a, feed_b])
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        prefixes = {d.source_id.split(":", 1)[0] for d in docs if d.source_id}
        assert prefixes == {"yonhap_market", "edaily_stock_news"}

    async def test_multiple_tickers_in_one_item_duplicate_doc(self) -> None:
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        # news-3 → yonhap_market:news-3
        item3_docs = [d for d in docs if d.source_id and "news-3" in d.source_id]
        tickers = sorted(d.ticker for d in item3_docs)
        assert tickers == ["000660", "005930"]

    async def test_market_for_unmatched_items(self) -> None:
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        market_docs = [d for d in docs if d.ticker == "MARKET"]
        assert len(market_docs) == 1
        assert market_docs[0].source_id and "news-2" in market_docs[0].source_id

    async def test_user_agent_header(self) -> None:
        client = _mock_client()
        collector = _make_collector(client=client)
        await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        call_kwargs = client.get.call_args.kwargs
        headers = call_kwargs.get("headers") or {}
        assert headers.get("User-Agent") == "test-agent"

    async def test_empty_feed(self) -> None:
        empty_xml = "<?xml version='1.0'?><rss><channel></channel></rss>"
        collector = _make_collector(client=_mock_client(xml=empty_xml))
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        assert docs == []

    async def test_failed_feed_does_not_block_others(self) -> None:
        """한 피드 404가 다른 피드 수집을 막지 않는다."""
        import httpx
        response_ok = MagicMock()
        response_ok.text = RSS_XML
        response_ok.raise_for_status = MagicMock()

        client = MagicMock()
        # 첫 피드 → 404, 둘째 피드 → OK
        client.get = AsyncMock(side_effect=[
            httpx.HTTPError("404 not found"),
            response_ok,
        ])
        feeds = [
            _feed(label="dead", url="https://dead.example/feed.xml"),
            _feed(label="alive", url="https://alive.example/feed.xml"),
        ]
        collector = _make_collector(feeds=feeds, client=client)
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        # 두 번째 피드 결과만 들어와야 함
        labels = {d.metadata["feed_label"] for d in docs}
        assert labels == {"alive"}


@pytest.mark.asyncio
class TestRobotsIntegration:
    async def test_robots_disallowed_feed_skipped(self) -> None:
        """robots.txt가 차단한 피드는 fetch 자체를 안 한다."""
        robots = MagicMock(spec=RobotsChecker)
        robots.can_fetch = AsyncMock(side_effect=[False, True])
        robots.crawl_delay = MagicMock(return_value=0.0)

        client = _mock_client()
        feeds = [
            _feed(label="blocked", url="https://blocked.example/feed.xml"),
            _feed(label="allowed", url="https://allowed.example/feed.xml"),
        ]
        collector = _make_collector(feeds=feeds, client=client, robots=robots)
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))

        # client.get은 1회만 호출되어야 함 (allowed 피드만)
        assert client.get.call_count == 1
        # 모든 doc의 metadata.feed_label은 'allowed'
        labels = {d.metadata["feed_label"] for d in docs}
        assert labels == {"allowed"}

    async def test_crawl_delay_respected(self) -> None:
        """robots.txt Crawl-delay가 있으면 fetch 전 대기."""
        import asyncio as _asyncio
        from unittest.mock import patch as _patch

        robots = MagicMock(spec=RobotsChecker)
        robots.can_fetch = AsyncMock(return_value=True)
        robots.crawl_delay = MagicMock(return_value=2.0)

        collector = _make_collector(robots=robots)
        with _patch.object(_asyncio, "sleep", new=AsyncMock()) as mock_sleep:
            await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        mock_sleep.assert_any_await(2.0)
