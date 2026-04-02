"""KIS OpenAPI OAuth 인증 및 토큰 관리 모듈."""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass

import httpx

from src.config import settings
from src.utils.exceptions import AuthenticationError, TokenExpiredError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class TokenInfo:
    """OAuth 토큰 정보."""

    access_token: str
    expires_at: datetime.datetime

    @property
    def is_expired(self) -> bool:
        """토큰이 만료되었는지 확인한다."""
        return datetime.datetime.now() >= self.expires_at

    @property
    def should_refresh(self) -> bool:
        """토큰 갱신이 필요한지 확인한다 (만료 1시간 전)."""
        refresh_threshold = self.expires_at - datetime.timedelta(hours=1)
        return datetime.datetime.now() >= refresh_threshold


class KISAuth:
    """KIS OpenAPI OAuth 인증을 관리한다."""

    def __init__(self) -> None:
        """KISAuth를 초기화한다."""
        self._app_key = settings.kis.app_key
        self._app_secret = settings.kis.app_secret
        self._base_url = settings.kis.base_url
        self._token_info: TokenInfo | None = None
        self._lock = asyncio.Lock()

        logger.info("KISAuth 초기화 완료 (환경: %s)", settings.kis.env)

    async def get_access_token(self) -> str:
        """유효한 액세스 토큰을 반환한다.

        토큰이 없거나 갱신이 필요한 경우 자동으로 발급/갱신한다.

        Returns:
            유효한 액세스 토큰 문자열

        Raises:
            AuthenticationError: 토큰 발급 실패 시
            TokenExpiredError: 토큰이 만료되어 갱신 불가 시
        """
        async with self._lock:
            if self._token_info is None or self._token_info.should_refresh:
                await self._issue_token()

            if self._token_info is None:
                raise AuthenticationError("토큰 발급에 실패했습니다.")

            if self._token_info.is_expired:
                raise TokenExpiredError("토큰이 만료되었습니다. 재발급이 필요합니다.")

            return self._token_info.access_token

    async def _issue_token(self) -> None:
        """OAuth 토큰을 발급받는다.

        Raises:
            AuthenticationError: 토큰 발급 요청 실패 시
        """
        url = f"{self._base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
        }

        logger.info("OAuth 토큰 발급 요청: %s", url)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=body, timeout=10.0)

            if response.status_code != 200:
                raise AuthenticationError(
                    f"토큰 발급 실패 (status={response.status_code}): {response.text}"
                )

            data = response.json()
            access_token = data.get("access_token")
            token_expired = data.get("access_token_token_expired", "")

            if not access_token:
                raise AuthenticationError("응답에 access_token이 없습니다.")

            # 만료 시간 파싱 (형식: "2026-03-31 12:00:00")
            expires_at = _parse_expires(token_expired)

            self._token_info = TokenInfo(
                access_token=access_token,
                expires_at=expires_at,
            )

            logger.info("OAuth 토큰 발급 성공 (만료: %s)", expires_at.isoformat())

        except httpx.HTTPError as e:
            raise AuthenticationError(f"토큰 발급 요청 중 네트워크 에러: {e}") from e

    async def get_hashkey(self, body: dict[str, str | int]) -> str:
        """주문 요청에 필요한 hashkey를 발급받는다.

        Args:
            body: hashkey 생성 대상 요청 본문

        Returns:
            hashkey 문자열

        Raises:
            AuthenticationError: hashkey 발급 실패 시
        """
        url = f"{self._base_url}/uapi/hashkey"
        headers = {
            "content-Type": "application/json; charset=utf-8",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers=headers, json=body, timeout=10.0
                )

            if response.status_code != 200:
                raise AuthenticationError(
                    f"hashkey 발급 실패 (status={response.status_code}): {response.text}"
                )

            data = response.json()
            hashkey = data.get("HASH", "")
            if not hashkey:
                raise AuthenticationError("응답에 HASH 값이 없습니다.")

            return hashkey

        except httpx.HTTPError as e:
            raise AuthenticationError(f"hashkey 발급 요청 중 네트워크 에러: {e}") from e

    @property
    def token_info(self) -> TokenInfo | None:
        """현재 토큰 정보를 반환한다."""
        return self._token_info


def _parse_expires(token_expired: str) -> datetime.datetime:
    """만료 시간 문자열을 datetime으로 변환한다.

    Args:
        token_expired: 만료 시간 문자열 (형식: "2026-03-31 12:00:00")

    Returns:
        만료 시간 datetime 객체
    """
    if not token_expired:
        # 만료 시간이 없으면 24시간 후로 설정
        return datetime.datetime.now() + datetime.timedelta(hours=24)

    try:
        return datetime.datetime.strptime(token_expired, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        logger.warning("만료 시간 파싱 실패 (%s), 24시간 후로 설정", token_expired)
        return datetime.datetime.now() + datetime.timedelta(hours=24)
