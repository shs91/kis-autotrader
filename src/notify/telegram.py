"""Telegram Bot API를 통한 알림 전송 모듈."""

from __future__ import annotations

import httpx

from src.config import settings
from src.notify.formatter import (
    format_buy,
    format_daily_summary,
    format_error,
    format_sell,
    format_system,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT = 10.0


class TelegramNotifier:
    """Telegram으로 알림을 전송한다.

    알림 전송 실패는 매매 로직에 영향을 주지 않는다.
    """

    def __init__(self) -> None:
        """TelegramNotifier를 초기화한다."""
        self._token = settings.telegram.bot_token
        self._chat_id = settings.telegram.chat_id
        self._enabled = settings.telegram.enabled

    async def send(self, message: str) -> None:
        """메시지를 전송한다. 실패해도 예외를 전파하지 않는다."""
        if not self._enabled:
            return
        if not self._token or not self._chat_id:
            logger.warning("Telegram 설정 미완료 (토큰 또는 채팅ID 없음), 알림 스킵")
            return
        try:
            url = SEND_MESSAGE_URL.format(token=self._token)
            payload = {
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(url, json=payload)
                if response.status_code != 200:
                    logger.warning(
                        "Telegram 전송 실패: status=%d, body=%s",
                        response.status_code,
                        response.text[:200],
                    )
        except Exception:
            logger.exception("Telegram 알림 전송 중 에러 (매매에 영향 없음)")

    async def notify_buy(
        self, stock_name: str, stock_code: str, quantity: int, price: int
    ) -> None:
        """매수 체결 알림을 전송한다."""
        await self.send(format_buy(stock_name, stock_code, quantity, price))

    async def notify_sell(
        self,
        stock_name: str,
        stock_code: str,
        quantity: int,
        price: int,
        reason: str,
    ) -> None:
        """매도 체결 알림을 전송한다."""
        await self.send(format_sell(stock_name, stock_code, quantity, price, reason))

    async def notify_daily_summary(
        self, trade_date: str, count: int, profit_loss: int, rate: float
    ) -> None:
        """일일 결산 알림을 전송한다."""
        await self.send(format_daily_summary(trade_date, count, profit_loss, rate))

    async def notify_error(self, context: str, error: str) -> None:
        """에러 알림을 전송한다."""
        await self.send(format_error(context, error))

    async def notify_system(self, message: str) -> None:
        """시스템 알림을 전송한다."""
        await self.send(format_system(message))
