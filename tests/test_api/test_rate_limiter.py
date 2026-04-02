"""RateLimiter 테스트."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.api.rate_limiter import MIN_CALL_INTERVAL, RateLimiter, TokenBucket
from src.utils.exceptions import DailyLimitExceededError


class TestTokenBucket:
    """TokenBucket 단위 테스트."""

    async def test_acquire_within_limit(self) -> None:
        """제한 내 호출은 즉시 통과한다."""
        bucket = TokenBucket(rate=10, capacity=10)
        start = time.monotonic()
        await bucket.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    async def test_acquire_waits_when_empty(self) -> None:
        """토큰이 없으면 대기한다."""
        bucket = TokenBucket(rate=2, capacity=1)
        await bucket.acquire()  # 토큰 소진
        start = time.monotonic()
        await bucket.acquire()  # 대기 필요
        elapsed = time.monotonic() - start
        assert elapsed >= 0.3  # 1/rate = 0.5초 근처


class TestRateLimiter:
    """RateLimiter 통합 테스트."""

    async def test_acquire_enforces_min_interval(self) -> None:
        """호출 간 최소 간격이 보장된다."""
        limiter = RateLimiter(per_second=10, daily_limit=10000)
        times: list[float] = []

        for _ in range(3):
            await limiter.acquire()
            times.append(time.monotonic())

        for i in range(1, len(times)):
            interval = times[i] - times[i - 1]
            assert interval >= MIN_CALL_INTERVAL * 0.9  # 약간의 오차 허용

    async def test_daily_limit_exceeded(self) -> None:
        """일일 한도 초과 시 DailyLimitExceededError가 발생한다."""
        limiter = RateLimiter(per_second=100, daily_limit=3)

        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()

        with pytest.raises(DailyLimitExceededError):
            await limiter.acquire()

    async def test_execute_runs_async_func(self) -> None:
        """execute로 비동기 함수를 실행할 수 있다."""
        limiter = RateLimiter(per_second=10, daily_limit=10000)

        async def add(a: int, b: int) -> int:
            return a + b

        result = await limiter.execute(add, 3, 5)
        assert result == 8

    async def test_execute_runs_sync_func(self) -> None:
        """execute로 동기 함수를 실행할 수 있다."""
        limiter = RateLimiter(per_second=10, daily_limit=10000)

        def multiply(a: int, b: int) -> int:
            return a * b

        result = await limiter.execute(multiply, 3, 5)
        assert result == 15

    async def test_concurrent_calls_respect_limit(self) -> None:
        """동시 호출이 rate limit을 준수한다."""
        limiter = RateLimiter(per_second=10, daily_limit=10000)
        call_times: list[float] = []

        async def timed_acquire() -> None:
            await limiter.acquire()
            call_times.append(time.monotonic())

        tasks = [timed_acquire() for _ in range(5)]
        await asyncio.gather(*tasks)

        assert len(call_times) == 5
        # 모든 호출 간 최소 간격 확인
        call_times.sort()
        for i in range(1, len(call_times)):
            interval = call_times[i] - call_times[i - 1]
            assert interval >= MIN_CALL_INTERVAL * 0.8  # 동시 실행 오차 허용

    async def test_daily_count_tracking(self) -> None:
        """일일 호출 횟수가 정확히 추적된다."""
        limiter = RateLimiter(per_second=100, daily_limit=10000)

        assert limiter.daily_count == 0
        await limiter.acquire()
        assert limiter.daily_count == 1
        await limiter.acquire()
        assert limiter.daily_count == 2
