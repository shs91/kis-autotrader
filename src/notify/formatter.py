"""Telegram 알림 메시지 포맷팅 모듈."""

from __future__ import annotations


def format_buy(stock_name: str, stock_code: str, quantity: int, price: int) -> str:
    """매수 체결 알림 메시지를 생성한다."""
    return (
        f"<b>[매수]</b> {stock_name}({stock_code})\n"
        f"{quantity}주 @ {price:,}원"
    )


def format_sell(
    stock_name: str, stock_code: str, quantity: int, price: int, reason: str
) -> str:
    """매도 체결 알림 메시지를 생성한다."""
    if reason == "손절":
        prefix = "\U0001f534"  # 빨간 원
        tag = "손절"
    else:
        prefix = "\U0001f7e2"  # 초록 원
        tag = "매도"
    return (
        f"{prefix} <b>[{tag}]</b> {stock_name}({stock_code})\n"
        f"{quantity}주 @ {price:,}원\n"
        f"사유: {reason}"
    )


def format_daily_summary(
    trade_date: str, count: int, profit_loss: int, rate: float
) -> str:
    """일일 결산 알림 메시지를 생성한다."""
    sign = "+" if profit_loss >= 0 else ""
    return (
        f"<b>[결산]</b> {trade_date}\n"
        f"체결: {count}건\n"
        f"손익: {sign}{profit_loss:,}원 ({sign}{rate:.2f}%)"
    )


def format_error(context: str, error: str) -> str:
    """에러 알림 메시지를 생성한다."""
    truncated = error[:200]
    return (
        f"\U0001f6a8 <b>[에러]</b> {context}\n"
        f"<code>{truncated}</code>"
    )


def format_system(message: str) -> str:
    """시스템 알림 메시지를 생성한다."""
    return f"<b>[시스템]</b> {message}"
