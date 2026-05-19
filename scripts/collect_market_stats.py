#!/usr/bin/env python
"""pykrx 기반 공매도 잔고 + 투자자별 매매동향 일일 RAG 적재 스크립트.

T+2 지연: 오늘이 N일이면 N-2(영업일) 데이터를 수집한다.
launchd 일일 잡(18:00 KST 권장 — 공매도 T+2 데이터 안정성 확보).

수집 대상 종목: watchlist ∪ 최근 30일 거래 종목 (env로 override 가능).

사용:
    .venv/bin/python scripts/collect_market_stats.py
    .venv/bin/python scripts/collect_market_stats.py --date 20260517
    .venv/bin/python scripts/collect_market_stats.py --tickers 005930,000660
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.db.repository import (  # noqa: E402
    NewsChunkRepository,
    StockRepository,
    TradeRepository,
)
from src.db.session import get_session  # noqa: E402
from src.market_stats import (  # noqa: E402
    MarketStatsCollector,
    _nearest_krx_business_day,
    resolve_target_tickers,
)
from src.rag.embedder import Embedder  # noqa: E402
from src.utils.logger import setup_logger  # noqa: E402

load_dotenv()
logger = setup_logger(__name__)


def _default_target_date() -> date:
    """T+2 지연 — 오늘 기준 2일 전 + KRX 영업일 보정.

    pykrx의 get_nearest_business_day_in_a_week로 토/일/공휴일을 영업일로
    당겨 잡는다.
    """
    today = datetime.now(UTC).date()
    return _nearest_krx_business_day(today, lookback_days=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pykrx 일일 RAG 적재")
    parser.add_argument(
        "--date", type=str, default=None,
        help="YYYYMMDD. 미지정 시 today-2.",
    )
    parser.add_argument(
        "--tickers", type=str, default=None,
        help="콤마 구분 종목코드. 미지정 시 watchlist ∪ 최근 30일 거래.",
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="최근 거래 종목 lookback (기본 30).",
    )
    args = parser.parse_args(argv)

    target_date = (
        datetime.strptime(args.date, "%Y%m%d").date()  # noqa: DTZ007 — date()만 사용
        if args.date else _default_target_date()
    )

    # 종목 결정
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        env_tickers = os.getenv("NEWS_PYKRX_TICKERS", "").strip()
        if env_tickers:
            tickers = [t.strip() for t in env_tickers.split(",") if t.strip()]
        else:
            with get_session() as session:
                tickers = resolve_target_tickers(
                    stock_repo=StockRepository(session),
                    trade_repo=TradeRepository(session),
                    days=args.days,
                )

    if not tickers:
        logger.warning("수집 대상 종목 없음 — 종료")
        return 1

    logger.info(
        "pykrx 수집 시작: date=%s tickers=%d", target_date, len(tickers),
    )

    embedder = Embedder.get()  # 첫 호출 시 ~5초 워밍업
    with get_session() as session:
        collector = MarketStatsCollector(
            embedder=embedder,
            repo=NewsChunkRepository(session),
            tickers=tickers,
            target_date=target_date,
        )
        inserted = collector.collect()

    logger.info(
        "pykrx 수집 완료: date=%s tickers=%d chunks_inserted=%d",
        target_date, len(tickers), inserted,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
