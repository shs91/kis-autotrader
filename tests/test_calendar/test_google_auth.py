"""GoogleCalendarAuth 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.calendar.google_auth import GoogleCalendarAuth, SCOPES
from src.utils.exceptions import CalendarError


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    """테스트용 credentials/token 경로를 반환한다."""
    creds_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"
    return creds_path, token_path


class TestLoadToken:
    """토큰 파일 로드 테스트."""

    def test_load_existing_valid_token(self, tmp_paths: tuple[Path, Path]) -> None:
        """유효한 토큰 파일이 존재하면 인증에 성공한다."""
        creds_path, token_path = tmp_paths
        token_path.write_text("{}")  # 토큰 파일 존재

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False

        with patch(
            "src.calendar.google_auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ):
            auth = GoogleCalendarAuth(
                credentials_path=creds_path, token_path=token_path
            )
            result = auth.authenticate()

        assert result is mock_creds

    def test_no_token_file_triggers_auth_flow(
        self, tmp_paths: tuple[Path, Path]
    ) -> None:
        """토큰 파일이 없으면 OAuth2 인증 플로우를 실행한다."""
        creds_path, token_path = tmp_paths
        creds_path.write_text('{"installed": {}}')  # credentials.json 존재

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = "{}"

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch(
            "src.calendar.google_auth.InstalledAppFlow.from_client_secrets_file",
            return_value=mock_flow,
        ):
            auth = GoogleCalendarAuth(
                credentials_path=creds_path, token_path=token_path
            )
            result = auth.authenticate()

        assert result is mock_creds


class TestRefreshToken:
    """토큰 갱신 테스트."""

    def test_expired_token_is_refreshed(self, tmp_paths: tuple[Path, Path]) -> None:
        """만료된 토큰은 자동으로 갱신된다."""
        creds_path, token_path = tmp_paths
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token_value"
        mock_creds.to_json.return_value = "{}"

        # refresh 호출 후 valid=True로 변경
        def do_refresh(request: object) -> None:
            mock_creds.valid = True

        mock_creds.refresh.side_effect = do_refresh

        with patch(
            "src.calendar.google_auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ):
            auth = GoogleCalendarAuth(
                credentials_path=creds_path, token_path=token_path
            )
            result = auth.authenticate()

        mock_creds.refresh.assert_called_once()
        assert result is mock_creds

    def test_refresh_failure_raises_calendar_error(
        self, tmp_paths: tuple[Path, Path]
    ) -> None:
        """토큰 갱신 실패 시 CalendarError가 발생한다."""
        creds_path, token_path = tmp_paths
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token_value"
        mock_creds.refresh.side_effect = Exception("네트워크 오류")

        with (
            patch(
                "src.calendar.google_auth.Credentials.from_authorized_user_file",
                return_value=mock_creds,
            ),
            pytest.raises(CalendarError, match="토큰 갱신 실패"),
        ):
            auth = GoogleCalendarAuth(
                credentials_path=creds_path, token_path=token_path
            )
            auth.authenticate()


class TestCredentialsMissing:
    """credentials.json 누락 테스트."""

    def test_no_credentials_file_raises_error(
        self, tmp_paths: tuple[Path, Path]
    ) -> None:
        """credentials.json이 없으면 CalendarError가 발생한다."""
        creds_path, token_path = tmp_paths
        # credentials.json, token.json 모두 없음

        with pytest.raises(CalendarError, match="자격증명 파일을 찾을 수 없습니다"):
            auth = GoogleCalendarAuth(
                credentials_path=creds_path, token_path=token_path
            )
            auth.authenticate()


class TestGetService:
    """서비스 빌드 테스트."""

    def test_get_service_builds_calendar_resource(
        self, tmp_paths: tuple[Path, Path]
    ) -> None:
        """get_service()가 Calendar API 서비스를 반환한다."""
        creds_path, token_path = tmp_paths
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = True

        mock_service = MagicMock()

        with (
            patch(
                "src.calendar.google_auth.Credentials.from_authorized_user_file",
                return_value=mock_creds,
            ),
            patch(
                "src.calendar.google_auth.build",
                return_value=mock_service,
            ) as mock_build,
        ):
            auth = GoogleCalendarAuth(
                credentials_path=creds_path, token_path=token_path
            )
            service = auth.get_service()

        mock_build.assert_called_once_with(
            "calendar", "v3", credentials=mock_creds
        )
        assert service is mock_service
