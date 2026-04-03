"""KIS 주식 자동매매 시스템 엔트리포인트."""

from __future__ import annotations

import asyncio
import signal
import sys

from src.config import settings
from src.db.session import init_db
from src.engine import TradingEngine
from src.notify.telegram import TelegramNotifier
from src.scheduler.jobs import TradingScheduler
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


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

    await notifier.notify_system(f"자동매매 시스템 가동 ({settings.kis.env})")

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
        await notifier.notify_system("자동매매 시스템 종료")
        scheduler.shutdown()
        logger.info("=== KIS 주식 자동매매 시스템 종료 ===")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
