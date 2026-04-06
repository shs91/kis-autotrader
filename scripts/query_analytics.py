#!/usr/bin/env python3
"""매매 분석 쿼리 CLI 도구.

사용법:
    python scripts/query_analytics.py daily 2026-04-07
    python scripts/query_analytics.py weekly 2026 15
    python scripts/query_analytics.py range 2026-03-01 2026-04-07
    python scripts/query_analytics.py risk --days 30

JSON 출력으로 Cowork 에이전트가 파싱하기 쉽게 구성되어 있다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

# 프로젝트 루트를 path에 추가
sys.path.insert(0, ".")

from src.db.analytics import (
    get_cumulative_pnl,
    get_daily_errors,
    get_daily_screening,
    get_daily_signals,
    get_daily_summary,
    get_daily_trades,
    get_optimal_risk_params,
    get_screening_conversion_rate,
    get_signal_accuracy,
    get_strategy_comparison,
    get_weekly_error_trend,
    get_weekly_risk_analysis,
    get_weekly_signal_performance,
    get_weekly_stock_frequency,
    get_weekly_trade_stats,
)
from src.db.session import get_session


def cmd_daily(args: argparse.Namespace) -> dict:
    """일일 분석을 실행한다."""
    target = date.fromisoformat(args.date)
    with get_session() as session:
        return {
            "date": target.isoformat(),
            "trades": get_daily_trades(session, target),
            "signals": get_daily_signals(session, target),
            "screening": get_daily_screening(session, target),
            "errors": get_daily_errors(session, target),
            "summary": get_daily_summary(session, target),
            "signal_accuracy": get_signal_accuracy(session, target),
        }


def cmd_weekly(args: argparse.Namespace) -> dict:
    """주간 분석을 실행한다."""
    year, week = args.year, args.week
    with get_session() as session:
        return {
            "year": year,
            "week": week,
            "trade_stats": get_weekly_trade_stats(session, year, week),
            "stock_frequency": get_weekly_stock_frequency(session, year, week),
            "signal_performance": get_weekly_signal_performance(session, year, week),
            "risk_analysis": get_weekly_risk_analysis(session, year, week),
            "screening_conversion": get_screening_conversion_rate(session, year, week),
            "error_trend": get_weekly_error_trend(session, year, week),
        }


def cmd_range(args: argparse.Namespace) -> dict:
    """기간 분석을 실행한다."""
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    with get_session() as session:
        return {
            "period": f"{start.isoformat()} ~ {end.isoformat()}",
            "cumulative_pnl": get_cumulative_pnl(session, start, end),
            "strategy_comparison": get_strategy_comparison(session, start, end),
        }


def cmd_risk(args: argparse.Namespace) -> dict:
    """리스크 파라미터 분석을 실행한다."""
    with get_session() as session:
        return get_optimal_risk_params(session, lookback_days=args.days)


def main() -> None:
    """CLI 엔트리포인트."""
    parser = argparse.ArgumentParser(
        description="매매 분석 쿼리 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # daily
    p_daily = subparsers.add_parser("daily", help="일일 분석")
    p_daily.add_argument("date", help="날짜 (YYYY-MM-DD)")

    # weekly
    p_weekly = subparsers.add_parser("weekly", help="주간 분석")
    p_weekly.add_argument("year", type=int, help="연도")
    p_weekly.add_argument("week", type=int, help="ISO 주차 (1-53)")

    # range
    p_range = subparsers.add_parser("range", help="기간 분석")
    p_range.add_argument("start", help="시작일 (YYYY-MM-DD)")
    p_range.add_argument("end", help="종료일 (YYYY-MM-DD)")

    # risk
    p_risk = subparsers.add_parser("risk", help="리스크 파라미터 분석")
    p_risk.add_argument("--days", type=int, default=30, help="분석 기간 (일수)")

    args = parser.parse_args()

    handlers = {
        "daily": cmd_daily,
        "weekly": cmd_weekly,
        "range": cmd_range,
        "risk": cmd_risk,
    }

    result = handlers[args.command](args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
