"""TelegramBot 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock

from src.notify.bot import TelegramBot


def _make_bot() -> TelegramBot:
    """테스트용 봇을 생성한다."""
    bot = TelegramBot()
    object.__setattr__(bot, "_enabled", True)
    object.__setattr__(bot, "_token", "test-token")
    object.__setattr__(bot, "_chat_id", "12345")
    return bot


class TestTelegramBot:
    """TelegramBot 테스트."""

    async def test_register_and_handle_command(self) -> None:
        """등록된 명령이 올바르게 호출된다."""
        bot = _make_bot()

        handler = AsyncMock(return_value="응답 메시지")
        bot.register("test", handler)

        bot._reply = AsyncMock()  # type: ignore[method-assign]

        update = {
            "update_id": 1,
            "message": {
                "chat": {"id": 12345},
                "text": "/test 인자",
            },
        }
        await bot._handle_update(update)

        handler.assert_called_once_with("인자")
        bot._reply.assert_called_once_with("12345", "응답 메시지")

    async def test_unknown_command(self) -> None:
        """등록되지 않은 명령은 안내 메시지를 반환한다."""
        bot = _make_bot()
        bot.register("status", AsyncMock(return_value="ok"))
        bot._reply = AsyncMock()  # type: ignore[method-assign]

        update = {
            "update_id": 2,
            "message": {
                "chat": {"id": 12345},
                "text": "/unknown",
            },
        }
        await bot._handle_update(update)

        reply_text = bot._reply.call_args[0][1]
        assert "알 수 없는 명령" in reply_text

    async def test_ignores_other_chat_id(self) -> None:
        """다른 chat_id의 메시지는 무시한다."""
        bot = _make_bot()
        handler = AsyncMock(return_value="ok")
        bot.register("test", handler)

        update = {
            "update_id": 3,
            "message": {
                "chat": {"id": 99999},  # 다른 chat_id
                "text": "/test",
            },
        }
        await bot._handle_update(update)

        handler.assert_not_called()

    async def test_ignores_non_command(self) -> None:
        """슬래시로 시작하지 않는 메시지는 무시한다."""
        bot = _make_bot()
        handler = AsyncMock(return_value="ok")
        bot.register("test", handler)
        bot._reply = AsyncMock()  # type: ignore[method-assign]

        update = {
            "update_id": 4,
            "message": {
                "chat": {"id": 12345},
                "text": "일반 메시지",
            },
        }
        await bot._handle_update(update)

        handler.assert_not_called()
        bot._reply.assert_not_called()

    async def test_command_with_bot_mention(self) -> None:
        """/status@botname 형태도 처리한다."""
        bot = _make_bot()
        handler = AsyncMock(return_value="상태 응답")
        bot.register("status", handler)
        bot._reply = AsyncMock()  # type: ignore[method-assign]

        update = {
            "update_id": 5,
            "message": {
                "chat": {"id": 12345},
                "text": "/status@my_bot_name",
            },
        }
        await bot._handle_update(update)

        handler.assert_called_once_with("")
