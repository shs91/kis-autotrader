"""매매 결과 Google Calendar 이벤트 생성 모듈."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from googleapiclient.discovery import Resource

from src.config import settings
from src.utils.exceptions import CalendarError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 장 마감 이벤트 시간 (KST)
EVENT_START_HOUR: int = 15
EVENT_START_MINUTE: int = 30
EVENT_END_HOUR: int = 16
EVENT_END_MINUTE: int = 0
EVENT_TIMEZONE: str = "Asia/Seoul"


class CalendarEventCreator:
    """매매 결과를 Google Calendar 이벤트로 생성한다."""

    def __init__(
        self,
        service: Resource,
        calendar_id: str | None = None,
    ) -> None:
        """CalendarEventCreator를 초기화한다.

        Args:
            service: Google Calendar API 서비스 인스턴스.
            calendar_id: 이벤트를 생성할 캘린더 ID.
                None이면 설정값 사용.
        """
        self._service = service
        self._calendar_id = calendar_id or settings.calendar.calendar_id

    def create_daily_report_event(
        self,
        trade_date: date,
        total_profit_loss: int,
        profit_rate: float,
        execution_count: int,
        details_json: str,
    ) -> str:
        """당일 매매 결과를 캘린더 이벤트로 생성한다.

        Args:
            trade_date: 매매 날짜.
            total_profit_loss: 총 손익 (원).
            profit_rate: 수익률 (%, 예: 2.5).
            execution_count: 체결 건수.
            details_json: 종목별 상세 내역 JSON 문자열.
                형식: [{"name": "삼성전자", "code": "005930",
                        "buy_price": 72000, "buy_qty": 10,
                        "sell_price": 73800, "sell_qty": 10,
                        "profit_loss": 18000, "profit_rate": 2.5}, ...]

        Returns:
            생성된 이벤트 ID.

        Raises:
            CalendarError: 이벤트 생성에 실패한 경우.
        """
        summary = self._build_summary(trade_date, profit_rate, execution_count)
        description = self._build_description(
            trade_date, total_profit_loss, profit_rate, execution_count, details_json
        )

        event_body = self._build_event_body(trade_date, summary, description)

        try:
            event: dict[str, Any] = (
                self._service.events()
                .insert(calendarId=self._calendar_id, body=event_body)
                .execute()
            )
            event_id: str = event["id"]
            logger.info(
                "캘린더 이벤트 생성 완료 - 날짜: %s, 이벤트 ID: %s, 제목: %s",
                trade_date.isoformat(),
                event_id,
                summary,
            )
            return event_id

        except Exception as e:
            raise CalendarError(
                f"캘린더 이벤트 생성 실패 (날짜: {trade_date.isoformat()}): {e}"
            ) from e

    @staticmethod
    def _build_summary(trade_date: date, profit_rate: float, execution_count: int) -> str:
        """이벤트 제목을 생성한다.

        Args:
            trade_date: 매매 날짜.
            profit_rate: 수익률 (%).
            execution_count: 체결 건수.

        Returns:
            이벤트 제목 문자열.
        """
        sign = "+" if profit_rate >= 0 else ""
        return (
            f"[매매결과] {trade_date.isoformat()} "
            f"{sign}{profit_rate:.1f}% ({execution_count}건 체결)"
        )

    @staticmethod
    def _build_description(
        trade_date: date,
        total_profit_loss: int,
        profit_rate: float,
        execution_count: int,
        details_json: str,
    ) -> str:
        """이벤트 설명(본문)을 마크다운 형식으로 생성한다.

        Args:
            trade_date: 매매 날짜.
            total_profit_loss: 총 손익 (원).
            profit_rate: 수익률 (%).
            execution_count: 체결 건수.
            details_json: 종목별 상세 내역 JSON 문자열.

        Returns:
            마크다운 형식의 이벤트 설명 문자열.
        """
        profit_sign = "+" if total_profit_loss >= 0 else ""
        rate_sign = "+" if profit_rate >= 0 else ""

        lines: list[str] = [
            "\U0001f4ca 일일 매매 결과",
            "",
            f"날짜: {trade_date.isoformat()}",
            f"총 손익: {profit_sign}{total_profit_loss:,}원",
            f"수익률: {rate_sign}{profit_rate:.1f}%",
            f"체결 건수: {execution_count}건",
        ]

        # 종목별 상세 내역 추가
        try:
            details: list[dict[str, Any]] = json.loads(details_json)
        except (json.JSONDecodeError, TypeError):
            details = []

        if details:
            lines.append("")
            lines.append("--- 종목별 상세 ---")

            for idx, detail in enumerate(details, start=1):
                name = detail.get("name", "알 수 없음")
                code = detail.get("code", "------")
                buy_price = detail.get("buy_price", 0)
                buy_qty = detail.get("buy_qty", 0)
                sell_price = detail.get("sell_price", 0)
                sell_qty = detail.get("sell_qty", 0)
                item_profit = detail.get("profit_loss", 0)
                item_rate = detail.get("profit_rate", 0.0)

                item_sign = "+" if item_profit >= 0 else ""
                item_rate_sign = "+" if item_rate >= 0 else ""

                lines.append("")
                lines.append(f"{idx}. {name} ({code})")
                lines.append(f"   - 매수: {buy_price:,}원 x {buy_qty}주")
                lines.append(f"   - 매도: {sell_price:,}원 x {sell_qty}주")
                lines.append(
                    f"   - 손익: {item_sign}{item_profit:,}원 "
                    f"({item_rate_sign}{item_rate:.1f}%)"
                )

        return "\n".join(lines)

    @staticmethod
    def _build_event_body(
        trade_date: date,
        summary: str,
        description: str,
    ) -> dict[str, Any]:
        """Google Calendar API용 이벤트 본문을 구성한다.

        Args:
            trade_date: 매매 날짜.
            summary: 이벤트 제목.
            description: 이벤트 설명.

        Returns:
            API 요청에 사용할 이벤트 딕셔너리.
        """
        date_str = trade_date.isoformat()
        return {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": f"{date_str}T{EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d}:00",
                "timeZone": EVENT_TIMEZONE,
            },
            "end": {
                "dateTime": f"{date_str}T{EVENT_END_HOUR:02d}:{EVENT_END_MINUTE:02d}:00",
                "timeZone": EVENT_TIMEZONE,
            },
        }
