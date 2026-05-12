"""Telegram Bot API를 통한 알림 전송 모듈."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx

from src.config import settings
from src.db.repository import ImplementationLogRepository
from src.db.session import get_session
from src.notify.formatter import (
    BuyDetail,
    SellDetail,
    format_buy,
    format_daily_summary,
    format_error,
    format_sell,
    format_system,
)
from src.utils.logger import setup_logger
from src.utils.versioning import read_current_version

if TYPE_CHECKING:
    from src.api.account import Balance, Execution

logger = setup_logger(__name__)
_KST = ZoneInfo("Asia/Seoul")

SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT = 10.0


class TelegramNotifier:
    """Telegram으로 알림을 전송한다.

    알림 레벨:
    - urgent=True: 소리/진동 알림 (손절, 에러, 서비스 다운)
    - urgent=False: 무음 알림 (일반 체결, 결산, 시스템 시작)

    알림 전송 실패는 매매 로직에 영향을 주지 않는다.
    """

    def __init__(self) -> None:
        """TelegramNotifier를 초기화한다."""
        self._token = settings.telegram.bot_token
        self._chat_id = settings.telegram.chat_id
        self._enabled = settings.telegram.enabled

    async def send(self, message: str, *, urgent: bool = False) -> None:
        """메시지를 전송한다. 실패해도 예외를 전파하지 않는다.

        Args:
            message: 전송할 메시지 (HTML 형식)
            urgent: True면 소리/진동 알림, False면 무음 전송
        """
        if not self._enabled:
            return
        if not self._token or not self._chat_id:
            logger.warning("Telegram 설정 미완료 (토큰 또는 채팅ID 없음), 알림 스킵")
            return
        try:
            url = SEND_MESSAGE_URL.format(token=self._token)
            payload: dict[str, object] = {
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_notification": not urgent,
            }
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(url, json=payload)
                if response.status_code != 200:
                    logger.warning(
                        "Telegram 전송 실패: status=%d, body=%s",
                        response.status_code,
                        response.text[:200],
                    )
        except Exception:
            logger.exception("Telegram 알림 전송 중 에러 (매매에 영향 없음)")

    # ── 매수 알림 (무음) ──────────────────────────────────

    async def notify_buy(
        self,
        stock_name: str,
        stock_code: str,
        quantity: int,
        price: int,
        *,
        strategy: str = "",
        reason: str = "",
        confidence: float = 0.0,
    ) -> None:
        """매수 체결 알림을 전송한다 (무음).

        Args:
            stock_name: 종목명
            stock_code: 종목코드
            quantity: 수량
            price: 체결가
            strategy: 전략명
            reason: 시그널 근거
            confidence: 시그널 신뢰도
        """
        detail = BuyDetail(
            total_amount=quantity * price,
            strategy=strategy,
            reason=reason,
            confidence=confidence,
        )
        await self.send(format_buy(stock_name, stock_code, quantity, price, detail))

    # ── 매도 알림 (손절은 긴급) ───────────────────────────

    async def notify_sell(
        self,
        stock_name: str,
        stock_code: str,
        quantity: int,
        price: int,
        reason: str,
        *,
        avg_price: float = 0.0,
    ) -> None:
        """매도 체결 알림을 전송한다. 손절은 긴급.

        Args:
            stock_name: 종목명
            stock_code: 종목코드
            quantity: 수량
            price: 체결가
            reason: 매도 사유
            avg_price: 평균 매입가 (0이면 손익 미표시)
        """
        detail: SellDetail | None = None
        if avg_price > 0:
            profit_loss = int((price - avg_price) * quantity)
            profit_rate = ((price - avg_price) / avg_price) * 100
            detail = SellDetail(
                total_amount=quantity * price,
                avg_price=avg_price,
                profit_loss=profit_loss,
                profit_rate=profit_rate,
            )

        is_urgent = reason == "손절"
        await self.send(
            format_sell(stock_name, stock_code, quantity, price, reason, detail),
            urgent=is_urgent,
        )

    # ── 일일 결산 알림 (무음) ─────────────────────────────

    async def notify_daily_summary(
        self,
        trade_date: str,
        count: int,
        profit_loss: int,
        rate: float,
        *,
        buy_count: int = 0,
        sell_count: int = 0,
        executions: list[Execution] | None = None,
        balance: Balance | None = None,
    ) -> None:
        """일일 결산 알림을 전송한다 (무음).

        Args:
            trade_date: 매매일 (ISO 형식)
            count: 총 체결 건수
            profit_loss: 실현 손익
            rate: 실현 수익률
            buy_count: 매수 건수
            sell_count: 매도 건수
            executions: 체결 내역 목록
            balance: 잔고 정보
        """
        version = _safe_read_version()
        today_bumps = _query_today_bumps(trade_date)
        await self.send(
            format_daily_summary(
                trade_date, count, profit_loss, rate,
                buy_count=buy_count,
                sell_count=sell_count,
                executions=executions,
                balance=balance,
                version=version,
                today_bumps=today_bumps,
            )
        )

    # ── 긴급 알림 (소리/진동) ────────────────────────────

    async def notify_error(self, context: str, error: str) -> None:
        """에러 알림을 전송한다 (긴급)."""
        await self.send(format_error(context, error), urgent=True)

    # ── 시스템 알림 (무음) ───────────────────────────────

    async def notify_system(self, message: str) -> None:
        """시스템 알림을 전송한다 (무음)."""
        await self.send(format_system(message))


def _safe_read_version() -> str | None:
    """현재 프로젝트 버전을 읽는다. 실패 시 None (알림 실패 방지)."""
    try:
        return read_current_version()
    except Exception:
        logger.debug("버전 읽기 실패, 결산 헤더 버전 생략")
        return None


def _query_today_bumps(trade_date: str) -> list[tuple[str, str, str]]:
    """`trade_date`에 적용된 자동 bump 내역을 조회한다.

    Args:
        trade_date: ISO 날짜 문자열 (예: "2026-05-12"). 파싱 실패 시 빈 목록.

    Returns:
        (version, category, title) 튜플 목록 (시간순). DB 조회 실패 시 빈 목록.
    """
    try:
        target = date.fromisoformat(trade_date)
    except ValueError:
        return []

    start = datetime.combine(target, time.min, tzinfo=_KST)
    end = start + timedelta(days=1)
    try:
        with get_session() as session:
            repo = ImplementationLogRepository(session)
            # 최근 50건 안에서 당일 항목만 필터 (보통 하루에 그보다 적음)
            recent = repo.list_recent(limit=50)
            bumps: list[tuple[str, str, str]] = []
            for log in recent:
                if not log.version:
                    continue
                if start <= log.implemented_at < end:
                    bumps.append((log.version, log.category.value, log.title))
            # 시간순 (과거 → 현재)
            bumps.reverse()
            return bumps
    except Exception:
        logger.debug("당일 bump 조회 실패, 결산에 변경 내역 생략", exc_info=True)
        return []
