"""Telegram 알림 메시지 포맷팅 모듈.

Telegram HTML parse_mode를 사용한다.
지원 태그: <b>, <i>, <code>, <pre>
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.market.profile import format_money

if TYPE_CHECKING:
    from src.api.account import Balance, Execution


# ── 매수/매도 알림에 사용하는 경량 데이터 ────────────────────


@dataclass
class BuyDetail:
    """매수 알림에 필요한 부가 정보."""

    total_amount: float = 0  # 매수 총액 (quantity × price). 해외는 USD float.
    strategy: str = ""  # 전략명 (예: 이동평균교차(5/20))
    reason: str = ""  # 시그널 근거 (예: 골든크로스)
    confidence: float = 0.0  # 시그널 신뢰도 (0.0~1.0)


@dataclass
class SellDetail:
    """매도 알림에 필요한 부가 정보."""

    total_amount: float = 0  # 매도 총액. 해외는 USD float.
    avg_price: float = 0.0  # 평균 매입가
    profit_loss: float = 0  # 실현 손익. 해외는 USD float.
    profit_rate: float = 0.0  # 실현 수익률 (%)


# ── 포맷 함수 ─────────────────────────────────────────────


def format_buy(
    stock_name: str,
    stock_code: str,
    quantity: int,
    price: float,
    detail: BuyDetail | None = None,
    currency: str = "KRW",
) -> str:
    """매수 체결 알림 메시지를 생성한다(통화 인지)."""
    total = detail.total_amount if detail and detail.total_amount else quantity * price
    lines = [
        f"\U0001f4c8 <b>[매수]</b> {stock_name}({stock_code})",
        "─" * 20,
        f"• 수량: {quantity}주 × {format_money(price, currency)}",
        f"• 금액: {format_money(total, currency)}",
    ]
    if detail and detail.strategy:
        lines.append(f"• 전략: {detail.strategy}")
    if detail and detail.reason:
        conf = f" (신뢰도 {detail.confidence:.0%})" if detail.confidence > 0 else ""
        lines.append(f"• 근거: {detail.reason}{conf}")
    return "\n".join(lines)


def format_sell(
    stock_name: str,
    stock_code: str,
    quantity: int,
    price: float,
    reason: str,
    detail: SellDetail | None = None,
    currency: str = "KRW",
) -> str:
    """매도 체결 알림 메시지를 생성한다(통화 인지)."""
    if reason == "손절":
        emoji = "\U0001f534"  # 빨간 원
        tag = "손절"
    elif reason == "익절":
        emoji = "\U0001f7e2"  # 초록 원
        tag = "익절"
    else:
        emoji = "\U0001f7e1"  # 노란 원
        tag = "매도"

    total = detail.total_amount if detail and detail.total_amount else quantity * price
    lines = [
        f"{emoji} <b>[{tag}]</b> {stock_name}({stock_code})",
        "─" * 20,
        f"• 수량: {quantity}주 × {format_money(price, currency)}",
        f"• 금액: {format_money(total, currency)}",
    ]
    if detail and detail.avg_price > 0:
        lines.append(f"• 매입가: {format_money(detail.avg_price, currency)}")
    if detail and detail.profit_loss != 0:
        sign = "+" if detail.profit_loss > 0 else ""
        lines.append(
            f"• 손익: {sign}{format_money(detail.profit_loss, currency)}"
            f" ({sign}{detail.profit_rate:.2f}%)"
        )
    if reason not in ("손절", "익절"):
        lines.append(f"• 사유: {reason}")
    return "\n".join(lines)


def eval_profit_rate(balance: Balance) -> float:
    """보유분 평가손익률(%)을 매입금액 합계 기준으로 계산한다.

    ``balance.total_profit_rate``는 KIS의 자산증감수익률(ASST_ICDC_ERNG_RT)이라
    평가손익 금액(EVLU_PFLS_SMTL_AMT)과 지표가 달라, 한 줄에 함께 표기하면 부호가
    어긋난다(예: +33,000원인데 -1.83%). 보유 종목 매입금액 합계로 평가손익률을
    계산해 금액과 일관되게 맞춘다.

    Args:
        balance: 잔고 정보.

    Returns:
        평가손익률(%). 매입금액이 0이면 0.0.
    """
    invested = sum(
        h.avg_price * h.quantity for h in balance.holdings if h.quantity > 0
    )
    if invested <= 0:
        return 0.0
    return balance.total_profit_loss / invested * 100.0


def format_daily_summary(
    trade_date: str,
    count: int,
    profit_loss: int,
    rate: float,
    buy_count: int = 0,
    sell_count: int = 0,
    executions: list[Execution] | None = None,
    balance: Balance | None = None,
    version: str | None = None,
    today_bumps: list[tuple[str, str, str]] | None = None,
    currency: str = "KRW",
) -> str:
    """일일 결산 알림 메시지를 생성한다.

    Args:
        trade_date: 매매일 (ISO 형식 문자열).
        count: 총 체결 건수.
        profit_loss: 실현 손익(원).
        rate: 실현 수익률(%).
        buy_count: 매수 체결 건수.
        sell_count: 매도 체결 건수.
        executions: 체결 내역.
        balance: 잔고 정보.
        version: 현재 프로젝트 버전 (예: "0.1.3"). 지정 시 헤더에 [vX.Y.Z] 표시.
        today_bumps: 당일 자동 bump 내역. (version, category, title) 튜플 목록.
    """
    sign = "+" if profit_loss >= 0 else ""
    emoji = "\U0001f4c8" if profit_loss >= 0 else "\U0001f4c9"

    header_prefix = f"[v{version}] " if version else ""
    lines = [
        f"{emoji} <b>{header_prefix}[일일 결산]</b> {trade_date}",
        "─" * 20,
    ]

    # 체결 요약
    if buy_count or sell_count:
        lines.append(
            f"• 체결: {count}건 (매수 {buy_count} / 매도 {sell_count})"
        )
    else:
        lines.append(f"• 체결: {count}건")

    lines.append(
        f"• 실현손익: {sign}{format_money(profit_loss, currency)} ({sign}{rate:.2f}%)"
    )

    # 체결 내역 (최대 10건)
    if executions:
        lines.append("")
        lines.append("\U0001f4cb <b>체결 내역</b>")
        display = executions[:10]
        for e in display:
            side_emoji = "\U0001f7e2" if e.side == "매수" else "\U0001f534"
            lines.append(
                f"  {side_emoji} {e.side} {e.stock_name} {e.quantity}주"
                f" @ {format_money(e.price, currency)}"
            )
        if len(executions) > 10:
            lines.append(f"  ... 외 {len(executions) - 10}건")

    # 계좌 현황
    if balance:
        bal_sign = "+" if balance.total_profit_loss >= 0 else ""
        bal_rate = eval_profit_rate(balance)
        lines.append("")
        lines.append("\U0001f4b0 <b>계좌 현황</b>")
        # 잔고는 balance.currency(시장 통화)로 — KRX KRW, US USD.
        lines.append(f"  • 예수금: {format_money(balance.deposit, balance.currency)}")
        lines.append(
            f"  • 평가금: {format_money(balance.total_eval_amount, balance.currency)}"
        )
        lines.append(
            f"  • 평가손익: {bal_sign}"
            f"{format_money(balance.total_profit_loss, balance.currency)}"
            f" ({bal_sign}{bal_rate:.2f}%)"
        )
        if balance.holdings:
            held = [h for h in balance.holdings if h.quantity > 0]
            lines.append(f"  • 보유: {len(held)}종목")

    # 당일 자동 bump 내역 (최대 5건)
    if today_bumps:
        lines.append("")
        lines.append("\U0001f4e6 <b>오늘 적용된 변경</b>")
        for ver, category, title in today_bumps[:5]:
            lines.append(f"  • v{ver} ({category}) — {title}")
        if len(today_bumps) > 5:
            lines.append(f"  ... 외 {len(today_bumps) - 5}건")

    return "\n".join(lines)


def format_error(context: str, error: str) -> str:
    """에러 알림 메시지를 생성한다."""
    truncated = error[:200]
    return (
        f"\U0001f6a8 <b>[에러]</b> {context}\n"
        f"<code>{truncated}</code>"
    )


def format_system(message: str) -> str:
    """시스템 알림 메시지를 생성한다."""
    return f"⚙️ <b>[시스템]</b> {message}"


# 매수 거절 사유 코드 → 한글 라벨 (engine._record_buy_reject reason 코드 기준, 없으면 원문 표시)
_REJECT_LABELS: dict[str, str] = {
    "LOW_CONFIDENCE": "저신뢰",
    "POSITION_RATIO": "포지션비율",
    "INSUFFICIENT_CASH": "예수금부족",
    "DAILY_TRADE_LIMIT": "일일한도",
    "DAILY_TRADE_LIMIT_PER_STOCK": "종목한도",
    "MARKET_CLOSE_GUARD": "마감임박",
    "MAX_CONSECUTIVE_LOSSES": "연패",
    "MAX_DAILY_DRAWDOWN": "일중손실",
}


def format_diagnostics(diag: dict[str, Any], currency: str = "KRW") -> str:
    """장 마감 매매 진단 알림 메시지를 생성한다(무음, 통화 인지).

    Args:
        diag: ``build_daily_diagnostics`` 결과 dict.
        currency: 예수금 표기 통화("KRW"|"USD").
    """
    trade_count = diag["trade_count"]
    emoji = "\U0001f4c8" if trade_count > 0 else "\U0001f6ab"
    lines = [
        f"\U0001f52d <b>[매매 진단]</b> {diag['trade_date']}",
        f"{emoji} {diag['headline']}",
        "",
    ]

    mc = diag["monitored_counts"]
    lines.append(
        f"\U0001f4e1 모니터링 {len(diag['monitored'])}종목 "
        f"(보유{mc.get('positions', 0)}/관심{mc.get('watchlist', 0)}/발굴{mc.get('screening', 0)})"
    )
    for m in diag["monitored"][:10]:
        lines.append(f"  • {m['code']} {m['name']} — {m['max_conf']:.2f}")

    sc = diag["screening"]
    lines.append("")
    lines.append(
        f"\U0001f50d 스크리닝 top{sc['ranked_total']} → 후보 avg {sc['candidate_avg']:.2f}/사이클"
    )
    if sc["risk_excluded"]:
        excluded = ", ".join(sc["risk_excluded"][:5])
        lines.append(f"  • 위험배제 {len(sc['risk_excluded'])}종목 ({excluded})")

    lines.append("")
    if diag["buy_rejects"]:
        parts = [f"{_REJECT_LABELS.get(k, k)}{v}" for k, v in diag["buy_rejects"].items()]
        lines.append("⛔ 매수게이트 차단: " + " · ".join(parts))
    else:
        lines.append("⛔ 매수게이트: 신호 0이라 도달 전 차단")

    lines.append("")
    lines.append(
        f"\U0001f4b0 예수금 {format_money(diag['deposit'], currency)}"
        f" · 보유 {diag['holdings']}종목"
    )
    return "\n".join(lines)


# ── 하네스 사이클 결산 (Phase 4) ────────────────────────────────

_MAX_APPLIED = 5
_MAX_RECURRENCE = 5
_MAX_PREDICTION = 5


def format_pipeline_summary(
    *,
    cycle_id: str,
    applied: list[dict[str, Any]],
    recurrence_risks: list[dict[str, Any]],
    prediction_misses: list[dict[str, Any]],
) -> str:
    """사이클 종료 후 3섹션 결산 카드 — Phase 4."""
    lines = [f"🛠 <b>하네스 사이클 결산</b> ({cycle_id})", ""]

    # 1. 오늘 적용
    lines.append("<b>📦 오늘 적용된 변경</b>")
    if not applied:
        lines.append("  변경 없음")
    else:
        for entry in applied[:_MAX_APPLIED]:
            title = entry.get("title", "(no title)")
            version = entry.get("version") or "-"
            lines.append(f"  • <code>{version}</code> {title}")
        if len(applied) > _MAX_APPLIED:
            lines.append(f"  외 {len(applied) - _MAX_APPLIED}건")
    lines.append("")

    # 2. 회귀 위험
    lines.append("<b>⚠️ 회귀 위험 (7일)</b>")
    if not recurrence_risks:
        lines.append("  회귀 위험 없음")
    else:
        for r in recurrence_risks[:_MAX_RECURRENCE]:
            comp = r.get("component") or r.get("path", "?")
            count = r.get("edit_count", 0)
            lines.append(f"  • {comp} — {count}회")
        if len(recurrence_risks) > _MAX_RECURRENCE:
            lines.append(f"  외 {len(recurrence_risks) - _MAX_RECURRENCE}건")
    lines.append("")

    # 3. 예측 미달
    lines.append("<b>📉 예측 미달 (지난주 대비)</b>")
    if not prediction_misses:
        lines.append("  예측 미달 없음")
    else:
        for m in prediction_misses[:_MAX_PREDICTION]:
            cat = m.get("category", "?")
            metric = m.get("metric", "?")
            lines.append(f"  • {cat} / {metric}")
        if len(prediction_misses) > _MAX_PREDICTION:
            lines.append(f"  외 {len(prediction_misses) - _MAX_PREDICTION}건")

    return "\n".join(lines)
