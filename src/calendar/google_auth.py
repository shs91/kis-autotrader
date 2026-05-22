"""Google OAuth2 인증 모듈."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from src.config import settings
from src.utils.exceptions import CalendarError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

SCOPES: list[str] = ["https://www.googleapis.com/auth/calendar.events"]


class GoogleCalendarAuth:
    """Google Calendar OAuth2 인증을 관리한다."""

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
    ) -> None:
        """GoogleCalendarAuth를 초기화한다.

        Args:
            credentials_path: OAuth2 클라이언트 자격증명 파일 경로.
                None이면 설정값 사용.
            token_path: 저장된 토큰 파일 경로. None이면 설정값 사용.
        """
        self._credentials_path = credentials_path or settings.calendar.credentials_path
        self._token_path = token_path or settings.calendar.token_path
        self._credentials: Credentials | None = None

    def authenticate(self) -> Credentials:
        """Google OAuth2 인증을 수행하고 자격증명을 반환한다.

        저장된 토큰이 있으면 로드하고, 만료된 경우 자동으로 갱신한다.
        토큰이 없으면 OAuth2 인증 플로우를 실행한다.

        Returns:
            유효한 Google OAuth2 자격증명 객체.

        Raises:
            CalendarError: 인증에 실패한 경우.
        """
        try:
            creds = self._load_token()

            if creds and creds.valid:
                logger.info("기존 토큰으로 인증 성공")
                self._credentials = creds
                return creds

            if creds and creds.expired and creds.refresh_token:
                try:
                    creds = self._refresh_token(creds)
                    self._credentials = creds
                    return creds
                except CalendarError:
                    logger.warning("토큰 갱신 실패, 재인증 플로우 실행")
                    creds = None

            # 새로운 인증 플로우 실행
            creds = self._run_auth_flow()
            self._credentials = creds
            return creds

        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Google Calendar 인증 실패: {e}") from e

    def get_service(self) -> Resource:
        """Google Calendar API v3 서비스 인스턴스를 생성하여 반환한다.

        Returns:
            Google Calendar API 서비스 리소스 객체.

        Raises:
            CalendarError: 서비스 생성에 실패한 경우.
        """
        try:
            if self._credentials is None or not self._credentials.valid:
                self.authenticate()

            service: Resource = build("calendar", "v3", credentials=self._credentials)
            logger.info("Google Calendar API 서비스 빌드 완료")
            return service

        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Google Calendar 서비스 생성 실패: {e}") from e

    def _load_token(self) -> Credentials | None:
        """저장된 토큰 파일에서 자격증명을 로드한다.

        Returns:
            로드된 자격증명 또는 파일이 없으면 None.
        """
        if not self._token_path.exists():
            logger.info("저장된 토큰 파일이 없습니다: %s", self._token_path)
            return None

        try:
            # google-auth 일부 메서드는 타입 미제공 → cast으로 반환 타입 명시
            creds = cast(
                Credentials,
                Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                    str(self._token_path), SCOPES
                ),
            )
            logger.info("토큰 파일 로드 성공: %s", self._token_path)
            return creds
        except Exception as e:
            logger.warning("토큰 파일 로드 실패, 새 인증 필요: %s", e)
            return None

    def _refresh_token(self, creds: Credentials) -> Credentials:
        """만료된 토큰을 갱신한다.

        Args:
            creds: 만료된 자격증명.

        Returns:
            갱신된 자격증명.

        Raises:
            CalendarError: 토큰 갱신에 실패한 경우.
        """
        try:
            creds.refresh(Request())
            self._save_token(creds)
            logger.info("토큰 갱신 성공")
            return creds
        except Exception as e:
            raise CalendarError(f"토큰 갱신 실패: {e}") from e

    def _run_auth_flow(self) -> Credentials:
        """OAuth2 인증 플로우를 실행한다.

        Returns:
            새로 발급받은 자격증명.

        Raises:
            CalendarError: credentials.json 파일이 없거나 인증에 실패한 경우.
        """
        if not self._credentials_path.exists():
            raise CalendarError(
                f"OAuth2 자격증명 파일을 찾을 수 없습니다: {self._credentials_path}. "
                "Google Cloud Console에서 credentials.json을 다운로드하세요."
            )

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._credentials_path), SCOPES
            )
            creds = cast(Credentials, flow.run_local_server(port=0))
            self._save_token(creds)
            logger.info("새 OAuth2 인증 완료")
            return creds
        except Exception as e:
            raise CalendarError(f"OAuth2 인증 플로우 실패: {e}") from e

    def _save_token(self, creds: Credentials) -> None:
        """자격증명을 토큰 파일로 저장한다.

        Args:
            creds: 저장할 자격증명.
        """
        try:
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            # google-auth to_json은 타입 미제공 → cast으로 str 명시
            self._token_path.write_text(
                cast(str, creds.to_json())  # type: ignore[no-untyped-call]
            )
            logger.info("토큰 저장 완료: %s", self._token_path)
        except Exception as e:
            logger.warning("토큰 파일 저장 실패: %s", e)
