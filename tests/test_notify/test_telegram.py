"""TelegramNotifier 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx

from src.notify.telegram import TelegramNotifier


def _make_notifier(
    *, enabled: bool = True, token: str = "test-token", chat_id: str = "12345"
) -> TelegramNotifier:
    """테스트용 TelegramNotifier를 생성한다."""
    notifier = TelegramNotifier()
    object.__setattr__(notifier, "_enabled", enabled)
    object.__setattr__(notifier, "_token", token)
    object.__setattr__(notifier, "_chat_id", chat_id)
    return notifier


class TestTelegramNotifier:
    """TelegramNotifier 테스트."""

    async def test_send_disabled_skips_request(self) -> None:
        """enabled=False면 HTTP 요청하지 않는다."""
        notifier = _make_notifier(enabled=False)
        # enabled=False인 경우 아무 일도 안 일어남 (예외 없음)
        await notifier.send("테스트 메시지")

    async def test_send_success(self) -> None:
        """정상 전송 시 200 응답을 처리한다."""
        notifier = _make_notifier()

        mock_response = httpx.Response(200, json={"ok": True})
        with patch("src.notify.telegram.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await notifier.send("테스트 메시지")
            mock_client.post.assert_called_once()

    async def test_send_failure_no_exception(self) -> None:
        """전송 실패해도 예외가 전파되지 않는다."""
        notifier = _make_notifier()

        with patch("src.notify.telegram.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("connection failed")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            # 예외가 전파되지 않아야 한다
            await notifier.send("테스트 메시지")

    async def test_send_missing_token(self) -> None:
        """토큰 미설정 시 요청을 하지 않는다."""
        notifier = _make_notifier(token="")
        # 토큰 없으면 요청 자체를 하지 않음 (예외 없음)
        await notifier.send("테스트 메시지")

    async def test_send_missing_chat_id(self) -> None:
        """채팅ID 미설정 시 요청을 하지 않는다."""
        notifier = _make_notifier(chat_id="")
        await notifier.send("테스트 메시지")

    async def test_notify_buy(self) -> None:
        """notify_buy가 포맷된 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_buy("삼성전자", "005930", 10, 72000)
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "매수" in msg
        assert "삼성전자" in msg

    async def test_notify_sell(self) -> None:
        """notify_sell이 포맷된 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_sell("SK하이닉스", "000660", 5, 185000, "손절")
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "손절" in msg

    async def test_notify_daily_summary(self) -> None:
        """notify_daily_summary가 결산 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_daily_summary("2026-04-03", 3, 15200, 0.3)
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "결산" in msg

    async def test_notify_error(self) -> None:
        """notify_error가 에러 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_error("테스트", "에러 발생")
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "에러" in msg

    async def test_notify_system(self) -> None:
        """notify_system이 시스템 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_system("시스템 가동")
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "시스템" in msg
