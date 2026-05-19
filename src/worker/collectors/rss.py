"""RSS 뉴스 수집기.

httpx로 RSS XML을 fetch하고 feedparser로 파싱한다. TickerMatcher를 통해
본문에서 종목을 추출하고, 매칭된 ticker별로 RawDocument를 복제한다.
매칭이 없으면 ticker='MARKET' (시장 전반).

robots.txt 준수와 분당 호출 제한은 운영자 책임 — 본 모듈은 User-Agent
헤더만 명시한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import feedparser  # type: ignore[import-untyped]
import httpx

from src.db.models import NewsSourceType
from src.rag.chunker import RawDocument
from src.utils.logger import setup_logger
from src.worker.collectors.base import BaseCollector

if TYPE_CHECKING:
    from src.db.repository import NewsChunkRepository
    from src.rag.embedder import Embedder
    from src.rag.ticker_matcher import TickerMatcher

logger = setup_logger(__name__)


class RSSCollector(BaseCollector):
    """RSS 피드 수집기. 본문에서 종목을 매칭하여 ticker별 doc을 만든다."""

    source_name = "rss"

    def __init__(
        self,
        embedder: Embedder,
        repo: NewsChunkRepository,
        feed_urls: list[str],
        ticker_matcher: TickerMatcher,
        user_agent: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(embedder=embedder, repo=repo)
        self._feed_urls = feed_urls
        self._matcher = ticker_matcher
        self._user_agent = user_agent
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def collect(self, since: datetime) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for url in self._feed_urls:
            try:
                items = await self._fetch_feed(url)
            except httpx.HTTPError as e:
                logger.warning("RSS fetch 실패 %s: %s", url, e)
                continue
            for item in items:
                docs.extend(self._expand_item(item, since))
        return docs

    async def _fetch_feed(self, url: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            url, headers={"User-Agent": self._user_agent},
        )
        response.raise_for_status()
        # feedparser는 동기 — 짧은 텍스트 파싱이라 to_thread 생략하고 직접 호출
        parsed = feedparser.parse(response.text)
        return list(parsed.entries or [])

    def _expand_item(
        self, item: dict[str, Any], since: datetime
    ) -> list[RawDocument]:
        title = item.get("title") or ""
        summary = item.get("summary") or item.get("description") or ""
        link = item.get("link")
        guid = item.get("id") or item.get("guid") or link
        if not guid:
            return []

        event_time = _parse_pubdate(item) or datetime.now(UTC)
        if event_time < since:
            return []

        body_text = summary
        # 종목 매칭은 제목과 본문 모두에서 시도
        search_text = f"{title}\n{summary}"
        tickers = self._matcher.match(search_text)
        if not tickers:
            tickers = ["MARKET"]

        return [
            RawDocument(
                ticker=ticker,
                source_type=NewsSourceType.NEWS,
                source_id=str(guid),
                title=title,
                body=body_text,
                event_time=event_time,
                source_url=link,
                metadata={},
            )
            for ticker in tickers
        ]


def _parse_pubdate(item: dict[str, Any]) -> datetime | None:
    """RFC822 pubDate 또는 feedparser의 published_parsed를 UTC datetime으로."""
    parsed = item.get("published_parsed") or item.get("updated_parsed")
    if not parsed:
        return None
    # time.struct_time → UTC
    import time as _time
    return datetime.fromtimestamp(_time.mktime(parsed), tz=UTC)


# asyncio.sleep을 안 쓰는 collect 흐름이라 보일러플레이트 없음 — 분당 호출 제한은
# 호출자(스케줄러)가 사이클 간격으로 제어한다.
_ = asyncio  # noqa: B018 — 향후 to_thread 활용 시 유지
