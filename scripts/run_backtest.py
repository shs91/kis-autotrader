"""백테스트 CLI 실행 스크립트.

사용법:
    python scripts/run_backtest.py --csv data/005930.csv --code 005930
    python scripts/run_backtest.py --code 005930 --api
    python scripts/run_backtest.py --csv data/005930.csv --code 005930 --capital 50000000
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import BacktestConfig, BacktestEngine, BacktestReport, DataLoader
from src.strategy.moving_average import MovingAverageStrategy


def parse_args() -> argparse.Namespace:
    """CLI 인수를 파싱한다."""
    parser = argparse.ArgumentParser(description="백테스트 실행")
    parser.add_argument("--code", required=True, help="종목코드 (예: 005930)")

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="CSV 파일 경로")
    source.add_argument("--api", action="store_true", help="KIS API에서 데이터 로드")

    parser.add_argument("--capital", type=int, default=10_000_000, help="초기자본금 (기본: 10,000,000)")
    parser.add_argument("--short-ma", type=int, default=5, help="단기 이동평균 기간 (기본: 5)")
    parser.add_argument("--long-ma", type=int, default=20, help="장기 이동평균 기간 (기본: 20)")

    return parser.parse_args()


async def main() -> None:
    """백테스트를 실행한다."""
    args = parse_args()
    loader = DataLoader()

    if args.csv:
        data = loader.from_csv(args.csv)
    else:
        data = await loader.from_api(args.code)

    strategy = MovingAverageStrategy(
        short_period=args.short_ma,
        long_period=args.long_ma,
    )
    config = BacktestConfig(initial_capital=args.capital)
    engine = BacktestEngine(strategy=strategy, config=config)
    result = engine.run(data, stock_code=args.code)

    report = BacktestReport()
    report.print_summary(result)


if __name__ == "__main__":
    asyncio.run(main())
