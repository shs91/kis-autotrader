"""KIS API 기본 HTTP 클라이언트 모듈."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from src.api.auth import KISAuth
from src.api.rate_limiter import RateLimiter, rate_limiter
from src.config import settings
from src.utils.exceptions import KISAutoTraderError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 재시도 관련 상수
MAX_RETRIES: int = 3
RETRY_BASE_DELAY: float = 1.0

# Circuit breaker 상수
CIRCUIT_FAILURE_THRESHOLD: int = 5
CIRCUIT_RESET_TIMEOUT: float = 30.0


class CircuitBreaker:
    """연속 실패 시 요청을 차단하는 서킷 브레이커.

    반개방 후 재실패 시 리셋 대기 시간이 점진적으로 증가한다 (exponential backoff).
    최대 대기 시간은 5분(300초)이며, 성공 시 모든 상태가 초기화된다.
    """

    MAX_RESET_TIMEOUT: float = 300.0  # 최대 5분

    def __init__(
        self,
        failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
        reset_timeout: float = CIRCUIT_RESET_TIMEOUT,
    ) -> None:
        """CircuitBreaker를 초기화한다.

        Args:
            failure_threshold: 차단까지 허용하는 연속 실패 횟수
            reset_timeout: 차단 후 재시도까지 기본 대기 시간(초)
        """
        self._failure_threshold = failure_threshold
        self._base_reset_timeout = reset_timeout
        self._current_reset_timeout = reset_timeout
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._is_open = False
        self._trip_count = 0  # 서킷이 열린 누적 횟수

    def record_success(self) -> None:
        """성공을 기록하고 서킷을 닫는다. 백오프도 초기화."""
        self._failure_count = 0
        self._is_open = False
        self._trip_count = 0
        self._current_reset_timeout = self._base_reset_timeout

    def record_failure(self) -> None:
        """실패를 기록하고 임계값 초과 시 서킷을 연다."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._is_open = True
            self._trip_count += 1
            # 반복 트립 시 대기 시간 점진 증가 (30s → 60s → 120s → 240s → 300s)
            self._current_reset_timeout = min(
                self._base_reset_timeout * (2 ** (self._trip_count - 1)),
                self.MAX_RESET_TIMEOUT,
            )
            logger.warning(
                "서킷 브레이커 작동: 연속 %d회 실패, %.0f초간 요청 차단 (트립 #%d)",
                self._failure_count,
                self._current_reset_timeout,
                self._trip_count,
            )

    def _try_half_open(self) -> bool:
        """timer 만료 시 반개방 상태로 lazy 전환. 전환됐으면 True."""
        if not self._is_open:
            return False
        elapsed = time.monotonic() - self._last_failure_time
        if elapsed >= self._current_reset_timeout:
            logger.info(
                "서킷 브레이커 반개방: %.0f초 경과, 재시도 허용 (트립 #%d)",
                elapsed,
                self._trip_count,
            )
            self._failure_count = 0
            self._is_open = False
            return True
        return False

    def is_available(self) -> bool:
        """요청이 가능한 상태인지 확인한다 (timer 만료 시 자동 반개방)."""
        if not self._is_open:
            return True
        if self._try_half_open():
            return True
        return False

    @property
    def is_open(self) -> bool:
        """서킷이 열려있는지 반환 (timer 만료 시 자동 반개방).

        Phase 운영 결함 수정: engine.py 등 호출자가 is_open property를
        통해 검사할 때, timer가 만료됐다면 자동으로 반개방하여 다음
        record_success/failure가 정상 동작하도록 한다.
        is_available()과 일관된 결과 보장.
        """
        if self._is_open:
            self._try_half_open()
        return self._is_open


