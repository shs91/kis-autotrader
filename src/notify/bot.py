"""Telegram Bot 명령어 처리 모듈.

getUpdates 롱 폴링으로 명령을 수신하고 응답한다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import httpx

from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

GET_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"
SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
POLL_TIMEOUT = 30
REQUEST_TIMEOUT = 35.0

# 콜백 타입: 명령 이름 → (args) → 응답 문자열
CommandHandler = Callable[[str], Coroutine[Any, Any, str]]


class TelegramBot:
    """Telegram Bot 명령을 수신하고 응답한다.

    getUpdates 롱 폴링 방식으로 동작하며, asyncio 태스크로 백그라운드 실행된다.
    """

    def __init__(self) -> None:
        """TelegramBot을 초기화한다."""
        self._token = settings.telegram.bot_token
        self._chat_id = settings.telegram.chat_id
        self._enabled = settings.telegram.enabled
        self._offset = 0
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._commands: dict[str, CommandHandler] = {}

    def register(self, command: str, handler: CommandHandler) -> None:
        """명령 핸들러를 등록한다.

        Args:
            command: 명령 이름 (슬래시 제외, 예: "status")
            handler: 명령 처리 코루틴 (인자: 명령 뒤 텍스트 → 반환: 응답 메시지)
        """
        self._commands[command] = handler

    async def start(self) -> None:
        """폴링 루프를 백그라운드 태스크로 시작한다."""
        if not self._enabled or not self._token:
            logger.info("Telegram Bot 비활성화 (설정 미완료)")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram Bot 시작 (명령: %s)", list(self._commands.keys()))

    async def stop(self) -> None:
        """폴링 루프를 중단한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Telegram Bot 종료")

    async def _poll_loop(self) -> None:
        """getUpdates 롱 폴링 루프."""
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._handle_update(update)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Bot 폴링 에러, 5초 후 재시도")
                await asyncio.sleep(5)

    async def _get_updates(self) -> list[dict[str, Any]]:
        """Telegram getUpdates를 호출한다."""
        url = GET_UPDATES_URL.format(token=self._token)
        params = {
            "offset": self._offset,
            "timeout": POLL_TIMEOUT,
            "allowed_updates": json.dumps(["message"]),
        }
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                return []
            data = response.json()
            return data.get("result", [])

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """개별 업데이트를 처리한다."""
        update_id = update.get("update_id", 0)
        self._offset = max(self._offset, update_id + 1)

        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()

        # 등록된 chat_id에서 온 메시지만 처리
        if chat_id != self._chat_id:
            return

        if not text.startswith("/"):
            return

        parts = text.split(maxsplit=1)
        command = parts[0].lstrip("/").split("@")[0]  # /status@botname → status
        args = parts[1] if len(parts) > 1 else ""

        handler = self._commands.get(command)
        if handler is None:
            cmds = ", /".join(self._commands.keys())
            await self._reply(chat_id, f"알 수 없는 명령: /{command}\n사용 가능: /{cmds}")
            return

        try:
            response_text = await handler(args)
            await self._reply(chat_id, response_text)
        except Exception as e:
            logger.exception("명령 처리 실패: /%s", command)
            await self._reply(chat_id, f"명령 처리 실패: {e!s:.100}")

    async def _reply(self, chat_id: str, text: str) -> None:
        """메시지를 응답한다."""
        try:
            url = SEND_MESSAGE_URL.format(token=self._token)
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=payload)
        except Exception:
            logger.debug("Bot 응답 전송 실패")
