"""KIS OpenAPI OAuth 인증 및 토큰 관리 모듈."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx

from src.config import settings
from src.utils.exceptions import AuthenticationError, TokenExpiredError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 토큰 캐시 디렉토리. KIS 토큰은 24시간 유효하고 **1일 1회 발급이 원칙**(잦은 재발급 시
# 이용 제한)이므로, 프로세스 재시작마다 재발급하지 않도록 디스크에 캐시해 24시간 재사용한다.
# 앱키별 파일로 분리 → 국내(KIS_)/미국(KIS_US_)이 다른 앱키면 자연 분리, 같은 앱키면 공유
# (국내·미국 프로세스가 하루 1개 토큰을 공유). 경로는 KIS_TOKEN_CACHE_DIR로 오버라이드 가능.


def _token_cache_dir() -> Path:
    """토큰 캐시 디렉토리(KIS_TOKEN_CACHE_DIR env 우선, 기본 프로젝트 루트 .kis_tokens)."""
    override = os.getenv("KIS_TOKEN_CACHE_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / ".kis_tokens"


def _token_cache_path(app_key: str) -> Path:
    """앱키 해시 기반 토큰 캐시 파일 경로(앱키 노출 방지)."""
    digest = hashlib.sha256(app_key.encode("utf-8")).hexdigest()[:16]
    return _token_cache_dir() / f"{digest}.json"


# 갱신 실패 후 재시도 최소 간격 — 반복 실패 시 토큰 엔드포인트 과부하(1일 1회 발급
# 원칙) 방지. 이 간격 동안엔 아직 유효한 기존 토큰을 계속 사용한다.
_REFRESH_RETRY_INTERVAL = datetime.timedelta(seconds=60)


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
        self._cache_path = _token_cache_path(self._app_key)
        self._lock = asyncio.Lock()
        # 갱신 실패 후 재시도 가능 시각(쓰로틀). None이면 즉시 재시도 가능.
        self._refresh_retry_after: datetime.datetime | None = None

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
            # 디스크 캐시 우선 로드 — 프로세스 재시작 시 유효 토큰을 재사용해 재발급 회피.
            if self._token_info is None:
                self._token_info = self._load_from_cache()

            if self._token_info is None or self._token_info.should_refresh:
                await self._refresh_token()

            if self._token_info is None:
                raise AuthenticationError("토큰 발급에 실패했습니다.")

            if self._token_info.is_expired:
                raise TokenExpiredError("토큰이 만료되었습니다. 재발급이 필요합니다.")

            return self._token_info.access_token

    async def _refresh_token(self) -> None:
        """토큰을 발급/갱신하되, 실패 시 아직 유효한 기존 토큰으로 폴백한다.

        장중 만료 1시간 전(should_refresh) 갱신이 네트워크/발급 제한으로 실패해도,
        기존 토큰이 아직 유효하면 계속 사용하고 다음 호출에서 재시도한다(즉시 매매
        중단 방지). 반복 실패 시 토큰 엔드포인트 과부하(1일 1회 발급 원칙)를 막기 위해
        재시도를 _REFRESH_RETRY_INTERVAL 간격으로 쓰로틀한다. 유효 토큰이 전혀 없으면
        (None/만료) 발급 실패를 그대로 전파한다.
        """
        now = datetime.datetime.now()
        # 쓰로틀: 직전 발급 실패 후 재시도 간격 내면 발급 시도를 생략한다.
        # (기존 토큰을 유지 — 유효하면 호출부가 사용, 만료/없음이면 호출부 가드가 처리)
        if self._refresh_retry_after is not None and now < self._refresh_retry_after:
            return

        try:
            await self._issue_token()
            self._refresh_retry_after = None  # 성공 — 쓰로틀 해제
        except Exception as exc:
            self._refresh_retry_after = now + _REFRESH_RETRY_INTERVAL
            # 아직 유효한 기존 토큰이 있으면 폴백(다음 호출에서 재발급 재시도).
            if self._token_info is not None and not self._token_info.is_expired:
                logger.warning(
                    "토큰 갱신 실패 — 유효한 기존 토큰으로 폴백(%d초 후 재시도): %s",
                    int(_REFRESH_RETRY_INTERVAL.total_seconds()),
                    exc,
                )
                return
            raise  # 유효 토큰 없음 → 발급 실패 전파

    async def _issue_token(self) -> None:
        """OAuth 토큰을 발급받는다.

        발급 직전 디스크 캐시를 한 번 더 확인해, 다른 프로세스(동일 앱키)가 방금
        유효 토큰을 발급·캐시했으면 재사용한다(KIS 1일 1회 발급 원칙 — 중복 발급 회피).

        Raises:
            AuthenticationError: 토큰 발급 요청 실패 시
        """
        cached = self._load_from_cache()
        if cached is not None and not cached.should_refresh:
            self._token_info = cached
            logger.info(
                "OAuth 토큰 캐시 재사용 (만료: %s)", cached.expires_at.isoformat()
            )
            return

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
            self._save_to_cache(self._token_info)

            logger.info("OAuth 토큰 발급 성공 (만료: %s)", expires_at.isoformat())

        except httpx.HTTPError as e:
            raise AuthenticationError(f"토큰 발급 요청 중 네트워크 에러: {e}") from e

    def _load_from_cache(self) -> TokenInfo | None:
        """디스크 캐시에서 토큰을 로드한다. 없거나 파싱 불가 시 None."""
        try:
            if not self._cache_path.exists():
                return None
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            token = data.get("access_token")
            expires_raw = data.get("expires_at")
            if not token or not expires_raw:
                return None
            expires_at = datetime.datetime.fromisoformat(expires_raw)
            return TokenInfo(access_token=token, expires_at=expires_at)
        except Exception:
            logger.debug("토큰 캐시 로드 실패 — 무시하고 발급 진행")
            return None

    def _save_to_cache(self, token: TokenInfo) -> None:
        """토큰을 디스크 캐시에 원자적으로 저장한다(임시파일+rename). 실패해도 무시."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({
                "access_token": token.access_token,
                "expires_at": token.expires_at.isoformat(),
            })
            tmp = self._cache_path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._cache_path)  # 원자적 교체
            os.chmod(self._cache_path, 0o600)  # 토큰 파일 권한 제한
        except Exception:
            logger.warning("토큰 캐시 저장 실패 (매매에 영향 없음)")

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
            hashkey = cast(str, data.get("HASH", ""))
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
