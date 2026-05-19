"""robots.txt 체크 + 도메인별 캐싱.

각 RSS/뉴스 도메인의 robots.txt를 24시간 캐시. fetch 전에 `can_fetch()`로
허용 여부를 확인하고, `crawl_delay()`로 발행자가 권장하는 호출 간격을 받는다.

설계 원칙:
- 표준상 robots.txt 404/네트워크 에러는 "제약 없음"으로 간주 (허용).
- AI/SEO 봇 차단 규칙이 있어도 우리 user_agent가 일반 봇이면 매칭 안 됨.
- async fetch는 httpx로, parsing은 stdlib urllib.robotparser로.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_CACHE_TTL = timedelta(hours=24)
DEFAULT_USER_AGENT = "kis-autotrader/0.1"


class RobotsChecker:
    """도메인별 robots.txt 캐싱 + 권한 체크."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        client: httpx.AsyncClient | None = None,
        cache_ttl: timedelta = DEFAULT_CACHE_TTL,
    ) -> None:
        self._user_agent = user_agent
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._cache_ttl = cache_ttl
        # domain → (RobotFileParser, expires_at)
        self._cache: dict[str, tuple[RobotFileParser, datetime]] = {}

    async def can_fetch(self, url: str) -> bool:
        """url을 가져와도 되는지 robots.txt 기준으로 판정."""
        parser = await self._get_parser(url)
        if parser is None:
            return True  # robots.txt 자체가 없거나 fetch 실패 → 허용
        return parser.can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> float:
        """발행자가 권장하는 호출 간격 (초). 미지정 시 0.0.

        주의: `can_fetch()`를 먼저 호출해 캐시를 워밍업해야 의미 있는 값을
        반환한다 (캐시 miss면 0).
        """
        domain = urlparse(url).netloc
        entry = self._cache.get(domain)
        if entry is None:
            return 0.0
        delay = entry[0].crawl_delay(self._user_agent)
        return float(delay) if delay else 0.0

    async def _get_parser(self, url: str) -> RobotFileParser | None:
        domain = urlparse(url).netloc
        if not domain:
            return None

        now = datetime.now(UTC)
        cached = self._cache.get(domain)
        if cached is not None and cached[1] > now:
            return cached[0]

        # fetch
        robots_url = f"https://{domain}/robots.txt"
        try:
            response = await self._client.get(robots_url)
        except httpx.HTTPError as e:
            logger.info("robots.txt fetch 실패 %s: %s — 허용으로 간주", robots_url, e)
            return None

        if response.status_code == 404:
            logger.info("robots.txt 없음 (%s) — 허용으로 간주", robots_url)
            return None
        if response.status_code >= 400:
            logger.info(
                "robots.txt HTTP %d (%s) — 허용으로 간주",
                response.status_code, robots_url,
            )
            return None

        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        self._cache[domain] = (parser, now + self._cache_ttl)
        return parser
