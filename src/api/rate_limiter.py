"""Token Bucket 방식 API 호출 제한 관리 모듈."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, TypeVar

from src.config import settings
from src.utils.exceptions import DailyLimitExceededError, RateLimitExceededError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

T = TypeVar("T")

# 호출 간 최소 간격은 RateLimiter 초기화 시 초당 호출 수로부터 동적 계산


class TokenBucket:
    """Token Bucket 알고리즘으로 초당 호출 제한을 관리한다."""

    def __init__(self, rate: int, capacity: int | None = None) -> None:
        """Token Bucket을 초기화한다.

        Args:
            rate: 초당 토큰 생성 속도
            capacity: 버킷 최대 용량 (기본값: rate와 동일)
        """
        self._rate = rate
        self._capacity = capacity if capacity is not None else rate
        self._tokens = float(self._capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """경과 시간에 따라 토큰을 보충한다."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def acquire(self) -> None:
        """토큰 1개를 획득한다. 토큰이 없으면 대기한다."""
        async with self._lock:
            self._refill()
            while self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)
                self._refill()
            self._tokens -= 1.0


class RateLimiter:
    """API 호출 제한을 종합적으로 관리한다.

    Token Bucket으로 초당 호출을 제한하고, 호출 간 최소 간격을 보장하며,
    일일 호출 횟수 상한을 추적한다.
    """

    def __init__(
        self,
        per_second: int | None = None,
        daily_limit: int | None = None,
    ) -> None:
        """RateLimiter를 초기화한다.

        Args:
            per_second: 초당 최대 호출 수 (기본값: settings에서 로드)
            daily_limit: 일일 최대 호출 수 (기본값: settings에서 로드)
        """
        self._per_second = per_second or settings.rate_limit.per_second
        self._daily_limit = daily_limit or settings.rate_limit.daily_limit
        self._min_call_interval = 1.0 / self._per_second
        self._bucket = TokenBucket(rate=self._per_second)
        self._daily_count = 0
        self._daily_reset_date: str = _today_str()
        self._last_call_time: float = 0.0
        self._interval_lock = asyncio.Lock()

        logger.info(
            "RateLimiter 초기화 완료 (초당 %d건, 일일 %d건)",
            self._per_second,
            self._daily_limit,
        )

    def _check_daily_reset(self) -> None:
        """날짜가 바뀌었으면 일일 카운터를 초기화한다."""
        today = _today_str()
        if today != self._daily_reset_date:
            logger.info("일일 호출 카운터 초기화 (%s → %s)", self._daily_reset_date, today)
            self._daily_count = 0
            self._daily_reset_date = today

    async def acquire(self) -> None:
        """API 호출 권한을 획득한다.

        초당 호출 제한, 호출 간 최소 간격, 일일 한도를 모두 확인한다.
        제한 초과 시 자동으로 대기하며, 일일 한도 초과 시 예외를 발생시킨다.

        Raises:
            DailyLimitExceededError: 일일 호출 한도 초과 시
        """
        # 일일 한도 확인
        self._check_daily_reset()
        if self._daily_count >= self._daily_limit:
            raise DailyLimitExceededError(
                f"일일 API 호출 한도 초과: {self._daily_count}/{self._daily_limit}"
            )

        # Token Bucket 대기
        await self._bucket.acquire()

        # 호출 간 최소 간격 보장
        async with self._interval_lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self._min_call_interval:
                wait = self._min_call_interval - elapsed
                await asyncio.sleep(wait)
            self._last_call_time = time.monotonic()

        # 일일 카운터 증가
        self._daily_count += 1

        if self._daily_count % 1000 == 0:
            logger.info("일일 API 호출 횟수: %d/%d", self._daily_count, self._daily_limit)

    def log_daily_count(self) -> None:
        """현재 일일 API 호출 횟수를 로깅한다."""
        logger.info("일일 API 호출 횟수: %d/%d", self._daily_count, self._daily_limit)

    async def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """함수 실행을 rate limit 적용하여 실행한다.

        Args:
            func: 실행할 함수 (동기 또는 비동기)
            *args: 함수 인자
            **kwargs: 함수 키워드 인자

        Returns:
            함수 실행 결과

        Raises:
            DailyLimitExceededError: 일일 호출 한도 초과 시
            RateLimitExceededError: 호출 제한 관련 에러 발생 시
        """
        await self.acquire()
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as e:
            logger.error("rate-limited 함수 실행 중 에러: %s", e)
            raise

    @property
    def daily_count(self) -> int:
        """현재 일일 호출 횟수를 반환한다."""
        return self._daily_count

    @property
    def daily_limit(self) -> int:
        """일일 호출 한도를 반환한다."""
        return self._daily_limit


