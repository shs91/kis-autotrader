"""Token Bucket 방식 API 호출 제한 관리 모듈."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, TypeVar

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


def _today_str() -> str:
    """오늘 날짜를 문자열로 반환한다."""
    import datetime

    return datetime.date.today().isoformat()


# 모듈 레벨 싱글턴 인스턴스
rate_limiter = RateLimiter()
