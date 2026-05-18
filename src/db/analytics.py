"""매매 분석 쿼리 모듈.

Cowork 에이전트가 리포트/제안서를 작성할 때 사용하는 읽기 전용 쿼리.
모든 함수는 Session을 인자로 받아 트랜잭션 관리를 호출자에게 위임한다.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.db.models import (
    ImplementationLog,
    Proposal,
    ScreeningResult,
    SellReason,
    Signal,
    SystemMetric,
    Trade,
    TradeType,
)
from src.db.repository import DailySummaryRepository


def _day_range(target_date: date) -> tuple[datetime, datetime]:
    """날짜의 시작~끝 datetime을 반환한다."""
    start = datetime(target_date.year, target_date.month, target_date.day)
    end = start + timedelta(days=1)
    return start, end


def _week_range(year: int, week: int) -> tuple[date, date]:
    """ISO 주차의 월요일~일요일 date를 반환한다."""
    jan4 = date(year, 1, 4)
    start_of_year = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = start_of_year + timedelta(weeks=week - 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


# ── 일일 분석 ─────────────────────────────────────────────


def get_daily_trades(session: Session, target_date: date) -> list[dict[str, Any]]:
    """해당일 전체 체결 내역을 반환한다.

    Args:
        session: DB 세션
        target_date: 조회 날짜

    Returns:
        체결 내역 딕셔너리 리스트
    """
    start, end = _day_range(target_date)
    rows = session.execute(
        select(Trade)
        .where(Trade.traded_at >= start, Trade.traded_at < end)
        .order_by(Trade.traded_at)
    ).scalars().all()

    return [
        {
            "id": t.id,
            "stock_code": t.stock_code,
            "stock_name": t.stock_name,
            "trade_type": t.trade_type.value,
            "quantity": t.quantity,
            "price": t.price,
            "total_amount": t.total_amount,
            "sell_reason": t.sell_reason.value if t.sell_reason else None,
            "signal_type": t.signal_type,
            "profit_loss_pct": t.profit_loss_pct,
            "profit_loss_amount": t.profit_loss_amount,
            "cycle_number": t.cycle_number,
            "traded_at": t.traded_at.isoformat(),
        }
        for t in rows
    ]


def get_daily_signals(session: Session, target_date: date) -> list[dict[str, Any]]:
    """해당일 시그널과 action_taken 여부를 반환한다.

    Args:
        session: DB 세션
        target_date: 조회 날짜

    Returns:
        시그널 딕셔너리 리스트
    """
    start, end = _day_range(target_date)
    rows = session.execute(
        select(Signal)
        .where(Signal.detected_at >= start, Signal.detected_at < end)
        .order_by(Signal.detected_at)
    ).scalars().all()

    return [
        {
            "id": s.id,
            "stock_code": s.stock_code,
            "stock_name": s.stock_name,
            "signal_type": s.signal_type,
            "signal_value": s.signal_value,
            "confidence": s.confidence,
            "action_taken": s.action_taken,
            "detected_at": s.detected_at.isoformat(),
        }
        for s in rows
    ]


def get_daily_screening(session: Session, target_date: date) -> dict[str, Any]:
    """해당일 스크리닝 결과��� 전환율을 반환한다.

    Args:
        session: DB 세션
        target_date: 조회 날짜

    Returns:
        스크리닝 요약 + 상세 목록
    """
    start, end = _day_range(target_date)
    rows = session.execute(
        select(ScreeningResult)
        .where(ScreeningResult.screened_at >= start, ScreeningResult.screened_at < end)
        .order_by(ScreeningResult.screened_at, ScreeningResult.screening_rank)
    ).scalars().all()

    total = len(rows)
    converted = sum(1 for r in rows if r.converted_to_trade)

    return {
        "total_screened": total,
        "converted_count": converted,
        "conversion_rate": (converted / total * 100) if total > 0 else 0.0,
        "items": [
            {
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "screening_rank": r.screening_rank,
                "volume": r.volume,
                "price_change_pct": r.price_change_pct,
                "converted_to_trade": r.converted_to_trade,
                "cycle_number": r.cycle_number,
            }
            for r in rows
        ],
    }


def get_daily_errors(session: Session, target_date: date) -> dict[str, Any]:
    """해당일 에러 집계를 반환한다.

    Args:
        session: DB 세션
        target_date: 조회 날짜

    Returns:
        에러 유형별 건�� + 상세 목록
    """
    start, end = _day_range(target_date)
    rows = session.execute(
        select(SystemMetric)
        .where(
            SystemMetric.metric_type == "ERROR",
            SystemMetric.recorded_at >= start,
            SystemMetric.recorded_at < end,
        )
        .order_by(SystemMetric.recorded_at)
    ).scalars().all()

    return {
        "total_errors": len(rows),
        "items": [
            {
                "id": m.id,
                "detail": m.detail,
                "recorded_at": m.recorded_at.isoformat(),
            }
            for m in rows
        ],
    }


def get_daily_summary(session: Session, target_date: date) -> dict[str, Any]:
    """해당일 요약을 반환한다. 없으면 집계 후 생성한다.

    Args:
        session: DB 세션
        target_date: 조회 날짜

    Returns:
        일일 요약 딕셔너리
    """
    repo = DailySummaryRepository(session)
    summary = repo.get_by_date(target_date)
    if summary is None:
        summary = repo.upsert_daily_summary(target_date)

    return {
        "report_date": summary.report_date.isoformat(),
        "total_buy_count": summary.total_buy_count,
        "total_sell_count": summary.total_sell_count,
        "total_profit_loss": summary.total_profit_loss,
        "win_rate": summary.win_rate,
        "stop_loss_count": summary.stop_loss_count,
        "take_profit_count": summary.take_profit_count,
        "strategy_sell_count": summary.strategy_sell_count,
        "screening_count": summary.screening_count,
        "screening_conversion_count": summary.screening_conversion_count,
        "error_count": summary.error_count,
        "cycle_count": summary.cycle_count,
    }


def get_signal_accuracy(
    session: Session,
    target_date: date,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    """시그널 발생 후 실제 매매 실행 일치율을 반환한다.

    action_taken=True인 시그널 중 실제로 같은 종목에 체결이 발생한 비율.

    Args:
        session: DB 세션
        target_date: 조회 날짜
        lookback_hours: 시그널 이후 매매 확인 시간 범위

    Returns:
        시그널 정확도 통계
    """
    start, end = _day_range(target_date)

    signals = session.execute(
        select(Signal)
        .where(Signal.detected_at >= start, Signal.detected_at < end)
    ).scalars().all()

    total = len(signals)
    acted = [s for s in signals if s.action_taken]
    not_acted = [s for s in signals if not s.action_taken]

    # action_taken 시그널 중 실제 체결 확인
    confirmed = 0
    for sig in acted:
        lookback_end = sig.detected_at + timedelta(hours=lookback_hours)
        expected_type = TradeType.BUY if "BUY" in sig.signal_type.upper() or \
            "GOLDEN" in sig.signal_type.upper() else TradeType.SELL

        trade_exists = session.execute(
            select(func.count()).select_from(Trade).where(
                Trade.stock_code == sig.stock_code,
                Trade.trade_type == expected_type,
                Trade.traded_at >= sig.detected_at,
                Trade.traded_at <= lookback_end,
            )
        ).scalar_one()

        if trade_exists > 0:
            confirmed += 1

    return {
        "total_signals": total,
        "acted_count": len(acted),
        "not_acted_count": len(not_acted),
        "confirmed_count": confirmed,
        "accuracy_rate": (confirmed / len(acted) * 100) if acted else 0.0,
    }


# ── 주간 분석 ─────────────────────────────────────────────


def get_weekly_trade_stats(
    session: Session, year: int, week: int,
) -> dict[str, Any]:
    """주간 일별 매매 건수 및 수익률 추이를 반환한다.

    Args:
        session: DB 세션
        year: 연도
        week: ISO 주차

    Returns:
        일별 매매 통계 리스트
    """
    monday, sunday = _week_range(year, week)
    start = datetime(monday.year, monday.month, monday.day)
    end = datetime(sunday.year, sunday.month, sunday.day) + timedelta(days=1)

    trades = session.execute(
        select(Trade)
        .where(Trade.traded_at >= start, Trade.traded_at < end)
        .order_by(Trade.traded_at)
    ).scalars().all()

    daily: dict[str, dict[str, Any]] = {}
    for t in trades:
        day_key = t.traded_at.strftime("%Y-%m-%d")
        if day_key not in daily:
            daily[day_key] = {
                "date": day_key,
                "buy_count": 0,
                "sell_count": 0,
                "total_profit_loss": 0,
                "trades": 0,
            }
        d = daily[day_key]
        d["trades"] += 1
        if t.trade_type == TradeType.BUY:
            d["buy_count"] += 1
        else:
            d["sell_count"] += 1
            d["total_profit_loss"] += t.profit_loss_amount or 0

    result = list(daily.values())
    result.sort(key=lambda x: x["date"])

    return {
        "year": year,
        "week": week,
        "period": f"{monday.isoformat()} ~ {sunday.isoformat()}",
        "total_trades": len(trades),
        "daily_stats": result,
    }


def get_weekly_stock_frequency(
    session: Session, year: int, week: int,
) -> list[dict[str, Any]]:
    """주간 종목별 매매 횟수를 반환한다 (반복 매매 감지).

    Args:
        session: DB 세션
        year: 연도
        week: ISO 주차

    Returns:
        종목별 매매 빈도 (내림차순)
    """
    monday, sunday = _week_range(year, week)
    start = datetime(monday.year, monday.month, monday.day)
    end = datetime(sunday.year, sunday.month, sunday.day) + timedelta(days=1)

    rows = session.execute(
        select(
            Trade.stock_code,
            Trade.stock_name,
            func.count().label("trade_count"),
            func.sum(case((Trade.trade_type == TradeType.BUY, 1), else_=0)).label("buy_count"),
            func.sum(case((Trade.trade_type == TradeType.SELL, 1), else_=0)).label("sell_count"),
            func.sum(
                case((Trade.profit_loss_amount.isnot(None), Trade.profit_loss_amount), else_=0)
            ).label("total_pnl"),
        )
        .where(Trade.traded_at >= start, Trade.traded_at < end)
        .group_by(Trade.stock_code, Trade.stock_name)
        .order_by(func.count().desc())
    ).all()

    return [
        {
            "stock_code": r.stock_code,
            "stock_name": r.stock_name,
            "trade_count": r.trade_count,
            "buy_count": r.buy_count,
            "sell_count": r.sell_count,
            "total_pnl": int(r.total_pnl),
        }
        for r in rows
    ]


def get_weekly_signal_performance(
    session: Session, year: int, week: int,
) -> list[dict[str, Any]]:
    """주간 시그널 유형별 성공률을 반환한다.

    Args:
        session: DB 세션
        year: 연도
        week: ISO 주차

    Returns:
        시그널 유형별 통계
    """
    monday, sunday = _week_range(year, week)
    start = datetime(monday.year, monday.month, monday.day)
    end = datetime(sunday.year, sunday.month, sunday.day) + timedelta(days=1)

    rows = session.execute(
        select(
            Signal.signal_type,
            func.count().label("total"),
            func.sum(case((Signal.action_taken.is_(True), 1), else_=0)).label("acted"),
            func.avg(Signal.confidence).label("avg_confidence"),
        )
        .where(Signal.detected_at >= start, Signal.detected_at < end)
        .group_by(Signal.signal_type)
        .order_by(func.count().desc())
    ).all()

    return [
        {
            "signal_type": r.signal_type,
            "total": r.total,
            "acted": int(r.acted),
            "act_rate": round(int(r.acted) / r.total * 100, 1) if r.total > 0 else 0.0,
            "avg_confidence": round(float(r.avg_confidence), 3) if r.avg_confidence else 0.0,
        }
        for r in rows
    ]


def get_weekly_risk_analysis(
    session: Session, year: int, week: int,
) -> dict[str, Any]:
    """주간 손절/익절 발동 통계를 반환한다.

    Args:
        session: DB 세션
        year: 연도
        week: ISO 주차

    Returns:
        매도 사유별 통계
    """
    monday, sunday = _week_range(year, week)
    start = datetime(monday.year, monday.month, monday.day)
    end = datetime(sunday.year, sunday.month, sunday.day) + timedelta(days=1)

    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= start,
            Trade.traded_at < end,
            Trade.trade_type == TradeType.SELL,
        )
        .order_by(Trade.traded_at)
    ).scalars().all()

    by_reason: dict[str, list[dict[str, Any]]] = {}
    for t in sells:
        reason_key = t.sell_reason.value if t.sell_reason else "UNKNOWN"
        if reason_key not in by_reason:
            by_reason[reason_key] = []
        by_reason[reason_key].append({
            "stock_code": t.stock_code,
            "price": t.price,
            "profit_loss_pct": t.profit_loss_pct,
            "profit_loss_amount": t.profit_loss_amount,
        })

    summary: dict[str, Any] = {}
    for reason, items in by_reason.items():
        pcts = [i["profit_loss_pct"] for i in items if i["profit_loss_pct"] is not None]
        summary[reason] = {
            "count": len(items),
            "avg_pnl_pct": round(sum(pcts) / len(pcts), 2) if pcts else 0.0,
            "total_pnl": sum(i["profit_loss_amount"] or 0 for i in items),
        }

    return {
        "total_sells": len(sells),
        "by_reason": summary,
    }


def get_screening_conversion_rate(
    session: Session, year: int, week: int,
) -> dict[str, Any]:
    """주간 스크리닝 발굴→체결 전환율 추이를 반환한다.

    Args:
        session: DB 세션
        year: 연도
        week: ISO 주차

    Returns:
        일별 전환율 추이
    """
    monday, sunday = _week_range(year, week)
    start = datetime(monday.year, monday.month, monday.day)
    end = datetime(sunday.year, sunday.month, sunday.day) + timedelta(days=1)

    rows = session.execute(
        select(ScreeningResult)
        .where(ScreeningResult.screened_at >= start, ScreeningResult.screened_at < end)
        .order_by(ScreeningResult.screened_at)
    ).scalars().all()

    daily: dict[str, dict[str, int]] = {}
    for r in rows:
        day_key = r.screened_at.strftime("%Y-%m-%d")
        if day_key not in daily:
            daily[day_key] = {"total": 0, "converted": 0}
        daily[day_key]["total"] += 1
        if r.converted_to_trade:
            daily[day_key]["converted"] += 1

    result = []
    for day_key in sorted(daily):
        d = daily[day_key]
        result.append({
            "date": day_key,
            "total_screened": d["total"],
            "converted": d["converted"],
            "rate": round(d["converted"] / d["total"] * 100, 1) if d["total"] > 0 else 0.0,
        })

    total = sum(d["total"] for d in daily.values())
    converted = sum(d["converted"] for d in daily.values())

    return {
        "period": f"{monday.isoformat()} ~ {sunday.isoformat()}",
        "total_screened": total,
        "total_converted": converted,
        "overall_rate": round(converted / total * 100, 1) if total > 0 else 0.0,
        "daily": result,
    }


def get_weekly_error_trend(
    session: Session, year: int, week: int,
) -> dict[str, Any]:
    """주간 일별 에러 빈도 추이를 반환한다.

    Args:
        session: DB 세션
        year: 연도
        week: ISO 주차

    Returns:
        일별 에러 건수
    """
    monday, sunday = _week_range(year, week)
    start = datetime(monday.year, monday.month, monday.day)
    end = datetime(sunday.year, sunday.month, sunday.day) + timedelta(days=1)

    rows = session.execute(
        select(SystemMetric)
        .where(
            SystemMetric.metric_type == "ERROR",
            SystemMetric.recorded_at >= start,
            SystemMetric.recorded_at < end,
        )
        .order_by(SystemMetric.recorded_at)
    ).scalars().all()

    daily: dict[str, int] = {}
    for m in rows:
        day_key = m.recorded_at.strftime("%Y-%m-%d")
        daily[day_key] = daily.get(day_key, 0) + 1

    return {
        "period": f"{monday.isoformat()} ~ {sunday.isoformat()}",
        "total_errors": len(rows),
        "daily": [
            {"date": k, "error_count": v}
            for k, v in sorted(daily.items())
        ],
    }


# ── 중장기 분석 ────────────────────────────────────────────


def get_cumulative_pnl(
    session: Session, start_date: date, end_date: date,
) -> dict[str, Any]:
    """기간 내 누적 손익 곡선을 반환한다.

    Args:
        session: DB 세션
        start_date: 시작일
        end_date: 종료일

    Returns:
        일별 손익 + 누적 손익 곡선
    """
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)

    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= start,
            Trade.traded_at < end,
            Trade.trade_type == TradeType.SELL,
        )
        .order_by(Trade.traded_at)
    ).scalars().all()

    daily: dict[str, int] = {}
    for t in sells:
        day_key = t.traded_at.strftime("%Y-%m-%d")
        daily[day_key] = daily.get(day_key, 0) + (t.profit_loss_amount or 0)

    cumulative = 0
    curve = []
    for day_key in sorted(daily):
        cumulative += daily[day_key]
        curve.append({
            "date": day_key,
            "daily_pnl": daily[day_key],
            "cumulative_pnl": cumulative,
        })

    return {
        "period": f"{start_date.isoformat()} ~ {end_date.isoformat()}",
        "total_pnl": cumulative,
        "trading_days": len(curve),
        "curve": curve,
    }


def get_strategy_comparison(
    session: Session, start_date: date, end_date: date,
) -> list[dict[str, Any]]:
    """기간 내 시그널 유형별 성과를 비교한다.

    시그널 유형별로 action_taken=True인 시그널의
    해당 종목 매도 손익을 집계한다.

    Args:
        session: DB 세션
        start_date: 시작일
        end_date: 종료일

    Returns:
        시그널 유형별 성과 비교
    """
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)

    # 시그널 유형별 통계
    signals = session.execute(
        select(Signal)
        .where(Signal.detected_at >= start, Signal.detected_at < end)
    ).scalars().all()

    by_type: dict[str, dict[str, Any]] = {}
    for s in signals:
        if s.signal_type not in by_type:
            by_type[s.signal_type] = {
                "total": 0,
                "acted": 0,
                "confidences": [],
            }
        st = by_type[s.signal_type]
        st["total"] += 1
        st["confidences"].append(s.confidence)
        if s.action_taken:
            st["acted"] += 1

    # 매매에서 signal_type별 손익
    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= start,
            Trade.traded_at < end,
            Trade.trade_type == TradeType.SELL,
            Trade.signal_type.isnot(None),
        )
    ).scalars().all()

    pnl_by_signal: dict[str, list[int]] = {}
    for t in sells:
        sig = t.signal_type or "UNKNOWN"
        if sig not in pnl_by_signal:
            pnl_by_signal[sig] = []
        pnl_by_signal[sig].append(t.profit_loss_amount or 0)

    result = []
    for sig_type, stats in by_type.items():
        pnls = pnl_by_signal.get(sig_type, [])
        confs = stats["confidences"]
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        total = stats["total"]
        acted = stats["acted"]
        act_rate = round(acted / total * 100, 1) if total > 0 else 0.0
        result.append({
            "signal_type": sig_type,
            "signal_count": total,
            "acted_count": acted,
            "act_rate": act_rate,
            "avg_confidence": round(avg_conf, 3),
            "related_sells": len(pnls),
            "total_pnl": sum(pnls),
            "avg_pnl": round(sum(pnls) / len(pnls)) if pnls else 0,
        })

    result.sort(key=lambda x: x["total_pnl"], reverse=True)
    return result


def get_optimal_risk_params(
    session: Session, lookback_days: int = 30,
) -> dict[str, Any]:
    """손절/익절 최적 비율을 추정한다.

    손절/익절 발동 시점의 수익률 분포를 분석하여
    최적 비율을 제안한다.

    Args:
        session: DB 세션
        lookback_days: 분석 기간 (일수)

    Returns:
        손절/익절 비율 분석 결과
    """
    since = datetime.now() - timedelta(days=lookback_days)

    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= since,
            Trade.trade_type == TradeType.SELL,
            Trade.sell_reason.isnot(None),
        )
        .order_by(Trade.traded_at)
    ).scalars().all()

    stop_loss_pcts: list[float] = []
    take_profit_pcts: list[float] = []
    strategy_pcts: list[float] = []

    for t in sells:
        pct = t.profit_loss_pct
        if pct is None:
            continue
        if t.sell_reason == SellReason.STOP_LOSS:
            stop_loss_pcts.append(pct)
        elif t.sell_reason == SellReason.TAKE_PROFIT:
            take_profit_pcts.append(pct)
        elif t.sell_reason == SellReason.STRATEGY:
            strategy_pcts.append(pct)

    def _stats(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "avg": 0.0, "min": 0.0, "max": 0.0, "median": 0.0}
        sorted_v = sorted(values)
        mid = len(sorted_v) // 2
        median = sorted_v[mid] if len(sorted_v) % 2 else (sorted_v[mid - 1] + sorted_v[mid]) / 2
        return {
            "count": len(values),
            "avg": round(sum(values) / len(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "median": round(median, 2),
        }

    return {
        "lookback_days": lookback_days,
        "total_sells": len(sells),
        "stop_loss": _stats(stop_loss_pcts),
        "take_profit": _stats(take_profit_pcts),
        "strategy": _stats(strategy_pcts),
        "recommendation": {
            "stop_loss_rate": round(
                abs(sum(stop_loss_pcts) / len(stop_loss_pcts)) / 100, 4
            ) if stop_loss_pcts else 0.03,
            "take_profit_rate": round(
                abs(sum(take_profit_pcts) / len(take_profit_pcts)) / 100, 4
            ) if take_profit_pcts else 0.05,
        },
    }


# ── 고급 분석 지표 ────────────────────────────────────────


def _daily_pnl_series(
    session: Session, start_date: date, end_date: date,
) -> list[tuple[str, int]]:
    """기간 내 일별 실현손익 시계열을 반환한다 (내부 헬퍼)."""
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)

    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= start,
            Trade.traded_at < end,
            Trade.trade_type == TradeType.SELL,
        )
        .order_by(Trade.traded_at)
    ).scalars().all()

    daily: dict[str, int] = {}
    for t in sells:
        day_key = t.traded_at.strftime("%Y-%m-%d")
        daily[day_key] = daily.get(day_key, 0) + (t.profit_loss_amount or 0)

    return [(k, daily[k]) for k in sorted(daily)]


def get_max_drawdown(
    session: Session, start_date: date, end_date: date,
) -> dict[str, Any]:
    """기간 내 최대 낙폭(MDD)을 계산한다.

    MDD = (피크 대비 최대 하락액) / 피크 * 100

    Args:
        session: DB 세션
        start_date: 시작일
        end_date: 종료일

    Returns:
        MDD 관련 지표
    """
    series = _daily_pnl_series(session, start_date, end_date)
    if not series:
        return {"mdd_pct": 0.0, "mdd_amount": 0, "peak": 0, "trough": 0, "peak_date": None, "trough_date": None}

    cumulative = 0
    peak = 0
    peak_date = series[0][0]
    mdd_amount = 0
    mdd_peak = 0
    mdd_trough = 0
    mdd_peak_date = series[0][0]
    mdd_trough_date = series[0][0]

    for day_key, daily_pnl in series:
        cumulative += daily_pnl
        if cumulative > peak:
            peak = cumulative
            peak_date = day_key
        drawdown = peak - cumulative
        if drawdown > mdd_amount:
            mdd_amount = drawdown
            mdd_peak = peak
            mdd_trough = cumulative
            mdd_peak_date = peak_date
            mdd_trough_date = day_key

    mdd_pct = (mdd_amount / mdd_peak * 100) if mdd_peak > 0 else 0.0

    return {
        "mdd_pct": round(mdd_pct, 2),
        "mdd_amount": mdd_amount,
        "peak": mdd_peak,
        "trough": mdd_trough,
        "peak_date": mdd_peak_date,
        "trough_date": mdd_trough_date,
    }


def get_sharpe_ratio(
    session: Session, start_date: date, end_date: date,
    risk_free_rate: float = 0.035,
) -> dict[str, Any]:
    """기간 내 Sharpe Ratio를 계산한다.

    Sharpe = (평균 일별 수익 - 무위험수익률/252) / 일별 수익 표준편차 * sqrt(252)

    Args:
        session: DB 세션
        start_date: 시작일
        end_date: 종료일
        risk_free_rate: 연간 무위험수익률 (기본 3.5%)

    Returns:
        Sharpe Ratio 관련 지표
    """
    series = _daily_pnl_series(session, start_date, end_date)
    if len(series) < 2:
        return {"sharpe_ratio": 0.0, "sortino_ratio": 0.0, "trading_days": len(series)}

    returns = [pnl for _, pnl in series]
    avg_return = sum(returns) / len(returns)
    daily_rf = risk_free_rate / 252

    # 표준편차 (전체)
    variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0

    sharpe = ((avg_return - daily_rf) / std_dev * math.sqrt(252)) if std_dev > 0 else 0.0

    # Sortino (하방 편차만)
    downside = [r for r in returns if r < 0]
    if len(downside) >= 2:
        down_var = sum(r ** 2 for r in downside) / (len(downside) - 1)
        down_std = math.sqrt(down_var) if down_var > 0 else 0.0
        sortino = ((avg_return - daily_rf) / down_std * math.sqrt(252)) if down_std > 0 else 0.0
    else:
        sortino = 0.0

    return {
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "avg_daily_pnl": round(avg_return),
        "daily_std_dev": round(std_dev),
        "trading_days": len(series),
    }


def get_profit_factor(
    session: Session, start_date: date, end_date: date,
) -> dict[str, Any]:
    """기간 내 Profit Factor 및 Win/Loss 비율을 계산한다.

    Profit Factor = 총 수익 / 총 손실 (절대값)

    Args:
        session: DB 세션
        start_date: 시작일
        end_date: 종료일

    Returns:
        Profit Factor 및 Win/Loss 관련 지표
    """
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)

    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= start,
            Trade.traded_at < end,
            Trade.trade_type == TradeType.SELL,
            Trade.profit_loss_amount.isnot(None),
        )
    ).scalars().all()

    wins = [t for t in sells if (t.profit_loss_amount or 0) > 0]
    losses = [t for t in sells if (t.profit_loss_amount or 0) < 0]
    breakeven = [t for t in sells if (t.profit_loss_amount or 0) == 0]

    total_profit = sum(t.profit_loss_amount for t in wins) if wins else 0
    total_loss = abs(sum(t.profit_loss_amount for t in losses)) if losses else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float("inf") if total_profit > 0 else 0.0

    avg_win = (total_profit / len(wins)) if wins else 0
    avg_loss = (total_loss / len(losses)) if losses else 0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    win_rate = (len(wins) / len(sells) * 100) if sells else 0.0

    return {
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "total_profit": total_profit,
        "total_loss": total_loss,
        "win_count": len(wins),
        "loss_count": len(losses),
        "breakeven_count": len(breakeven),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win),
        "avg_loss": round(avg_loss),
        "payoff_ratio": round(payoff_ratio, 2),
    }


def get_consecutive_losses(
    session: Session, start_date: date, end_date: date,
) -> dict[str, Any]:
    """기간 내 최대 연속 손실/수익 횟수를 계산한다.

    Args:
        session: DB 세션
        start_date: 시작일
        end_date: 종료일

    Returns:
        연속 손실/수익 관련 지표
    """
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)

    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= start,
            Trade.traded_at < end,
            Trade.trade_type == TradeType.SELL,
            Trade.profit_loss_amount.isnot(None),
        )
        .order_by(Trade.traded_at)
    ).scalars().all()

    max_win_streak = 0
    max_loss_streak = 0
    current_win = 0
    current_loss = 0

    for t in sells:
        pnl = t.profit_loss_amount or 0
        if pnl > 0:
            current_win += 1
            current_loss = 0
            max_win_streak = max(max_win_streak, current_win)
        elif pnl < 0:
            current_loss += 1
            current_win = 0
            max_loss_streak = max(max_loss_streak, current_loss)
        else:
            current_win = 0
            current_loss = 0

    return {
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "current_win_streak": current_win,
        "current_loss_streak": current_loss,
        "total_sells": len(sells),
    }


def get_strategy_win_rates(
    session: Session, lookback_days: int = 30,
) -> dict[str, float]:
    """전략(signal_type)별 승률을 계산하여 반환한다.

    앙상블 가중치 자동 조정에 사용된다.

    Args:
        session: DB 세션
        lookback_days: 분석 기간 (일수)

    Returns:
        {전략명: 승률(0.0~1.0)} 딕셔너리. 데이터 없는 전략은 0.5.
    """
    since = datetime.now() - timedelta(days=lookback_days)

    sells = session.execute(
        select(Trade)
        .where(
            Trade.traded_at >= since,
            Trade.trade_type == TradeType.SELL,
            Trade.signal_type.isnot(None),
            Trade.profit_loss_amount.isnot(None),
        )
    ).scalars().all()

    by_strategy: dict[str, dict[str, int]] = {}
    for t in sells:
        key = t.signal_type or "UNKNOWN"
        if key not in by_strategy:
            by_strategy[key] = {"wins": 0, "total": 0}
        by_strategy[key]["total"] += 1
        if (t.profit_loss_amount or 0) > 0:
            by_strategy[key]["wins"] += 1

    return {
        name: stats["wins"] / stats["total"] if stats["total"] > 0 else 0.5
        for name, stats in by_strategy.items()
    }


def get_prediction_calibration(
    session: Session,
    window_days: int = 30,
) -> dict[str, Any]:
    """제안서의 prediction과 실측을 카테고리별로 집계한다.

    Phase 4 Decision Observability. 실측 비교는 후속 Phase 5(리포트 사이클)에서
    win_rate 등을 매핑해 채운다. 본 함수는 prediction 분포만 우선 노출.
    """
    from datetime import UTC as _UTC
    since = datetime.now(_UTC) - timedelta(days=window_days)
    stmt = select(Proposal).where(Proposal.created_at >= since)
    rows = list(session.execute(stmt).scalars().all())
    categories: dict[str, dict[str, dict[str, Any]]] = {}
    with_pred = 0
    for p in rows:
        if not p.prediction:
            continue
        with_pred += 1
        cat_key = p.category.value
        cat_bucket = categories.setdefault(cat_key, {})
        for k, v in p.prediction.items():
            metric = cat_bucket.setdefault(
                k, {"count": 0, "sum_predicted": 0.0, "avg_predicted": 0.0},
            )
            metric["count"] += 1
            metric["sum_predicted"] += float(v)
            metric["avg_predicted"] = metric["sum_predicted"] / metric["count"]
    return {
        "window_days": window_days,
        "proposal_count": len(rows),
        "with_prediction_count": with_pred,
        "categories": categories,
    }


def get_recurrence_risk(
    session: Session,
    window_days: int = 7,
    min_edits: int = 3,
) -> dict[str, Any]:
    """동일 component/파일을 윈도우 내 min_edits회 이상 수정한 케이스 집계.

    재발 위험 신호 — 같은 모듈을 단기에 반복 수정한다는 것은 일회성 fix가
    부족했음을 의미. Telegram 결산과 대시보드에 노출.
    """
    from datetime import UTC as _UTC
    since = datetime.now(_UTC) - timedelta(days=window_days)
    stmt = (
        select(ImplementationLog)
        .where(ImplementationLog.implemented_at >= since)
        .order_by(ImplementationLog.implemented_at)
    )
    logs = list(session.execute(stmt).scalars().all())

    file_counts: dict[str, int] = {}
    comp_counts: dict[str, int] = {}
    for log in logs:
        if not log.changed_files:
            continue
        files = (
            log.changed_files.get("files")
            if isinstance(log.changed_files, dict)
            else None
        )
        if not files:
            continue
        seen_in_log_files: set[str] = set()
        seen_in_log_comps: set[str] = set()
        for f in files:
            if not isinstance(f, dict):
                continue
            path = f.get("path", "")
            comp = f.get("component", "other")
            if path and path not in seen_in_log_files:
                file_counts[path] = file_counts.get(path, 0) + 1
                seen_in_log_files.add(path)
            if comp and comp not in seen_in_log_comps:
                comp_counts[comp] = comp_counts.get(comp, 0) + 1
                seen_in_log_comps.add(comp)

    risk_files = sorted(
        (
            {"path": p, "edit_count": c}
            for p, c in file_counts.items()
            if c >= min_edits
        ),
        key=lambda x: -x["edit_count"],
    )
    risk_components = sorted(
        (
            {"component": comp, "edit_count": c}
            for comp, c in comp_counts.items()
            if c >= min_edits
        ),
        key=lambda x: -x["edit_count"],
    )
    return {
        "window_days": window_days,
        "min_edits": min_edits,
        "risk_files": risk_files,
        "risk_components": risk_components,
    }
