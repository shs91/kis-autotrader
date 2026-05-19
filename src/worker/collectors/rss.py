"""RSS 뉴스 수집기.

여러 RSS 피드를 카테고리·라벨과 함께 수집한다. 한 피드에서 가져온 모든 doc은
`metadata`에 `feed_label`(영문 ID)·`category`(한글 라벨)·`provider`를 기록하여
analytics에서 카테고리별 집계를 가능하게 한다.

httpx로 RSS XML을 fetch하고 feedparser로 파싱한다. TickerMatcher를 통해
본문에서 종목을 추출하고, 매칭된 ticker별로 RawDocument를 복제한다.
매칭이 없으면 ticker='MARKET' (시장 전반).

robots.txt 준수와 분당 호출 제한은 운영자 책임 — 본 모듈은 User-Agent
헤더만 명시한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import feedparser  # type: ignore[import-untyped]
import httpx

from src.db.models import NewsSourceType
from src.rag.chunker import RawDocument
from src.utils.logger import setup_logger
from src.worker.collectors.base import BaseCollector
from src.worker.collectors.robots_checker import RobotsChecker

if TYPE_CHECKING:
    from src.db.repository import NewsChunkRepository, SystemMetricRepository
    from src.rag.embedder import Embedder
    from src.rag.ticker_matcher import TickerMatcher

logger = setup_logger(__name__)


@dataclass(frozen=True)
class FeedSource:
    """RSS 피드 메타데이터.

    - label: 영문 ID (e.g., "yonhap_market", "edaily_stock_news"). 로그·메트릭 키.
    - category: 한글 분류 (e.g., "증권", "경제", "산업"). 리포트 표시용.
    - url: 피드 URL.
    - provider: 발행사 (e.g., "yonhap", "edaily"). 필수 — provider 단위 집계용.
    """

    label: str
    category: str
    url: str
    provider: str


class RSSCollector(BaseCollector):
    """RSS 피드 수집기. 본문에서 종목을 매칭하여 ticker별 doc을 만든다."""

    source_name = "rss"

    def __init__(
        self,
        embedder: Embedder,
        repo: NewsChunkRepository,
        feeds: list[FeedSource],
        ticker_matcher: TickerMatcher,
        user_agent: str,
        client: httpx.AsyncClient | None = None,
        robots_checker: RobotsChecker | None = None,
        metric_repo: SystemMetricRepository | None = None,
    ) -> None:
        super().__init__(embedder=embedder, repo=repo, metric_repo=metric_repo)
        self._feeds = feeds
        self._matcher = ticker_matcher
        self._user_agent = user_agent
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        self._robots = robots_checker or RobotsChecker(
            user_agent=user_agent, client=self._client,
        )

    async def collect(self, since: datetime) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for feed in self._feeds:
            # robots.txt 체크 — 차단된 피드는 fetch 자체를 안 함
            if not await self._robots.can_fetch(feed.url):
                logger.warning(
                    "robots.txt 차단 — skip: %s (%s)", feed.label, feed.url,
                )
                continue
            # 발행자가 권장하는 Crawl-delay 준수
            delay = self._robots.crawl_delay(feed.url)
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                items = await self._fetch_feed(feed.url)
            except httpx.HTTPError as e:
                logger.warning("RSS fetch 실패 %s (%s): %s", feed.label, feed.url, e)
                continue
            for item in items:
                docs.extend(self._expand_item(item, since, feed))
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
        self, item: dict[str, Any], since: datetime, feed: FeedSource,
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

        metadata: dict[str, object] = {
            "feed_label": feed.label,
            "category": feed.category,
            "provider": feed.provider,
        }
        # source_id에 feed_label을 prefix해 같은 guid가 다른 피드에서 들어와도 충돌 안 함
        composite_id = f"{feed.label}:{guid}"
        return [
            RawDocument(
                ticker=ticker,
                source_type=NewsSourceType.NEWS,
                source_id=composite_id,
                title=title,
                body=body_text,
                event_time=event_time,
                source_url=link,
                metadata=metadata,
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
