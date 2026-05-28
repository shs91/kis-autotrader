"""일일 헬스체크 작업.

평일 점심(12:30) + 장 마감 직후(15:35) 두 차례, 매매 활동 수치와
잔고를 수집해 Telegram으로 전송한다. 매매가 0건이면 경고 마커와 함께
주된 매수 거절 사유를 함께 알린다.

설계 의도:
- 운영 영향 0: 수집·전송 중 에러는 모두 swallow.
- 휴장일 스킵: ``src.scheduler.holidays.is_market_closed`` 위임.
- 엔진 없으면 스킵: 부트스트랩 단계 보호.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select

from src.db.models import EventLog, Order, OrderType, Signal
from src.db.session import get_session
from src.notify.telegram import TelegramNotifier
from src.scheduler.holidays import is_market_closed
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.engine import TradingEngine

logger = setup_logger(__name__)
_KST = ZoneInfo("Asia/Seoul")


class HealthcheckSlot(enum.Enum):
    """헬스체크 시점."""

    MORNING = "morning"  # 12:30 — 오전 매매 점검
    CLOSING = "closing"  # 15:35 — 장 마감 직후 종합


@dataclass(frozen=True)
class HealthcheckResult:
    """헬스체크 수집 결과 — 메시지 포맷팅 입력."""

    slot: HealthcheckSlot
    cycle_count: int
    api_calls: int
    api_limit: int
    signals_buy: int
    signals_sell: int
    orders_buy: int
    orders_sell: int
    holdings_count: int
    holdings_codes: list[str]
    deposit: int
    buy_reject_reasons: dict[str, int] = field(default_factory=dict)


def _slot_label(slot: HealthcheckSlot) -> str:
    return "오전" if slot is HealthcheckSlot.MORNING else "마감"


def build_healthcheck_message(result: HealthcheckResult) -> str:
    """HealthcheckResult → Telegram HTML 메시지."""
    label = _slot_label(result.slot)
    total_orders = result.orders_buy + result.orders_sell
    warn = total_orders == 0

    header = (
        f"⚠️ <b>일일 헬스체크 [{label}] — 매매 주의</b>"
        if warn
        else f"✅ <b>일일 헬스체크 [{label}]</b>"
    )
    lines = [
        header,
        "",
        f"• 사이클: <b>#{result.cycle_count}</b>",
        f"• API 호출: <b>{result.api_calls:,}</b> / {result.api_limit:,}",
        f"• 시그널: BUY {result.signals_buy} / SELL {result.signals_sell}",
        f"• 주문 — 매수: <b>{result.orders_buy}건</b>",
        f"• 주문 — 매도: <b>{result.orders_sell}건</b>",
        f"• 보유: {result.holdings_count}종목"
        + (f" ({', '.join(result.holdings_codes[:5])})" if result.holdings_codes else ""),
        f"• 예수금: {result.deposit:,}원",
    ]

    if warn and result.buy_reject_reasons:
        top = sorted(result.buy_reject_reasons.items(), key=lambda kv: -kv[1])[:3]
        reasons_fmt = ", ".join(f"{k}={v}" for k, v in top)
        lines += ["", f"주된 매수 거절 사유: {reasons_fmt}"]
    elif warn:
        lines += ["", "참고: 매수 거절 이력이 기록되지 않았습니다."]

    return "\n".join(lines)


def _today_kst_window() -> tuple[datetime, datetime]:
    """KST 기준 today의 [start, end) UTC-naive 구간."""
    today_kst = datetime.now(_KST).date()
    start_kst = datetime.combine(today_kst, time.min, tzinfo=_KST)
    end_kst = start_kst + timedelta(days=1)
    # DB는 timezone 정보를 컬럼별로 다르게 다룸. Order/EventLog 는 naive UTC default.
    # Signal은 timestamptz. 둘 모두에 안전하도록 aware로 두고 호출자가 변환.
    return start_kst, end_kst


def _query_today_counts() -> dict[str, Any]:
    """오늘자 signals/orders/거절사유 카운트를 DB에서 수집한다.

    실패해도 호출자에게 예외를 던지지 않는다 — 빈 기본값 반환.
    """
    defaults: dict[str, Any] = {
        "signals_buy": 0,
        "signals_sell": 0,
        "orders_buy": 0,
        "orders_sell": 0,
        "api_calls": 0,
        "buy_reject_reasons": {},
    }
    try:
        start_kst, end_kst = _today_kst_window()
        # Order/EventLog: naive UTC. Signal: timestamptz.
        start_utc_naive = start_kst.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        end_utc_naive = end_kst.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

        with get_session() as session:
            # 1. signals (action_taken=True가 의미있는 매매 트리거)
            sig_q = select(
                func.sum(
                    func.case(
                        (Signal.signal_value.op("->>")("reason").ilike("%BUY%"), 1),
                        else_=0,
                    )
                ).label("buy_count"),
                func.sum(
                    func.case(
                        (Signal.signal_value.op("->>")("reason").ilike("%SELL%"), 1),
                        else_=0,
                    )
                ).label("sell_count"),
            ).where(
                and_(
                    Signal.created_at >= start_kst,
                    Signal.created_at < end_kst,
                )
            )
            row = session.execute(sig_q).one()
            buy = int(row.buy_count or 0)
            sell = int(row.sell_count or 0)

            # 2. orders
            ord_q = (
                select(Order.order_type, func.count(Order.id))
                .where(
                    and_(
                        Order.created_at >= start_utc_naive,
                        Order.created_at < end_utc_naive,
                    )
                )
                .group_by(Order.order_type)
            )
            o_buy = 0
            o_sell = 0
            for otype, cnt in session.execute(ord_q):
                if otype == OrderType.BUY:
                    o_buy = int(cnt)
                elif otype == OrderType.SELL:
                    o_sell = int(cnt)

            # 3. BUY_REJECT 카운트 (event_logs.category='trade', message에 'BUY_REJECT'/'매수 차단')
            reject_q = (
                select(EventLog.message, func.count(EventLog.id))
                .where(
                    and_(
                        EventLog.timestamp >= start_utc_naive,
                        EventLog.timestamp < end_utc_naive,
                        or_(
                            EventLog.message.ilike("%BUY_REJECT%"),
                            EventLog.message.ilike("%매수 차단%"),
                            EventLog.message.ilike("%DISCLOSURE_FATAL%"),
                        ),
                    )
                )
                .group_by(EventLog.message)
            )
            reasons: dict[str, int] = {}
            for msg, cnt in session.execute(reject_q):
                key = _extract_reject_reason(msg)
                reasons[key] = reasons.get(key, 0) + int(cnt)

            return {
                "signals_buy": buy,
                "signals_sell": sell,
                "orders_buy": o_buy,
                "orders_sell": o_sell,
                "api_calls": 0,  # engine에서 채워짐
                "buy_reject_reasons": reasons,
            }
    except Exception:
        logger.exception("헬스체크 DB 수집 실패 (알림은 기본값으로 계속 진행)")
        return defaults


def _extract_reject_reason(message: str) -> str:
    """이벤트 메시지에서 거절 사유 라벨을 추출한다.

    BRIDGE_SPEC 카테고리 식별자(예: DISCLOSURE_FATAL, RISK_HALT)가 메시지에
    포함되어 있으면 그것을 우선 사용한다. 못 찾으면 "OTHER" 폴백.
    """
    known = [
        "DISCLOSURE_FATAL",
        "DAILY_TRADE_LIMIT_PER_STOCK",
        "DAILY_TRADE_LIMIT",
        "POSITION_RATIO",
        "INSUFFICIENT_CASH",
        "LOW_CONFIDENCE",
        "MARKET_CLOSE_GUARD",
        "RISK_HALT",
    ]
    upper = message.upper()
    for k in known:
        if k in upper:
            return k
    if "매수 차단" in message:
        return "BUY_BLOCK"
    return "OTHER"


async def collect_healthcheck(
    engine: TradingEngine, *, slot: HealthcheckSlot
) -> HealthcheckResult:
    """engine과 DB에서 수치를 수집해 HealthcheckResult를 만든다."""
    counts = _query_today_counts()

    # KIS 잔고 — 실패해도 빈 값으로 계속.
    deposit = 0
    holdings_count = 0
    holdings_codes: list[str] = []
    try:
        balance = await engine._get_balance(force=False)  # noqa: SLF001
        deposit = int(getattr(balance, "deposit", 0) or 0)
        holdings = [h for h in getattr(balance, "holdings", []) if getattr(h, "quantity", 0) > 0]
        holdings_count = len(holdings)
        holdings_codes = [getattr(h, "stock_code", "") for h in holdings]
    except Exception:
        logger.exception("헬스체크 잔고 조회 실패 (0으로 표기하고 계속)")

    api_limit_attr: int | float
    try:
        from src.config import settings

        api_limit_attr = int(settings.rate_limit.daily_limit)
    except Exception:
        api_limit_attr = 50_000

    # daily_api_calls는 engine 내부에 노출돼 있지 않으면 0으로.
    api_calls = int(getattr(engine, "_daily_api_calls", 0) or 0)

    return HealthcheckResult(
        slot=slot,
        cycle_count=int(getattr(engine, "_cycle_count", 0) or 0),
        api_calls=api_calls,
        api_limit=int(api_limit_attr),
        signals_buy=int(counts["signals_buy"]),
        signals_sell=int(counts["signals_sell"]),
        orders_buy=int(counts["orders_buy"]),
        orders_sell=int(counts["orders_sell"]),
        holdings_count=holdings_count,
        holdings_codes=holdings_codes,
        deposit=deposit,
        buy_reject_reasons=dict(counts.get("buy_reject_reasons", {}) or {}),
    )


async def run_healthcheck(
    engine: TradingEngine | None, *, slot: HealthcheckSlot
) -> None:
    """헬스체크 1회 실행. 휴장일·엔진없음은 조용히 스킵.

    내부 에러는 모두 swallow — 스케줄러 작업이 죽지 않도록 보호한다.
    """
    today = datetime.now(_KST).date()
    if is_market_closed(today):
        logger.info("휴장일이므로 헬스체크 스킵 (%s, slot=%s)", today, slot.value)
        return
    if engine is None:
        logger.warning("매매 엔진이 설정되지 않음 — 헬스체크 스킵 (slot=%s)", slot.value)
        return

    try:
        result = await collect_healthcheck(engine, slot=slot)
        message = build_healthcheck_message(result)
        notifier = TelegramNotifier()
        await notifier.notify_system(message)
        logger.info(
            "헬스체크 전송 완료 (slot=%s, orders=%d, signals_buy=%d, signals_sell=%d)",
            slot.value,
            result.orders_buy + result.orders_sell,
            result.signals_buy,
            result.signals_sell,
        )
    except Exception:
        logger.exception("헬스체크 실행 중 에러 (스케줄러에 영향 없음, slot=%s)", slot.value)
