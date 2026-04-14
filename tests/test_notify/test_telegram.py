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

            await notifier.send("테스트 메시지")

    async def test_send_missing_token(self) -> None:
        """토큰 미설정 시 요청을 하지 않는다."""
        notifier = _make_notifier(token="")
        await notifier.send("테스트 메시지")

    async def test_send_missing_chat_id(self) -> None:
        """채팅ID 미설정 시 요청을 하지 않는다."""
        notifier = _make_notifier(chat_id="")
        await notifier.send("테스트 메시지")

    async def test_notify_buy_basic(self) -> None:
        """notify_buy가 기본 매수 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_buy("삼성전자", "005930", 10, 72000)
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "매수" in msg
        assert "삼성전자" in msg
        assert "720,000" in msg

    async def test_notify_buy_with_strategy(self) -> None:
        """notify_buy가 전략/시그널 정보를 포함한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_buy(
            "삼성전자", "005930", 10, 72000,
            strategy="이동평균교차(5/20)",
            reason="골든크로스",
            confidence=0.75,
        )
        msg = notifier.send.call_args[0][0]
        assert "이동평균교차" in msg
        assert "골든크로스" in msg

    async def test_notify_sell_stop_loss_is_urgent(self) -> None:
        """손절 매도는 urgent=True로 전송된다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_sell("SK하이닉스", "000660", 5, 185000, "손절")
        notifier.send.assert_called_once()
        assert notifier.send.call_args[1]["urgent"] is True

    async def test_notify_sell_take_profit_is_not_urgent(self) -> None:
        """익절 매도는 urgent=False로 전송된다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_sell("NAVER", "035420", 3, 400000, "익절")
        notifier.send.assert_called_once()
        assert notifier.send.call_args[1]["urgent"] is False

    async def test_notify_sell_with_avg_price(self) -> None:
        """매도 시 매입가/손익 정보가 포함된다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_sell(
            "SK하이닉스", "000660", 5, 185000, "익절", avg_price=170000.0,
        )
        msg = notifier.send.call_args[0][0]
        assert "170,000" in msg
        assert "+75,000" in msg

    async def test_notify_daily_summary_basic(self) -> None:
        """notify_daily_summary가 기본 결산 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_daily_summary("2026-04-03", 3, 15200, 0.3)
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "일일 결산" in msg

    async def test_notify_daily_summary_with_details(self) -> None:
        """notify_daily_summary가 상세 정보를 포함한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_daily_summary(
            "2026-04-03", 3, 15200, 0.3,
            buy_count=2, sell_count=1,
        )
        msg = notifier.send.call_args[0][0]
        assert "매수 2" in msg
        assert "매도 1" in msg

    async def test_notify_error_is_urgent(self) -> None:
        """에러 알림은 urgent=True로 전송된다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_error("테스트", "에러 발생")
        notifier.send.assert_called_once()
        assert notifier.send.call_args[1]["urgent"] is True

    async def test_notify_buy_is_not_urgent(self) -> None:
        """매수 알림은 urgent=False(무음)로 전송된다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_buy("삼성전자", "005930", 10, 72000)
        call_kwargs = notifier.send.call_args[1] if notifier.send.call_args[1] else {}
        assert call_kwargs.get("urgent", False) is False

    async def test_notify_system(self) -> None:
        """notify_system이 시스템 메시지를 전송한다."""
        notifier = _make_notifier()
        notifier.send = AsyncMock()  # type: ignore[method-assign]
        await notifier.notify_system("시스템 가동")
        notifier.send.assert_called_once()
        msg = notifier.send.call_args[0][0]
        assert "시스템" in msg
