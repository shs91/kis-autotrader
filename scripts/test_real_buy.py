"""실제 KIS API 매수 주문 테스트 스크립트 (모의투자)."""

import asyncio
import json
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.order import OrderAPI
from src.config import settings


async def main() -> None:
    """삼성전자 1주 시장가 매수 주문을 테스트한다."""
    print("=" * 60)
    print("KIS API 실제 매수 주문 테스트 (모의투자)")
    print("=" * 60)
    print(f"환경: {settings.kis.env}")
    print(f"계좌: {settings.kis.account_no}")
    print(f"BASE URL: {settings.kis.base_url}")
    print(f"종목: 005930 (삼성전자)")
    print(f"수량: 1주")
    print(f"주문유형: 시장가")
    print("=" * 60)

    if settings.kis.env != "virtual":
        print("ERROR: 모의투자 환경이 아닙니다! 실전 환경에서는 실행하지 않습니다.")
        return

    api = OrderAPI()

    try:
        result = await api.buy(
            stock_code="005930",
            quantity=1,
        )

        print("\n[주문 성공]")
        print(f"  주문번호: {result.order_no}")
        print(f"  주문시각: {result.order_time}")
        print(f"  메시지: {result.message}")
        print(f"\n[전체 응답]")
        print(json.dumps(result.raw_response, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n[주문 실패] {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
