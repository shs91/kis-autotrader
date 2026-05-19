"""RobotsChecker — robots.txt 캐싱 + can_fetch / crawl_delay 테스트.

httpx.AsyncClient를 mock하여 robots.txt 응답을 시뮬레이션.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.worker.collectors.robots_checker import RobotsChecker


def _mock_client(*responses: tuple[int, str]) -> MagicMock:
    """순차 응답 mock — status_code와 text를 튜플로 받는다."""
    mocks = []
    for status, text in responses:
        r = MagicMock()
        r.status_code = status
        r.text = text
        r.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("", request=MagicMock(), response=r)
            if status >= 400 else None
        )
        mocks.append(r)
    client = MagicMock()
    client.get = AsyncMock(side_effect=mocks)
    return client


ALLOW_ALL = "User-agent: *\nAllow: /\n"
DISALLOW_NEWS = "User-agent: *\nDisallow: /news/\n"
WITH_CRAWL_DELAY = "User-agent: *\nAllow: /\nCrawl-delay: 5\n"


@pytest.mark.asyncio
class TestCanFetch:
    async def test_allow_when_robots_allows(self) -> None:
        client = _mock_client((200, ALLOW_ALL))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        assert await checker.can_fetch("https://example.com/rss/feed.xml") is True

    async def test_disallow_when_robots_disallows(self) -> None:
        client = _mock_client((200, DISALLOW_NEWS))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        assert await checker.can_fetch("https://example.com/news/item.xml") is False

    async def test_allow_when_robots_404(self) -> None:
        """robots.txt 404 → 표준상 제약 없음으로 간주."""
        client = _mock_client((404, "<html>not found</html>"))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        assert await checker.can_fetch("https://example.com/any.xml") is True

    async def test_allow_when_fetch_fails(self) -> None:
        """네트워크 에러 → 허용 fallback (수집 자체는 막지 않음)."""
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("no route"))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        assert await checker.can_fetch("https://example.com/any.xml") is True


@pytest.mark.asyncio
class TestCache:
    async def test_caches_per_domain(self) -> None:
        client = _mock_client((200, ALLOW_ALL))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        # 같은 도메인 두 번 → fetch는 1회
        await checker.can_fetch("https://example.com/a.xml")
        await checker.can_fetch("https://example.com/b.xml")
        assert client.get.call_count == 1

    async def test_separate_cache_per_domain(self) -> None:
        client = _mock_client((200, ALLOW_ALL), (200, DISALLOW_NEWS))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        await checker.can_fetch("https://a.example/x.xml")
        await checker.can_fetch("https://b.example/y.xml")
        assert client.get.call_count == 2

    async def test_cache_expires_after_ttl(self) -> None:
        client = _mock_client((200, ALLOW_ALL), (200, ALLOW_ALL))
        checker = RobotsChecker(
            user_agent="kis-test", client=client, cache_ttl=timedelta(hours=24),
        )
        # 1차 fetch
        await checker.can_fetch("https://example.com/x.xml")
        # 만료 시점 강제 — 25시간 이전
        checker._cache["example.com"] = (  # type: ignore[index]
            checker._cache["example.com"][0],  # type: ignore[index]
            datetime.now(UTC) - timedelta(hours=1),
        )
        await checker.can_fetch("https://example.com/x.xml")
        assert client.get.call_count == 2


@pytest.mark.asyncio
class TestCrawlDelay:
    async def test_returns_zero_when_not_specified(self) -> None:
        client = _mock_client((200, ALLOW_ALL))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        await checker.can_fetch("https://example.com/x.xml")
        assert checker.crawl_delay("https://example.com/x.xml") == 0.0

    async def test_returns_value_when_specified(self) -> None:
        client = _mock_client((200, WITH_CRAWL_DELAY))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        await checker.can_fetch("https://example.com/x.xml")
        assert checker.crawl_delay("https://example.com/x.xml") == 5.0

    async def test_returns_zero_for_uncached_domain(self) -> None:
        client = _mock_client((200, ALLOW_ALL))
        checker = RobotsChecker(user_agent="kis-test", client=client)
        # can_fetch 호출 없이 crawl_delay만 → 캐시 miss → 0
        assert checker.crawl_delay("https://never-fetched.example/x.xml") == 0.0
