"""Google Calendar 이벤트 등록 테스트."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calendar.google_auth import GoogleCalendarAuth
from src.calendar.event import CalendarEventCreator


def main() -> None:
    print("=== Google Calendar 테스트 ===")

    # 인증
    auth = GoogleCalendarAuth()
    service = auth.get_service()
    print("인증 성공")

    # 테스트 이벤트 생성
    creator = CalendarEventCreator(service=service)
    event_id = creator.create_daily_report_event(
        trade_date=date.today(),
        total_profit_loss=15000,
        profit_rate=1.5,
        execution_count=2,
        details_json='[{"name":"삼성전자","code":"005930","buy_price":72000,"buy_qty":10,"sell_price":73500,"sell_qty":10,"profit_loss":15000,"profit_rate":2.08}]',
    )
    print(f"이벤트 생성 완료! ID: {event_id}")


if __name__ == "__main__":
    main()
