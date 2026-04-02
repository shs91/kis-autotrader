"""전략 분석 디버그 스크립트 — 실제 데이터로 시그널 확인."""

import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.client import KISClient
from src.api.quote import QuoteAPI
from src.strategy.moving_average import MovingAverageStrategy
from src.strategy.rsi import RSIStrategy


async def main() -> None:
    client = KISClient()
    quote = QuoteAPI(client=client)
    ma_strategy = MovingAverageStrategy()
    rsi_strategy = RSIStrategy()

    codes = ["005930", "000660", "035420"]

    for code in codes:
        daily = await quote.get_daily_price(code)
        current = await quote.get_current_price(code)

        print(f"\n{'='*60}")
        print(f"{current.stock_name} ({code}) — 현재가: {current.current_price:,}원")
        print(f"일봉 데이터: {len(daily)}건")

        if len(daily) < 21:
            print("  데이터 부족, 스킵")
            continue

        df = pd.DataFrame(
            [{"close": p.close_price, "date": p.date} for p in reversed(daily)]
        )

        # MA 값 직접 확인
        short_ma = df["close"].rolling(window=5).mean()
        long_ma = df["close"].rolling(window=20).mean()

        print(f"\n  [이동평균 분석]")
        print(f"  최근 종가 5개: {df['close'].tail(5).tolist()}")
        print(f"  단기MA(5): {short_ma.iloc[-1]:.2f}")
        print(f"  장기MA(20): {long_ma.iloc[-1]:.2f}")
        print(f"  직전 단기MA: {short_ma.iloc[-2]:.2f}")
        print(f"  직전 장기MA: {long_ma.iloc[-2]:.2f}")
        diff_pct = (short_ma.iloc[-1] - long_ma.iloc[-1]) / long_ma.iloc[-1] * 100
        print(f"  단기-장기 괴리: {diff_pct:+.2f}%")

        ma_signal = ma_strategy.analyze(df)
        print(f"  MA 시그널: {ma_signal.signal_type.value} (신뢰도: {ma_signal.confidence:.2f})")
        print(f"  사유: {ma_signal.reason}")

        # RSI도 확인
        rsi_signal = rsi_strategy.analyze(df)
        print(f"\n  [RSI 분석]")
        print(f"  RSI 시그널: {rsi_signal.signal_type.value} (신뢰도: {rsi_signal.confidence:.2f})")
        print(f"  사유: {rsi_signal.reason}")

    # 거래량 상위 종목 스크리닝 디버그
    print(f"\n{'='*60}")
    print("거래량 상위 종목 스크리닝 디버그")
    print(f"{'='*60}")

    ranked = await quote.get_volume_rank(top_n=10)
    for item in ranked[:5]:
        daily = await quote.get_daily_price(item.stock_code)
        if len(daily) < 21:
            print(f"  {item.stock_name}({item.stock_code}): 데이터 부족 ({len(daily)}건)")
            continue

        df = pd.DataFrame(
            [{"close": p.close_price, "date": p.date} for p in reversed(daily)]
        )
        signal = ma_strategy.analyze(df)
        print(
            f"  {item.stock_name:20s}({item.stock_code}) "
            f"시그널={signal.signal_type.value:4s} 신뢰도={signal.confidence:.2f} "
            f"사유={signal.reason}"
        )


if __name__ == "__main__":
    asyncio.run(main())
