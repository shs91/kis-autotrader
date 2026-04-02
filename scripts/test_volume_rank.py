"""거래량 순위 API + 스크리닝 확인 스크립트."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.client import KISClient
from src.api.quote import QuoteAPI


async def main() -> None:
    client = KISClient()
    quote = QuoteAPI(client=client)

    print("=== 거래량 순위 조회 ===")
    ranked = await quote.get_volume_rank(top_n=10)

    for i, item in enumerate(ranked, 1):
        print(
            f"{i:2d}. {item.stock_name:20s} ({item.stock_code}) "
            f"현재가={item.current_price:>8,}  등락={item.change_rate:>+6.2f}%  "
            f"거래량={item.volume:>15,}"
        )

    print(f"\n총 {len(ranked)}종목 조회됨")


if __name__ == "__main__":
    asyncio.run(main())
