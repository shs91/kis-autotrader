"""태스크 타입별 핸들러."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class TaskHandler(ABC):
    """태스크 핸들러 추상 클래스."""

    @abstractmethod
    async def execute(self, payload: dict[str, Any]) -> None:
        """태스크를 실행한다.

        Args:
            payload: 태스크 데이터 (JSON 역직렬화된 딕셔너리).

        Raises:
            Exception: 실행 실패 시 (Worker가 재시도를 처리).
        """


class CalendarEventHandler(TaskHandler):
    """Google Calendar 이벤트 등록 핸들러."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """일일 매매 결과를 캘린더에 등록한다.

        payload:
            trade_date: 매매 날짜 (ISO 문자열).
            total_profit_loss: 총 손익 (원).
            profit_rate: 수익률 (%).
            execution_count: 체결 건수.
            details_json: 종목별 상세 JSON 문자열.
        """
        from src.calendar.event import CalendarEventCreator
        from src.calendar.google_auth import GoogleCalendarAuth

        auth = GoogleCalendarAuth()
        service = auth.get_service()
        creator = CalendarEventCreator(service=service)

        event_id = creator.create_daily_report_event(
            trade_date=date.fromisoformat(payload["trade_date"]),
            total_profit_loss=payload["total_profit_loss"],
            profit_rate=payload["profit_rate"],
            execution_count=payload["execution_count"],
            details_json=payload["details_json"],
        )
        logger.info("캘린더 이벤트 등록 완료: %s", event_id)


class TelegramNotifyHandler(TaskHandler):
    """Telegram 알림 전송 핸들러."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """Telegram 알림을 전송한다.

        payload:
            notify_type: 알림 유형 (buy, sell, stop_loss, daily_summary, error, system).
            message_data: 알림 메서드에 전달할 키워드 인자.
        """
        from src.notify.telegram import TelegramNotifier

        notifier = TelegramNotifier()
        notify_type = payload["notify_type"]
        message_data = payload["message_data"]

        method = getattr(notifier, f"notify_{notify_type}", None)
        if method is None:
            raise ValueError(f"알 수 없는 알림 유형: {notify_type}")

        await method(**message_data)
        logger.info("Telegram 알림 전송 완료: type=%s", notify_type)


class DailySummaryHandler(TaskHandler):
    """일일 요약 집계 핸들러."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """일일 요약을 DB에 집계한다.

        payload:
            report_date: 집계 대상 날짜 (ISO 문자열).
        """
        from src.db.repository import DailySummaryRepository
        from src.db.session import get_session

        report_date = date.fromisoformat(payload["report_date"])

        with get_session() as session:
            repo = DailySummaryRepository(session)
            summary = repo.upsert_daily_summary(report_date)
            logger.info(
                "일일 요약 집계 완료: %s (매수=%d, 매도=%d)",
                report_date,
                summary.total_buy_count,
                summary.total_sell_count,
            )


class SyncPortfolioHandler(TaskHandler):
    """포트폴리오 동기화 핸들러."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """잔고 정보를 DB 포트폴리오에 동기화한다.

        payload:
            holdings: [{stock_code, stock_name, quantity, avg_price, current_price}].
        """
        from src.db.repository import PortfolioRepository, StockRepository
        from src.db.session import get_session

        holdings = payload["holdings"]

        with get_session() as session:
            stock_repo = StockRepository(session)
            portfolio_repo = PortfolioRepository(session)

            for h in holdings:
                stock = stock_repo.get_by_code(h["stock_code"])
                if stock is None:
                    stock = stock_repo.create(
                        code=h["stock_code"],
                        name=h.get("stock_name", h["stock_code"]),
                        market="UNKNOWN",
                    )
                portfolio_repo.upsert(
                    stock_id=stock.id,
                    quantity=h["quantity"],
                    avg_price=h["avg_price"],
                    current_price=h["current_price"],
                )

        logger.info("포트폴리오 동기화 완료: %d종목", len(holdings))


class DailyPerformanceHandler(TaskHandler):
    """일일 성과 저장 핸들러."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """일일 성과를 DB에 저장한다.

        payload:
            trade_date: 매매 날짜 (ISO 문자열).
            total_profit_loss: 총 손익.
            profit_rate: 수익률.
            execution_count: 체결 건수.
            details: 상세 JSON 문자열 (nullable).
        """
        from src.db.repository import DailyPerformanceRepository
        from src.db.session import get_session

        trade_date = date.fromisoformat(payload["trade_date"])

        with get_session() as session:
            repo = DailyPerformanceRepository(session)
            existing = repo.get_by_date(trade_date)
            if existing:
                logger.debug("일일 성과 이미 존재: %s", trade_date)
                return

            repo.create(
                perf_date=trade_date,
                total_profit_loss=payload["total_profit_loss"],
                profit_rate=payload["profit_rate"],
                execution_count=payload["execution_count"],
                details=payload.get("details"),
            )
            logger.info("일일 성과 저장 완료: %s", trade_date)


class RecordTradeHandler(TaskHandler):
    """매매 체결 기록 핸들러 (Phase 2)."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """매매 체결 내역을 trades 테이블에 기록한다.

        payload:
            stock_code, stock_name, trade_type (BUY/SELL),
            quantity, price, total_amount, traded_at (ISO),
            cycle_number, buy_reason (nullable), sell_reason (nullable),
            signal_type (nullable), profit_loss_pct (nullable),
            profit_loss_amount (nullable).
        """
        from datetime import datetime

        from src.db.models import BuyReason, SellReason, TradeType
        from src.db.repository import TradeRepository
        from src.db.session import get_session

        trade_type = TradeType(payload["trade_type"])
        buy_reason = BuyReason(payload["buy_reason"]) if payload.get("buy_reason") else None
        sell_reason = (
            SellReason(payload["sell_reason"]) if payload.get("sell_reason") else None
        )

        with get_session() as session:
            repo = TradeRepository(session)
            repo.record_trade(
                stock_code=payload["stock_code"],
                stock_name=payload["stock_name"],
                trade_type=trade_type,
                quantity=payload["quantity"],
                price=payload["price"],
                total_amount=payload["total_amount"],
                traded_at=datetime.fromisoformat(payload["traded_at"]),
                cycle_number=payload.get("cycle_number", 0),
                buy_reason=buy_reason,
                sell_reason=sell_reason,
                signal_type=payload.get("signal_type"),
                profit_loss_pct=payload.get("profit_loss_pct"),
                profit_loss_amount=payload.get("profit_loss_amount"),
            )
        logger.info(
            "매매 기록 완료: %s %s %d주 @%d",
            payload["stock_code"],
            payload["trade_type"],
            payload["quantity"],
            payload["price"],
        )


class RecordSignalHandler(TaskHandler):
    """전략 시그널 기록 핸들러 (Phase 2)."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """시그널을 signals 테이블에 기록한다.

        payload:
            stock_code, stock_name, signal_type, detected_at (ISO),
            signal_value (dict, nullable), confidence (float),
            action_taken (bool).
        """
        from datetime import datetime

        from src.db.repository import SignalRepository
        from src.db.session import get_session

        with get_session() as session:
            repo = SignalRepository(session)
            repo.record_signal(
                stock_code=payload["stock_code"],
                stock_name=payload["stock_name"],
                signal_type=payload["signal_type"],
                detected_at=datetime.fromisoformat(payload["detected_at"]),
                signal_value=payload.get("signal_value"),
                confidence=payload.get("confidence", 0.0),
                action_taken=payload.get("action_taken", False),
            )
        logger.info(
            "시그널 기록 완료: %s %s (confidence=%.2f)",
            payload["stock_code"],
            payload["signal_type"],
            payload.get("confidence", 0.0),
        )


class RecordMetricHandler(TaskHandler):
    """시스템 메트릭 기록 핸들러 (Phase 2)."""

    async def execute(self, payload: dict[str, Any]) -> None:
        """시스템 메트릭을 system_metrics 테이블에 기록한다.

        payload:
            metric_type, detail (dict, nullable),
            recorded_at (ISO, nullable).
        """
        from datetime import datetime

        from src.db.repository import SystemMetricRepository
        from src.db.session import get_session

        recorded_at = (
            datetime.fromisoformat(payload["recorded_at"])
            if payload.get("recorded_at")
            else None
        )

        with get_session() as session:
            repo = SystemMetricRepository(session)
            repo.record_metric(
                metric_type=payload["metric_type"],
                detail=payload.get("detail"),
                recorded_at=recorded_at,
            )
        logger.info("메트릭 기록 완료: %s", payload["metric_type"])
