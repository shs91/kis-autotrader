"""CalendarEventCreator 테스트."""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.calendar.event import CalendarEventCreator, EVENT_TIMEZONE
from src.utils.exceptions import CalendarError


SAMPLE_DETAILS: list[dict[str, Any]] = [
    {
        "name": "삼성전자",
        "code": "005930",
        "buy_price": 72000,
        "buy_qty": 10,
        "sell_price": 73800,
        "sell_qty": 10,
        "profit_loss": 18000,
        "profit_rate": 2.5,
    },
    {
        "name": "SK하이닉스",
        "code": "000660",
        "buy_price": 150000,
        "buy_qty": 5,
        "sell_price": 147000,
        "sell_qty": 5,
        "profit_loss": -15000,
        "profit_rate": -2.0,
    },
]


@pytest.fixture
def mock_service() -> MagicMock:
    """모의 Google Calendar 서비스를 반환한다."""
    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {
        "id": "test_event_id_123"
    }
    return service


@pytest.fixture
def creator(mock_service: MagicMock) -> CalendarEventCreator:
    """CalendarEventCreator 인스턴스를 반환한다."""
    return CalendarEventCreator(service=mock_service, calendar_id="test_calendar_id")


class TestBuildSummary:
    """이벤트 제목 형식 테스트."""

    def test_positive_profit_rate(self) -> None:
        """양수 수익률이면 + 부호가 붙는다."""
        summary = CalendarEventCreator._build_summary(
            trade_date=date(2026, 3, 31),
            profit_rate=2.5,
            execution_count=3,
        )
        assert summary == "[매매결과] 2026-03-31 +2.5% (3건 체결)"

    def test_negative_profit_rate(self) -> None:
        """음수 수익률이면 - 부호가 붙는다."""
        summary = CalendarEventCreator._build_summary(
            trade_date=date(2026, 3, 31),
            profit_rate=-1.3,
            execution_count=2,
        )
        assert summary == "[매매결과] 2026-03-31 -1.3% (2건 체결)"

    def test_zero_profit_rate(self) -> None:
        """수익률이 0이면 + 부호가 붙는다."""
        summary = CalendarEventCreator._build_summary(
            trade_date=date(2026, 3, 31),
            profit_rate=0.0,
            execution_count=1,
        )
        assert summary == "[매매결과] 2026-03-31 +0.0% (1건 체결)"

    def test_decimal_precision(self) -> None:
        """수익률이 소수점 첫째 자리까지 표시된다."""
        summary = CalendarEventCreator._build_summary(
            trade_date=date(2026, 1, 15),
            profit_rate=12.345,
            execution_count=5,
        )
        assert "+12.3%" in summary


class TestBuildEventBody:
    """이벤트 시간 검증 테스트."""

    def test_event_time_is_1530_to_1600_kst(self) -> None:
        """이벤트 시간이 15:30~16:00 KST이다."""
        body = CalendarEventCreator._build_event_body(
            trade_date=date(2026, 3, 31),
            summary="test",
            description="test",
        )
        assert body["start"]["dateTime"] == "2026-03-31T15:30:00"
        assert body["start"]["timeZone"] == EVENT_TIMEZONE
        assert body["end"]["dateTime"] == "2026-03-31T16:00:00"
        assert body["end"]["timeZone"] == EVENT_TIMEZONE


class TestBuildDescription:
    """이벤트 설명 포맷 테스트."""

    def test_description_contains_header(self) -> None:
        """설명에 일일 매매 결과 헤더가 포함된다."""
        desc = CalendarEventCreator._build_description(
            trade_date=date(2026, 3, 31),
            total_profit_loss=125000,
            profit_rate=2.5,
            execution_count=3,
            details_json=json.dumps(SAMPLE_DETAILS),
        )
        assert "일일 매매 결과" in desc

    def test_description_contains_summary_info(self) -> None:
        """설명에 요약 정보가 올바르게 포함된다."""
        desc = CalendarEventCreator._build_description(
            trade_date=date(2026, 3, 31),
            total_profit_loss=125000,
            profit_rate=2.5,
            execution_count=3,
            details_json=json.dumps(SAMPLE_DETAILS),
        )
        assert "날짜: 2026-03-31" in desc
        assert "+125,000원" in desc
        assert "+2.5%" in desc
        assert "3건" in desc

    def test_description_contains_negative_profit(self) -> None:
        """음수 손익이 올바르게 표시된다."""
        desc = CalendarEventCreator._build_description(
            trade_date=date(2026, 3, 31),
            total_profit_loss=-50000,
            profit_rate=-1.5,
            execution_count=2,
            details_json="[]",
        )
        assert "-50,000원" in desc
        assert "-1.5%" in desc

    def test_description_contains_stock_details(self) -> None:
        """설명에 종목별 상세 내역이 포함된다."""
        desc = CalendarEventCreator._build_description(
            trade_date=date(2026, 3, 31),
            total_profit_loss=3000,
            profit_rate=0.5,
            execution_count=2,
            details_json=json.dumps(SAMPLE_DETAILS),
        )
        assert "삼성전자 (005930)" in desc
        assert "72,000원 x 10주" in desc
        assert "+18,000원" in desc
        assert "SK하이닉스 (000660)" in desc
        assert "-15,000원" in desc
        assert "-2.0%" in desc

    def test_description_handles_empty_details(self) -> None:
        """상세 내역이 비어있으면 종목 섹션이 없다."""
        desc = CalendarEventCreator._build_description(
            trade_date=date(2026, 3, 31),
            total_profit_loss=0,
            profit_rate=0.0,
            execution_count=0,
            details_json="[]",
        )
        assert "종목별 상세" not in desc

    def test_description_handles_invalid_json(self) -> None:
        """유효하지 않은 JSON은 종목 섹션 없이 처리된다."""
        desc = CalendarEventCreator._build_description(
            trade_date=date(2026, 3, 31),
            total_profit_loss=0,
            profit_rate=0.0,
            execution_count=0,
            details_json="not valid json",
        )
        assert "종목별 상세" not in desc


class TestCreateDailyReportEvent:
    """이벤트 생성 API 호출 테스트."""

    def test_creates_event_and_returns_id(
        self,
        creator: CalendarEventCreator,
        mock_service: MagicMock,
    ) -> None:
        """이벤트를 생성하고 이벤트 ID를 반환한다."""
        event_id = creator.create_daily_report_event(
            trade_date=date(2026, 3, 31),
            total_profit_loss=125000,
            profit_rate=2.5,
            execution_count=3,
            details_json=json.dumps(SAMPLE_DETAILS),
        )

        assert event_id == "test_event_id_123"
        mock_service.events.return_value.insert.assert_called_once()

        call_kwargs = mock_service.events.return_value.insert.call_args
        assert call_kwargs.kwargs["calendarId"] == "test_calendar_id"

        body = call_kwargs.kwargs["body"]
        assert "[매매결과]" in body["summary"]
        assert "+2.5%" in body["summary"]
        assert "3건 체결" in body["summary"]

    def test_api_error_raises_calendar_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        """API 호출 실패 시 CalendarError가 발생한다."""
        mock_service.events.return_value.insert.return_value.execute.side_effect = (
            Exception("API 호출 실패")
        )
        creator = CalendarEventCreator(
            service=mock_service, calendar_id="test_calendar_id"
        )

        with pytest.raises(CalendarError, match="캘린더 이벤트 생성 실패"):
            creator.create_daily_report_event(
                trade_date=date(2026, 3, 31),
                total_profit_loss=0,
                profit_rate=0.0,
                execution_count=0,
                details_json="[]",
            )