class RedisRateLimiter:
    """Redis 기반 분산 Rate Limiter.

    프로세스 간 API 호출 제한을 공유한다.
    기존 RateLimiter와 동일한 인터페이스(acquire, daily_count, daily_limit)를 제공한다.
    """

    def __init__(
        self,
        role: str = "main",
        redis_url: str | None = None,
        per_second: int | None = None,
        daily_limit: int | None = None,
    ) -> None:
        """RedisRateLimiter를 초기화한다.

        Args:
            role: 역할 ("main" 또는 "screener").
            redis_url: Redis 연결 URL.
            per_second: 전체 초당 최대 호출 수.
            daily_limit: 일일 최대 호출 수.
        """
        import redis.asyncio as aioredis

        url = redis_url or settings.redis.url
        self._redis = aioredis.from_url(url, decode_responses=True)
        self._role = role
        self._per_second = per_second or settings.rate_limit.per_second
        self._daily_limit = daily_limit or settings.rate_limit.daily_limit
        self._daily_count_key = f"kis_daily_count:{_today_str()}"
        self._last_daily_reset = _today_str()

        logger.info(
            "RedisRateLimiter 초기화 (role=%s, 전체 초당=%d건, 일일=%d건)",
            self._role,
            self._per_second,
            self._daily_limit,
        )

    def _check_daily_key(self) -> None:
        """날짜가 바뀌었으면 일일 카운터 키를 갱신한다."""
        today = _today_str()
        if today != self._last_daily_reset:
            self._daily_count_key = f"kis_daily_count:{today}"
            self._last_daily_reset = today

    async def acquire(self) -> None:
        """API 호출 권한을 획득한다.

        Redis INCR로 초당 호출 수를 확인하고, 역할별 할당량을 초과하면 대기한다.

        Raises:
            DailyLimitExceededError: 일일 호출 한도 초과 시.
        """
        self._check_daily_key()

        # 일일 한도 확인
        daily = await self._redis.get(self._daily_count_key)
        if daily and int(daily) >= self._daily_limit:
            raise DailyLimitExceededError(
                f"일일 API 호출 한도 초과: {daily}/{self._daily_limit}"
            )

        # 초당 호출 제한 (역할별 할당량)
        second_key = f"kis_rate:{int(time.time())}"
        count = await self._redis.incr(second_key)
        if count == 1:
            await self._redis.expire(second_key, 2)

        quota = await self._get_quota()
        if count > quota:
            await asyncio.sleep(1.0)

        # 일일 카운터 증가
        pipe = self._redis.pipeline()
        pipe.incr(self._daily_count_key)
        pipe.expire(self._daily_count_key, 86400 + 3600)  # 25시간 TTL
        await pipe.execute()

    async def _get_quota(self) -> int:
        """역할별 할당량을 조회한다."""
        quota_key = f"kis_quota:{self._role}"
        val = await self._redis.get(quota_key)
        if val is not None:
            return int(val)
        return self._default_quota()

    def _default_quota(self) -> int:
        """역할별 기본 할당량을 반환한다."""
        if self._role == "screener":
            return max(1, self._per_second // 5)
        return self._per_second - max(1, self._per_second // 5)

    @property
    def daily_count(self) -> int:
        """현재 일일 호출 횟수 (동기 조회 — 캐시 없이 Redis 직접 조회)."""
        import redis as sync_redis

        r = sync_redis.from_url(settings.redis.url, decode_responses=True)
        self._check_daily_key()
        val = r.get(self._daily_count_key)
        r.close()
        return int(val) if val else 0

    @property
    def daily_limit(self) -> int:
        """일일 호출 한도를 반환한다."""
        return self._daily_limit

    def log_daily_count(self) -> None:
        """현재 일일 API 호출 횟수를 로깅한다."""
        logger.info(
            "일일 API 호출 횟수: %d/%d (Redis, role=%s)",
            self.daily_count,
            self._daily_limit,
            self._role,
        )


class HybridRateLimiter:
    """Redis 우선, 실패 시 로컬 TokenBucket 폴백.

    Redis 연결이 끊겼을 때 자동으로 로컬 RateLimiter로 전환한다.
    """

    def __init__(self, role: str = "main") -> None:
        """HybridRateLimiter를 초기화한다.

        Args:
            role: 역할 ("main" 또는 "screener").
        """
        self._role = role
        self._redis_limiter: RedisRateLimiter | None = None
        self._local_limiter = RateLimiter()
        self._using_redis = False

        try:
            self._redis_limiter = RedisRateLimiter(role=role)
            self._using_redis = True
        except Exception:
            logger.warning(
                "Redis 연결 실패, 로컬 Rate Limiter로 시작 (role=%s)", role
            )

    async def acquire(self) -> None:
        """API 호출 권한을 획득한다."""
        if self._using_redis and self._redis_limiter is not None:
            try:
                await self._redis_limiter.acquire()
                return
            except (DailyLimitExceededError, RateLimitExceededError):
                raise
            except Exception:
                logger.warning(
                    "Redis 연결 실패, 로컬 Rate Limiter로 폴백 (role=%s)",
                    self._role,
                )
                self._using_redis = False

        await self._local_limiter.acquire()

    @property
    def daily_count(self) -> int:
        """현재 일일 호출 횟수를 반환한다."""
        if self._using_redis and self._redis_limiter is not None:
            try:
                return self._redis_limiter.daily_count
            except Exception:
                pass
        return self._local_limiter.daily_count

    @property
    def daily_limit(self) -> int:
        """일일 호출 한도를 반환한다."""
        return self._local_limiter.daily_limit

    def log_daily_count(self) -> None:
        """현재 일일 API 호출 횟수를 로깅한다."""
        source = "Redis" if self._using_redis else "로컬"
        logger.info(
            "일일 API 호출 횟수: %d/%d (%s, role=%s)",
            self.daily_count,
            self.daily_limit,
            source,
            self._role,
        )


async def update_redis_quota(role_quotas: dict[str, int]) -> None:
    """Redis에 역할별 할당량을 설정한다.

    Args:
        role_quotas: 역할별 초당 할당량. 예: {"main": 16, "screener": 4}.
    """
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis.url, decode_responses=True)
    try:
        pipe = r.pipeline()
        for role, quota in role_quotas.items():
            pipe.set(f"kis_quota:{role}", quota)
        await pipe.execute()
        logger.info("Redis 할당량 업데이트: %s", role_quotas)
    finally:
        await r.aclose()


def _today_str() -> str:
    """오늘 날짜를 문자열로 반환한다."""
    import datetime

    return datetime.date.today().isoformat()


# 모듈 레벨 싱글턴 인스턴스
rate_limiter = RateLimiter()
