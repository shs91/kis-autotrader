"""KISAuth 토큰 발급/갱신 테스트."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.api.auth import KISAuth, TokenInfo, _parse_expires
from src.utils.exceptions import AuthenticationError


class TestTokenInfo:
    """TokenInfo 데이터 클래스 테스트."""

    def test_is_expired_true(self) -> None:
        """만료된 토큰을 정확히 감지한다."""
        token = TokenInfo(
            access_token="test",
            expires_at=datetime.datetime.now() - datetime.timedelta(hours=1),
        )
        assert token.is_expired is True

    def test_is_expired_false(self) -> None:
        """유효한 토큰을 정확히 감지한다."""
        token = TokenInfo(
            access_token="test",
            expires_at=datetime.datetime.now() + datetime.timedelta(hours=2),
        )
        assert token.is_expired is False

    def test_should_refresh_true(self) -> None:
        """갱신이 필요한 토큰을 정확히 감지한다 (만료 1시간 이내)."""
        token = TokenInfo(
            access_token="test",
            expires_at=datetime.datetime.now() + datetime.timedelta(minutes=30),
        )
        assert token.should_refresh is True

    def test_should_refresh_false(self) -> None:
        """갱신이 불필요한 토큰을 정확히 감지한다."""
        token = TokenInfo(
            access_token="test",
            expires_at=datetime.datetime.now() + datetime.timedelta(hours=12),
        )
        assert token.should_refresh is False


class TestParseExpires:
    """만료 시간 파싱 테스트."""

    def test_valid_format(self) -> None:
        """정상 형식의 만료 시간을 파싱한다."""
        result = _parse_expires("2026-03-31 12:00:00")
        assert result == datetime.datetime(2026, 3, 31, 12, 0, 0)

    def test_empty_string(self) -> None:
        """빈 문자열이면 24시간 후를 반환한다."""
        result = _parse_expires("")
        assert result > datetime.datetime.now()

    def test_invalid_format(self) -> None:
        """잘못된 형식이면 24시간 후를 반환한다."""
        result = _parse_expires("invalid-format")
        assert result > datetime.datetime.now()


class TestKISAuth:
    """KISAuth 인증 테스트."""

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_get_access_token_success(self, mock_client_cls: AsyncMock) -> None:
        """토큰 발급이 정상적으로 동작한다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_token_12345",
            "access_token_token_expired": "2026-12-31 23:59:59",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        auth = KISAuth()
        token = await auth.get_access_token()

        assert token == "test_token_12345"
        assert auth.token_info is not None
        assert auth.token_info.access_token == "test_token_12345"

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_get_access_token_failure(self, mock_client_cls: AsyncMock) -> None:
        """토큰 발급 실패 시 AuthenticationError가 발생한다."""
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        auth = KISAuth()

        with pytest.raises(AuthenticationError, match="토큰 발급 실패"):
            await auth.get_access_token()

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_token_reuse_when_valid(self, mock_client_cls: AsyncMock) -> None:
        """유효한 토큰이 있으면 재발급하지 않는다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "token_abc",
            "access_token_token_expired": "2099-12-31 23:59:59",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        auth = KISAuth()

        token1 = await auth.get_access_token()
        token2 = await auth.get_access_token()

        assert token1 == token2
        # post는 1번만 호출되어야 함
        assert mock_client.post.call_count == 1

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_get_hashkey_success(self, mock_client_cls: AsyncMock) -> None:
        """hashkey 발급이 정상적으로 동작한다."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"HASH": "abc123hash"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        auth = KISAuth()
        hashkey = await auth.get_hashkey({"key": "value"})

        assert hashkey == "abc123hash"

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_get_hashkey_failure(self, mock_client_cls: AsyncMock) -> None:
        """hashkey 발급 실패 시 AuthenticationError가 발생한다."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        auth = KISAuth()

        with pytest.raises(AuthenticationError, match="hashkey 발급 실패"):
            await auth.get_hashkey({"key": "value"})
