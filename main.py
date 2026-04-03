"""KIS 주식 자동매매 시스템 엔트리포인트."""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import date

from src.api.health import HealthServer
from src.config import settings
from src.db.session import init_db
from src.engine import TradingEngine
from src.notify.bot import TelegramBot
from src.notify.telegram import TelegramNotifier
from src.db.event_logger import log_system
from src.scheduler.jobs import TradingScheduler
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _register_bot_commands(
    bot: TelegramBot,
    engine: TradingEngine,
    scheduler: TradingScheduler,
) -> None:
    """Telegram 봇 명령을 등록한다."""

    async def cmd_status(_args: str) -> str:
        """시스템 상태를 반환한다."""
        limiter = engine._client._limiter
        running = scheduler.scheduler.running
        return (
            f"<b>[상태]</b>\n"
            f"환경: {settings.kis.env}\n"
            f"스케줄러: {'가동중' if running else '중지'}\n"
            f"사이클: #{engine._cycle_count}\n"
            f"API 호출: {limiter.daily_count:,}/{limiter.daily_limit:,}\n"
            f"당일 매매: {engine._today_trade_count}건"
        )

    async def cmd_balance(_args: str) -> str:
        """잔고를 조회한다."""
        try:
            balance = await engine._get_balance()
            lines = [
                f"<b>[잔고]</b>",
                f"예수금: {balance.deposit:,}원",
                f"평가손익: {balance.total_profit_loss:,}원 ({balance.total_profit_rate:.2f}%)",
            ]
            for h in balance.holdings[:10]:
                lines.append(
                    f"  {h.stock_name}({h.stock_code}) {h.quantity}주 {h.profit_rate:+.2f}%"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"잔고 조회 실패: {e!s:.100}"

    async def cmd_today(_args: str) -> str:
        """당일 매매 요약을 반환한다."""
        return (
            f"<b>[당일 현황]</b> {date.today()}\n"
            f"사이클: #{engine._cycle_count}\n"
            f"매매: {engine._today_trade_count}건\n"
            f"관심종목: {len(engine._fixed_watchlist)}개\n"
            f"발굴종목: {len(engine._screened_codes)}개\n"
            f"한도 초과: {'예' if engine._daily_limit_reached else '아니오'}"
        )

    async def cmd_help(_args: str) -> str:
        """사용 가능한 명령을 반환한다."""
        return (
            "<b>[명령어]</b>\n"
            "/status — 시스템 상태\n"
            "/balance — 잔고 조회\n"
            "/today — 당일 현황\n"
            "/help — 명령어 목록"
        )

    bot.register("status", cmd_status)
    bot.register("balance", cmd_balance)
    bot.register("today", cmd_today)
    bot.register("help", cmd_help)


async def main() -> None:
    """자동매매 시스템을 시작한다."""
    logger.info("=== KIS 주식 자동매매 시스템 시작 ===")
    logger.info("환경: %s", settings.kis.env)
    logger.info("계좌: %s", settings.kis.account_no)
    logger.info("API 호출 제한: %d건/초", settings.rate_limit.per_second)
    logger.info("최대 손실률: %.1f%%", settings.trading.max_loss_rate * 100)
    logger.info("최대 포지션 비율: %.1f%%", settings.trading.max_position_ratio * 100)
    logger.info("관심종목: %s", settings.trading.watchlist_codes)

    notifier = TelegramNotifier()

    # DB 초기화
    logger.info("데이터베이스 초기화 중...")
    init_db()

    # 매매 엔진 생성
    engine = TradingEngine()

    # 스케줄러에 엔진 연결 후 시작
    scheduler = TradingScheduler(engine=engine)
    scheduler.start()
    logger.info("스케줄러 시작 완료")

    # 헬스체크 서버 시작
    health_server: HealthServer | None = None
    if settings.health.enabled:
        health_server = HealthServer(port=settings.health.port)
        health_server.set_status_provider(
            lambda: {
                "scheduler_running": scheduler.scheduler.running,
                "cycle_count": engine._cycle_count,
                "daily_api_count": engine._client._limiter.daily_count,
            }
        )
        await health_server.start()

    # Telegram Bot 시작
    bot = TelegramBot()
    _register_bot_commands(bot, engine, scheduler)
    await bot.start()

    await notifier.notify_system(f"자동매매 시스템 가동 ({settings.kis.env})")
    log_system(f"시스템 시작 ({settings.kis.env})")

    # 종료 시그널 핸들러
    stop_event = asyncio.Event()

    def _handle_signal(sig: int, _frame: object) -> None:
        logger.info("종료 시그널 수신: %s", signal.Signals(sig).name)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("시스템 가동 중... (Ctrl+C로 종료)")

    try:
        await stop_event.wait()
    finally:
        logger.info("시스템 종료 중...")
        await bot.stop()
        if health_server:
            await health_server.stop()
        await notifier.notify_system("자동매매 시스템 종료")
        log_system("시스템 종료")
        scheduler.shutdown()
        logger.info("=== KIS 주식 자동매매 시스템 종료 ===")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