class KISClient:
    """KIS OpenAPI HTTP 클라이언트.

    모든 REST API 호출은 이 클라이언트를 통해 이루어지며,
    RateLimiter, CircuitBreaker, 재시도 로직이 자동 적용된다.
    """

    def __init__(
        self,
        auth: KISAuth | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        """KISClient를 초기화한다.

        Args:
            auth: KISAuth 인스턴스 (기본값: 새로 생성)
            limiter: RateLimiter 인스턴스 (기본값: 모듈 싱글턴)
        """
        self._auth = auth or KISAuth()
        self._limiter = limiter or rate_limiter
        self._base_url = settings.kis.base_url
        self._circuit_breaker = CircuitBreaker()

        logger.info("KISClient 초기화 완료 (base_url=%s)", self._base_url)

    async def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        tr_id: str = "",
    ) -> dict[str, Any]:
        """GET 요청을 보낸다.

        Args:
            path: API 경로 (예: "/uapi/domestic-stock/v1/quotations/inquire-price")
            headers: 추가 헤더
            params: 쿼리 파라미터
            tr_id: 거래 ID

        Returns:
            응답 JSON 딕셔너리

        Raises:
            KISAutoTraderError: API 호출 실패 시
        """
        return await self._request("GET", path, headers=headers, params=params, tr_id=tr_id)

    async def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        tr_id: str = "",
        use_hashkey: bool = False,
    ) -> dict[str, Any]:
        """POST 요청을 보낸다.

        Args:
            path: API 경로
            headers: 추가 헤더
            body: 요청 본문
            tr_id: 거래 ID
            use_hashkey: hashkey 사용 여부

        Returns:
            응답 JSON 딕셔너리

        Raises:
            KISAutoTraderError: API 호출 실패 시
        """
        return await self._request(
            "POST", path, headers=headers, body=body, tr_id=tr_id, use_hashkey=use_hashkey
        )

    async def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        tr_id: str = "",
        use_hashkey: bool = False,
    ) -> dict[str, Any]:
        """HTTP 요청을 실행한다. 재시도와 서킷 브레이커가 적용된다.

        Args:
            method: HTTP 메서드
            path: API 경로
            headers: 추가 헤더
            params: 쿼리 파라미터
            body: 요청 본문
            tr_id: 거래 ID
            use_hashkey: hashkey 사용 여부

        Returns:
            응답 JSON 딕셔너리

        Raises:
            KISAutoTraderError: 서킷 브레이커 차단 또는 최대 재시도 초과 시
            RateLimitExceededError: API 서버에서 429 응답을 받았을 때
        """
        if not self._circuit_breaker.is_available():
            raise KISAutoTraderError(
                "서킷 브레이커가 작동 중입니다. 잠시 후 다시 시도하세요."
            )

        url = f"{self._base_url}{path}"

        # 공통 헤더 구성
        access_token = await self._auth.get_access_token()
        request_headers = self._build_headers(access_token, tr_id, headers)

        # hashkey 적용
        if use_hashkey and body:
            hashkey = await self._auth.get_hashkey(body)
            request_headers["hashkey"] = hashkey

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                # RateLimiter 통과
                await self._limiter.acquire()

                request_time = time.time()
                logger.info(
                    "[API 요청] %s %s (시도 %d/%d)",
                    method,
                    path,
                    attempt + 1,
                    MAX_RETRIES,
                )

                async with httpx.AsyncClient() as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=request_headers,
                        params=params,
                        json=body,
                        timeout=30.0,
                    )

                elapsed = time.time() - request_time
                logger.info(
                    "[API 응답] %s %s → %d (%.2fs)",
                    method,
                    path,
                    response.status_code,
                    elapsed,
                )

                # 429 Too Many Requests
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", "1"))
                    logger.warning(
                        "429 Too Many Requests: %.1f초 대기 후 재시도", retry_after
                    )
                    await asyncio.sleep(retry_after)
                    continue

                # 5xx 서버 에러
                if response.status_code >= 500:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "서버 에러 %d: %.1f초 후 재시도", response.status_code, delay
                    )
                    self._circuit_breaker.record_failure()
                    await asyncio.sleep(delay)
                    last_error = KISAutoTraderError(
                        f"서버 에러 (status={response.status_code}): {response.text}"
                    )
                    continue

                # 기타 에러
                if response.status_code >= 400:
                    self._circuit_breaker.record_failure()
                    raise KISAutoTraderError(
                        f"API 에러 (status={response.status_code}): {response.text}"
                    )

                # 성공
                self._circuit_breaker.record_success()
                return response.json()  # type: ignore[no-any-return]

            except httpx.HTTPError as e:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.error("네트워크 에러: %s (%.1f초 후 재시도)", e, delay)
                self._circuit_breaker.record_failure()
                last_error = KISAutoTraderError(f"네트워크 에러: {e}")
                await asyncio.sleep(delay)

        # 최대 재시도 초과
        raise KISAutoTraderError(
            f"최대 재시도 횟수 초과 ({MAX_RETRIES}회): {last_error}"
        )

    def _build_headers(
        self,
        access_token: str,
        tr_id: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """요청 헤더를 구성한다.

        Args:
            access_token: OAuth 액세스 토큰
            tr_id: 거래 ID
            extra_headers: 추가 헤더

        Returns:
            구성된 헤더 딕셔너리
        """
        headers: dict[str, str] = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {access_token}",
            "appkey": settings.kis.app_key,
            "appsecret": settings.kis.app_secret,
        }
        if tr_id:
            headers["tr_id"] = tr_id
        if extra_headers:
            headers.update(extra_headers)
        return headers

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """서킷 브레이커 인스턴스를 반환한다."""
        return self._circuit_breaker
