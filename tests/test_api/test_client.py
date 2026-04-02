"""KISClient 재시도 로직, 서킷 브레이커 테스트."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.api.client import (
    CIRCUIT_FAILURE_THRESHOLD,
    CircuitBreaker,
    KISClient,
)
from src.api.rate_limiter import RateLimiter
from src.utils.exceptions import KISAutoTraderError


class TestCircuitBreaker:
    """CircuitBreaker 테스트."""

    def test_initially_available(self) -> None:
        """초기 상태에서 요청이 가능하다."""
        cb = CircuitBreaker()
        assert cb.is_available() is True
        assert cb.is_open is False

    def test_opens_after_threshold(self) -> None:
        """임계값 초과 시 서킷이 열린다."""
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=30.0)

        cb.record_failure()
        cb.record_failure()
        assert cb.is_available() is True

        cb.record_failure()  # 3번째 실패
        assert cb.is_open is True
        assert cb.is_available() is False

    def test_resets_on_success(self) -> None:
        """성공 기록 시 서킷이 닫힌다."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True

        cb.record_success()
        assert cb.is_open is False
        assert cb.is_available() is True

    def test_half_open_after_timeout(self) -> None:
        """타임아웃 후 반개방 상태가 된다."""
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1)
        cb.record_failure()
        assert cb.is_available() is False

        time.sleep(0.15)
        assert cb.is_available() is True


class TestKISClient:
    """KISClient 테스트."""

    def _make_client(self) -> tuple[KISClient, AsyncMock, RateLimiter]:
        """테스트용 클라이언트를 생성한다."""
        mock_auth = AsyncMock()
        mock_auth.get_access_token.return_value = "test_token"
        mock_auth.get_hashkey.return_value = "test_hash"

        limiter = RateLimiter(per_second=100, daily_limit=10000)
        client = KISClient(auth=mock_auth, limiter=limiter)
        return client, mock_auth, limiter

    @patch("src.api.client.httpx.AsyncClient")
    async def test_get_success(self, mock_client_cls: AsyncMock) -> None:
        """GET 요청이 정상적으로 동작한다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"output": {"price": "50000"}}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_http

        client, _, _ = self._make_client()
        result = await client.get("/test/path", tr_id="TEST001")

        assert result == {"output": {"price": "50000"}}

    @patch("src.api.client.httpx.AsyncClient")
    async def test_post_with_hashkey(self, mock_client_cls: AsyncMock) -> None:
        """POST 요청 시 hashkey가 헤더에 포함된다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"rt_cd": "0"}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_http

        client, mock_auth, _ = self._make_client()
        result = await client.post(
            "/test/order", body={"key": "val"}, tr_id="ORDER01", use_hashkey=True
        )

        assert result == {"rt_cd": "0"}
        mock_auth.get_hashkey.assert_called_once()

    @patch("src.api.client.httpx.AsyncClient")
    async def test_retry_on_5xx(self, mock_client_cls: AsyncMock) -> None:
        """5xx 에러 시 재시도한다."""
        response_500 = MagicMock()
        response_500.status_code = 500
        response_500.text = "Internal Server Error"
        response_500.headers = {}

        response_200 = MagicMock()
        response_200.status_code = 200
        response_200.json.return_value = {"ok": True}

        mock_http = AsyncMock()
        mock_http.request.side_effect = [response_500, response_200]
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_http

        client, _, _ = self._make_client()
        result = await client.get("/test")

        assert result == {"ok": True}
        assert mock_http.request.call_count == 2

    @patch("src.api.client.httpx.AsyncClient")
    async def test_raises_on_4xx(self, mock_client_cls: AsyncMock) -> None:
        """4xx 에러 시 즉시 예외가 발생한다."""
        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.headers = {}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_http

        client, _, _ = self._make_client()

        with pytest.raises(KISAutoTraderError, match="API 에러"):
            await client.get("/test")

    @patch("src.api.client.httpx.AsyncClient")
    async def test_circuit_breaker_blocks_after_failures(
        self, mock_client_cls: AsyncMock
    ) -> None:
        """서킷 브레이커가 연속 실패 후 요청을 차단한다."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Error"
        mock_response.headers = {}

        mock_http = AsyncMock()
        mock_http.request.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_http

        client, _, _ = self._make_client()

        # 첫 요청: 3회 재시도 후 실패 (서킷 브레이커에 3회 실패 기록)
        with pytest.raises(KISAutoTraderError, match="최대 재시도"):
            await client.get("/test")

        # 추가 실패를 누적하여 서킷 브레이커 임계값에 도달
        # (이전 요청에서 3회 실패가 기록됨, 총 5회 필요하므로 2회 더)
        with pytest.raises(KISAutoTraderError):
            await client.get("/test")

        # 서킷 브레이커가 열린 상태에서 즉시 차단
        assert client.circuit_breaker.is_open is True
