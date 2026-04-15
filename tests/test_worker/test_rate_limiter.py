"""RedisRateLimiter / HybridRateLimiter 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.rate_limiter import HybridRateLimiter, RedisRateLimiter


@pytest.mark.asyncio()
class TestRedisRateLimiter:
    """RedisRateLimiter 테스트."""

    @patch("src.api.rate_limiter.settings")
    async def test_default_quota_main(self, mock_settings):
        """main 역할의 기본 할당량이 전체의 80%이다."""
        mock_settings.rate_limit.per_second = 20
        mock_settings.rate_limit.daily_limit = 50000
        mock_settings.redis.url = "redis://localhost:6380/0"

        with patch("redis.asyncio.from_url") as mock_redis:
            limiter = RedisRateLimiter(role="main")
            assert limiter._default_quota() == 16  # 20 - 4

    @patch("src.api.rate_limiter.settings")
    async def test_default_quota_screener(self, mock_settings):
        """screener 역할의 기본 할당량이 전체의 20%이다."""
        mock_settings.rate_limit.per_second = 20
        mock_settings.rate_limit.daily_limit = 50000
        mock_settings.redis.url = "redis://localhost:6380/0"

        with patch("redis.asyncio.from_url") as mock_redis:
            limiter = RedisRateLimiter(role="screener")
            assert limiter._default_quota() == 4  # 20 // 5


@pytest.mark.asyncio()
class TestHybridRateLimiter:
    """HybridRateLimiter 테스트."""

    async def test_fallback_to_local_on_redis_failure(self):
        """Redis 연결 실패 시 로컬 RateLimiter로 폴백한다."""
        with patch(
            "src.api.rate_limiter.RedisRateLimiter",
            side_effect=Exception("Redis 연결 실패"),
        ):
            limiter = HybridRateLimiter(role="main")

        assert limiter._using_redis is False
        # 로컬 limiter로 acquire 가능
        await limiter.acquire()

    async def test_daily_count_fallback(self):
        """Redis 실패 시 daily_count가 로컬에서 반환된다."""
        with patch(
            "src.api.rate_limiter.RedisRateLimiter",
            side_effect=Exception("Redis 연결 실패"),
        ):
            limiter = HybridRateLimiter(role="main")

        assert limiter.daily_count == 0
        assert limiter.daily_limit > 0
