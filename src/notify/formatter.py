"""Telegram 알림 메시지 포맷팅 모듈.

Telegram HTML parse_mode를 사용한다.
지원 태그: <b>, <i>, <code>, <pre>
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.api.account import Balance, Execution


# ── 매수/매도 알림에 사용하는 경량 데이터 ────────────────────


@dataclass
class BuyDetail:
    """매수 알림에 필요한 부가 정보."""

    total_amount: int = 0  # 매수 총액 (quantity × price)
    strategy: str = ""  # 전략명 (예: 이동평균교차(5/20))
    reason: str = ""  # 시그널 근거 (예: 골든크로스)
    confidence: float = 0.0  # 시그널 신뢰도 (0.0~1.0)


@dataclass
class SellDetail:
    """매도 알림에 필요한 부가 정보."""

    total_amount: int = 0  # 매도 총액
    avg_price: float = 0.0  # 평균 매입가
    profit_loss: int = 0  # 실현 손익
    profit_rate: float = 0.0  # 실현 수익률 (%)


# ── 포맷 함수 ─────────────────────────────────────────────


def format_buy(
    stock_name: str,
    stock_code: str,
    quantity: int,
    price: int,
    detail: BuyDetail | None = None,
) -> str:
    """매수 체결 알림 메시지를 생성한다."""
    total = detail.total_amount if detail and detail.total_amount else quantity * price
    lines = [
        f"\U0001f4c8 <b>[매수]</b> {stock_name}({stock_code})",
        "─" * 20,
        f"• 수량: {quantity}주 × {price:,}원",
        f"• 금액: {total:,}원",
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
    price: int,
    reason: str,
    detail: SellDetail | None = None,
) -> str:
    """매도 체결 알림 메시지를 생성한다."""
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
        f"• 수량: {quantity}주 × {price:,}원",
        f"• 금액: {total:,}원",
    ]
    if detail and detail.avg_price > 0:
        lines.append(f"• 매입가: {detail.avg_price:,.0f}원")
    if detail and detail.profit_loss != 0:
        sign = "+" if detail.profit_loss > 0 else ""
        lines.append(
            f"• 손익: {sign}{detail.profit_loss:,}원 ({sign}{detail.profit_rate:.2f}%)"
        )
    if reason not in ("손절", "익절"):
        lines.append(f"• 사유: {reason}")
    return "\n".join(lines)


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
        f"• 실현손익: {sign}{profit_loss:,}원 ({sign}{rate:.2f}%)"
    )

    # 체결 내역 (최대 10건)
    if executions:
        lines.append("")
        lines.append("\U0001f4cb <b>체결 내역</b>")
        display = executions[:10]
        for e in display:
            side_emoji = "\U0001f7e2" if e.side == "매수" else "\U0001f534"
            lines.append(
                f"  {side_emoji} {e.side} {e.stock_name} {e.quantity}주 @ {e.price:,}원"
            )
        if len(executions) > 10:
            lines.append(f"  ... 외 {len(executions) - 10}건")

    # 계좌 현황
    if balance:
        bal_sign = "+" if balance.total_profit_loss >= 0 else ""
        lines.append("")
        lines.append("\U0001f4b0 <b>계좌 현황</b>")
        lines.append(f"  • 예수금: {balance.deposit:,}원")
        lines.append(f"  • 평가금: {balance.total_eval_amount:,}원")
        lines.append(
            f"  • 평가손익: {bal_sign}{balance.total_profit_loss:,}원"
            f" ({bal_sign}{balance.total_profit_rate:.2f}%)"
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
