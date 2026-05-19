"""RSSCollector 테스트.

feedparser는 동기 라이브러리. httpx로 RSS XML fetch 후 feedparser.parse 호출.
TickerMatcher로 본문에서 종목 추출 → 매칭별 RawDocument 복제.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.models import NewsSourceType
from src.rag.ticker_matcher import TickerMatcher
from src.worker.collectors.rss import RSSCollector

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


def _make_collector(
    client: MagicMock | None = None,
    matcher: TickerMatcher | None = None,
) -> RSSCollector:
    return RSSCollector(
        embedder=MagicMock(),
        repo=MagicMock(),
        feed_urls=["https://example.com/feed.xml"],
        ticker_matcher=matcher or TickerMatcher([
            ("005930", "삼성전자"),
            ("000660", "SK하이닉스"),
        ]),
        user_agent="test-agent",
        client=client or _mock_client(),
    )


@pytest.mark.asyncio
class TestCollect:
    async def test_matched_news_produces_doc(self) -> None:
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        # 삼성전자 매칭: item1 + item3 = 2 docs (ticker=005930)
        # SK하이닉스 매칭: item3 = 1 doc (ticker=000660)
        # 미매칭: item2 → ticker=MARKET = 1 doc
        tickers = sorted(d.ticker for d in docs)
        assert "005930" in tickers
        assert "000660" in tickers
        assert "MARKET" in tickers

    async def test_doc_fields(self) -> None:
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        doc = next(d for d in docs if d.ticker == "005930")
        assert doc.source_type == NewsSourceType.NEWS
        assert doc.title is not None
        assert "삼성전자" in doc.title
        assert doc.event_time.tzinfo is not None
        assert doc.source_url is not None
        assert doc.source_url.startswith("https://news.example.com/")

    async def test_multiple_tickers_in_one_item_duplicate_doc(self) -> None:
        """한 기사에 여러 종목이 매칭되면 ticker별로 doc이 복제된다."""
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        # item3 (news-3) 는 삼성전자 + SK하이닉스 둘 다 매칭
        item3_docs = [d for d in docs if d.source_id == "news-3"]
        tickers = sorted(d.ticker for d in item3_docs)
        assert tickers == ["000660", "005930"]

    async def test_market_for_unmatched_items(self) -> None:
        collector = _make_collector()
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        market_docs = [d for d in docs if d.ticker == "MARKET"]
        assert len(market_docs) == 1
        assert market_docs[0].source_id == "news-2"

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
