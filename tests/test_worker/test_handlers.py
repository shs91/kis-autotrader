"""핸들러 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.worker.handlers import (
    CalendarEventHandler,
    DailySummaryHandler,
    TelegramNotifyHandler,
)


@pytest.mark.asyncio()
class TestCalendarEventHandler:
    """CalendarEventHandler 테스트."""

    @patch("src.calendar.google_auth.GoogleCalendarAuth")
    @patch("src.calendar.event.CalendarEventCreator")
    async def test_execute_creates_event(self, mock_creator_cls, mock_auth_cls):
        """캘린더 이벤트가 정상 생성된다."""
        mock_service = MagicMock()
        mock_auth_cls.return_value.get_service.return_value = mock_service
        mock_creator = MagicMock()
        mock_creator.create_daily_report_event.return_value = "event_123"
        mock_creator_cls.return_value = mock_creator

        handler = CalendarEventHandler()
        await handler.execute({
            "trade_date": "2026-04-15",
            "total_profit_loss": 15000,
            "profit_rate": 1.5,
            "execution_count": 3,
            "details_json": "[]",
        })

        mock_creator.create_daily_report_event.assert_called_once()


@pytest.mark.asyncio()
class TestTelegramNotifyHandler:
    """TelegramNotifyHandler 테스트."""

    @patch("src.notify.telegram.TelegramNotifier")
    async def test_execute_sends_notification(self, mock_notifier_cls):
        """Telegram 알림이 정상 전송된다."""
        mock_notifier = MagicMock()
        mock_notifier.notify_daily_summary = AsyncMock()
        mock_notifier_cls.return_value = mock_notifier

        handler = TelegramNotifyHandler()
        await handler.execute({
            "notify_type": "daily_summary",
            "message_data": {
                "trade_date": "2026-04-15",
                "count": 3,
                "profit_loss": 15000,
                "rate": 1.5,
                "buy_count": 2,
                "sell_count": 1,
            },
        })

        mock_notifier.notify_daily_summary.assert_called_once()

    @patch("src.notify.telegram.TelegramNotifier")
    async def test_execute_invalid_type_raises(self, mock_notifier_cls):
        """알 수 없는 알림 유형 시 ValueError가 발생한다."""
        mock_notifier = MagicMock(spec=[])
        mock_notifier_cls.return_value = mock_notifier

        handler = TelegramNotifyHandler()
        with pytest.raises(ValueError, match="알 수 없는 알림 유형"):
            await handler.execute({
                "notify_type": "nonexistent",
                "message_data": {},
            })


@pytest.mark.asyncio()
class TestDailySummaryHandler:
    """DailySummaryHandler 테스트."""

    @patch("src.db.session.get_session")
    @patch("src.db.repository.DailySummaryRepository")
    async def test_execute_upserts(self, mock_repo_cls, mock_get_session):
        """일일 요약 집계가 정상 실행된다."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_repo = MagicMock()
        mock_summary = MagicMock()
        mock_summary.total_buy_count = 2
        mock_summary.total_sell_count = 1
        mock_repo.upsert_daily_summary.return_value = mock_summary
        mock_repo_cls.return_value = mock_repo

        handler = DailySummaryHandler()
        await handler.execute({"report_date": "2026-04-15"})

        mock_repo.upsert_daily_summary.assert_called_once()
