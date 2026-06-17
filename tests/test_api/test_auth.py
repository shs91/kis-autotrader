"""KISAuth 토큰 발급/갱신 테스트."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.auth import KISAuth, TokenInfo, _parse_expires
from src.utils.exceptions import AuthenticationError


@pytest.fixture(autouse=True)
def _isolate_token_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """토큰 캐시를 테스트별 tmp 디렉토리로 격리(실제 .kis_tokens 오염·flaky 방지)."""
    monkeypatch.setenv("KIS_TOKEN_CACHE_DIR", str(tmp_path / "kis_tokens"))


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


class TestTokenCache:
    """디스크 토큰 캐시 (1일 1회 발급 원칙 — 재시작 시 재발급 회피)."""

    @staticmethod
    def _mock_client(mock_client_cls: AsyncMock, token: str) -> AsyncMock:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": token,
            "access_token_token_expired": "2099-12-31 23:59:59",
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client
        return mock_client

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_issue_saves_token_to_cache(self, mock_client_cls: AsyncMock) -> None:
        """발급 시 토큰이 디스크 캐시에 저장된다."""
        self._mock_client(mock_client_cls, "tok_save")
        auth = KISAuth()
        await auth.get_access_token()
        assert auth._cache_path.exists()
        data = json.loads(auth._cache_path.read_text(encoding="utf-8"))
        assert data["access_token"] == "tok_save"

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_valid_cache_skips_reissue(self, mock_client_cls: AsyncMock) -> None:
        """유효 캐시가 있으면 재시작(새 인스턴스)해도 재발급하지 않는다."""
        mock_client = self._mock_client(mock_client_cls, "should_not_issue")
        # 이전 프로세스가 발급해 캐시에 남긴 유효 토큰을 모사
        auth0 = KISAuth()
        auth0._cache_path.parent.mkdir(parents=True, exist_ok=True)
        auth0._cache_path.write_text(
            json.dumps({
                "access_token": "cached_tok",
                "expires_at": (
                    datetime.datetime.now() + datetime.timedelta(hours=10)
                ).isoformat(),
            }),
            encoding="utf-8",
        )
        # 새 인스턴스(재시작 모사)
        token = await KISAuth().get_access_token()
        assert token == "cached_tok"
        mock_client.post.assert_not_called()  # 발급 호출 없음

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_expired_cache_triggers_reissue(
        self, mock_client_cls: AsyncMock
    ) -> None:
        """만료(갱신필요) 캐시면 재발급한다."""
        mock_client = self._mock_client(mock_client_cls, "fresh_tok")
        auth0 = KISAuth()
        auth0._cache_path.parent.mkdir(parents=True, exist_ok=True)
        auth0._cache_path.write_text(
            json.dumps({
                "access_token": "old_tok",
                "expires_at": (
                    datetime.datetime.now() - datetime.timedelta(hours=1)
                ).isoformat(),
            }),
            encoding="utf-8",
        )
        token = await KISAuth().get_access_token()
        assert token == "fresh_tok"
        mock_client.post.assert_called_once()

    def test_cache_path_separates_by_appkey(self) -> None:
        """서로 다른 앱키는 다른 캐시 파일(국내/미국 분리)."""
        from src.api.auth import _token_cache_path

        assert _token_cache_path("KEY_A") != _token_cache_path("KEY_B")
        assert _token_cache_path("KEY_A") == _token_cache_path("KEY_A")


class TestTokenRefreshFallback:
    """장중 갱신 실패 시 유효 토큰 폴백 + 재시도 쓰로틀."""

    @staticmethod
    def _failing_client(mock_client_cls: AsyncMock) -> AsyncMock:
        """토큰 발급(POST)이 실패(500)하는 클라이언트 mock."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client
        return mock_client

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_refresh_failure_falls_back_to_valid_token(
        self, mock_client_cls: AsyncMock
    ) -> None:
        """갱신(should_refresh) 실패 시 아직 유효한 기존 토큰으로 폴백한다."""
        mock_client = self._failing_client(mock_client_cls)
        auth = KISAuth()
        # 만료 30분 전(should_refresh=True) 이지만 아직 유효한 토큰
        auth._token_info = TokenInfo(
            access_token="still_valid",
            expires_at=datetime.datetime.now() + datetime.timedelta(minutes=30),
        )
        token = await auth.get_access_token()
        assert token == "still_valid"  # 폴백 — 예외 없음
        mock_client.post.assert_called_once()  # 갱신 시도는 했음

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_refresh_failure_no_valid_token_raises(
        self, mock_client_cls: AsyncMock
    ) -> None:
        """유효 토큰이 없는데 발급 실패하면 예외를 전파한다."""
        self._failing_client(mock_client_cls)
        auth = KISAuth()  # 토큰 없음
        with pytest.raises(AuthenticationError):
            await auth.get_access_token()

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_refresh_throttled_after_failure(
        self, mock_client_cls: AsyncMock
    ) -> None:
        """갱신 실패 후 재시도 간격 내 호출은 발급을 재시도하지 않는다(과부하 방지)."""
        mock_client = self._failing_client(mock_client_cls)
        auth = KISAuth()
        auth._token_info = TokenInfo(
            access_token="still_valid",
            expires_at=datetime.datetime.now() + datetime.timedelta(minutes=30),
        )
        await auth.get_access_token()  # 1회차: 발급 시도(실패)→폴백→쓰로틀 설정
        await auth.get_access_token()  # 2회차: 쓰로틀 — 발급 미시도, 기존 토큰 사용
        assert mock_client.post.call_count == 1

    @patch("src.api.auth.httpx.AsyncClient")
    async def test_retries_after_throttle_window(
        self, mock_client_cls: AsyncMock
    ) -> None:
        """쓰로틀 만료 후에는 갱신을 재시도한다."""
        mock_client = self._failing_client(mock_client_cls)
        auth = KISAuth()
        auth._token_info = TokenInfo(
            access_token="still_valid",
            expires_at=datetime.datetime.now() + datetime.timedelta(minutes=30),
        )
        await auth.get_access_token()  # 실패→쓰로틀
        # 쓰로틀 만료를 과거로 강제(시간 경과 모사)
        auth._refresh_retry_after = datetime.datetime.now() - datetime.timedelta(seconds=1)
        await auth.get_access_token()  # 재시도
        assert mock_client.post.call_count == 2
