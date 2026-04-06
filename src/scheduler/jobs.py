"""APScheduler 작업 정의 모듈."""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, JobSubmissionEvent
from apscheduler.schedulers.background import BackgroundScheduler

from src.config import settings
from src.scheduler.holidays import is_market_closed
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.engine import TradingEngine

logger = setup_logger(__name__)

# 스케줄러 상수
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 0
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 20
PRE_MARKET_HOUR = 8
PRE_MARKET_MINUTE = 30
POST_MARKET_HOUR = 15
POST_MARKET_MINUTE = 40
MISFIRE_GRACE_TIME = 60
MAX_INSTANCES = 1


def _calculate_trading_interval(stock_count: int) -> float:
    """종목 수에 따른 최소 시세 조회 간격(초)을 계산한다.

    API 초당 호출 제한(기본 3건/초)을 준수하기 위해
    종목 수에 비례하여 조회 간격을 산출한다.
    종목당 일봉+현재가 = 2건 호출이므로 이를 반영한다.

    Args:
        stock_count: 모니터링 대상 종목 수

    Returns:
        시세 조회 주기 (초 단위, 소수점)
    """
    rate_limit = settings.rate_limit.per_second
    if stock_count <= 0:
        return 1.0
    # 종목당 2건(일봉+현재가) + 잔고 1건 = stock_count * 2 + 1
    calls_per_cycle = stock_count * 2 + 1
    # 여유 계수 1.2를 곱하여 안전 마진 확보
    interval = math.ceil((calls_per_cycle / rate_limit) * 1.2 * 10) / 10
    return max(interval, 10.0)  # 최소 10초 간격


def _run_async(coro: object) -> None:
    """비동기 코루틴을 동기 컨텍스트에서 실행한다.

    예외가 발생해도 스케줄러 작업 자체는 죽지 않도록 보호한다.
    APScheduler는 작업에서 미처리 예외가 발생하면 해당 작업을 에러로
    표시하고 후속 실행을 중단할 수 있으므로, 반드시 여기서 처리한다.
    """
    try:
        asyncio.run(coro)
    except Exception:
        logger.exception("스케줄러 작업 실행 중 에러 발생 (다음 실행에 영향 없음)")


class TradingScheduler:
    """매매 스케줄러.

    APScheduler를 이용하여 장 시작 전/중/후 작업을 스케줄링한다.
    TradingEngine을 주입받아 실제 매매 로직을 실행한다.
    """

    def __init__(self, engine: TradingEngine | None = None) -> None:
        """스케줄러를 초기화한다.

        Args:
            engine: 매매 엔진 인스턴스
        """
        self._scheduler = BackgroundScheduler(
            job_defaults={
                "misfire_grace_time": MISFIRE_GRACE_TIME,
                "max_instances": MAX_INSTANCES,
            }
        )
        self._scheduler.add_listener(
            self._on_max_instances, EVENT_JOB_MAX_INSTANCES,
        )
        self._engine = engine
        self._stock_count: int = len(settings.trading.watchlist_codes)

    @property
    def scheduler(self) -> BackgroundScheduler:
        """내부 스케줄러 인스턴스를 반환한다."""
        return self._scheduler

    @staticmethod
    def _on_max_instances(event: JobSubmissionEvent) -> None:
        """max_instances 초과로 작업 실행이 스킵되었을 때 호출된다."""
        logger.warning(
            "maximum number of running instances reached — 작업 스킵: %s",
            event.job_id,
        )

    def set_engine(self, engine: TradingEngine) -> None:
        """매매 엔진을 설정한다.

        Args:
            engine: 매매 엔진 인스턴스
        """
        self._engine = engine
        self._stock_count = len(engine._watchlist)
        logger.info("매매 엔진 연결 완료 (종목 수: %d)", self._stock_count)

    def set_stock_count(self, count: int) -> None:
        """모니터링 대상 종목 수를 설정한다.

        Args:
            count: 종목 수
        """
        self._stock_count = count
        logger.info("모니터링 종목 수 설정: %d개", count)

    def pre_market_job(self) -> None:
        """장 시작 전 작업 (08:30)."""
        if is_market_closed():
            logger.info("휴장일이므로 장 시작 전 작업 스킵")
            return
        if self._engine is None:
            logger.warning("매매 엔진이 설정되지 않음, 스킵")
            return
        _run_async(self._engine.pre_market())

    def trading_job(self) -> None:
        """장중 매매 작업 (09:00~15:20 반복)."""
        if self._engine is None:
            logger.warning("매매 엔진이 설정되지 않음, 스킵")
            return
        _run_async(self._engine.run_trading_cycle())

    def post_market_job(self) -> None:
        """장 마감 후 작업 (15:40)."""
        if is_market_closed():
            logger.info("휴장일이므로 장 마감 후 작업 스킵")
            return
        if self._engine is None:
            logger.warning("매매 엔진이 설정되지 않음, 스킵")
            return
        _run_async(self._engine.post_market())

    @staticmethod
    def _heartbeat() -> None:
        """스케줄러 쓰레드 keepalive용 heartbeat.

        APScheduler BackgroundScheduler는 다음 작업까지 threading.Event.wait()로
        sleep하는데, macOS에서 장시간(수십 시간) sleep 시 쓰레드가 깨어나지 못하는
        문제가 있다. 30분마다 깨워서 쓰레드를 활성 상태로 유지한다.
        """

    def _register_jobs(self) -> None:
        """모든 스케줄 작업을 등록한다."""
        # 스케줄러 쓰레드 keepalive (30분 간격)
        self._scheduler.add_job(
            func=self._heartbeat,
            trigger="interval",
            minutes=30,
            id="heartbeat",
            name="스케줄러 heartbeat",
            replace_existing=True,
        )

        # 장 시작 전 작업 (평일 08:30)
        self._scheduler.add_job(
            func=self.pre_market_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=PRE_MARKET_HOUR,
            minute=PRE_MARKET_MINUTE,
            id="pre_market_job",
            name="장 시작 전 작업",
            replace_existing=True,
        )
        logger.info(
            "장 시작 전 작업 등록: 평일 %02d:%02d",
            PRE_MARKET_HOUR,
            PRE_MARKET_MINUTE,
        )

        # 장중 매매 작업 (평일 09:00~15:20, 종목 수에 따른 간격)
        interval_seconds = _calculate_trading_interval(self._stock_count)

        # 매일 장 시작 시 trading_job을 재등록하는 래퍼 작업
        def _start_trading_job() -> None:
            """장 시작 시 당일 trading_job을 등록한다."""
            today = date.today()
            if is_market_closed(today):
                logger.info("휴장일이므로 장중 매매 작업 스킵 (%s)", today)
                return

            start = datetime.combine(today, time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE))
            end = datetime.combine(today, time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE))

            existing = self._scheduler.get_job("trading_job")
            if existing:
                self._scheduler.remove_job("trading_job")

            self._scheduler.add_job(
                func=self.trading_job,
                trigger="interval",
                seconds=interval_seconds,
                start_date=start,
                end_date=end,
                id="trading_job",
                name="장중 매매 작업",
            )
            logger.info(
                "장중 매매 작업 등록: %s %02d:%02d~%02d:%02d, 간격=%.1f초",
                today,
                MARKET_OPEN_HOUR,
                MARKET_OPEN_MINUTE,
                MARKET_CLOSE_HOUR,
                MARKET_CLOSE_MINUTE,
                interval_seconds,
            )

        # 매일 08:55에 당일 trading_job을 등록
        self._scheduler.add_job(
            func=_start_trading_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=8,
            minute=55,
            id="register_trading_job",
            name="장중 매매 작업 등록",
            replace_existing=True,
        )

        # 오늘이 평일이고 아직 장중 시간이면 즉시 등록
        now = datetime.now()
        market_close_today = datetime.combine(date.today(), time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE))
        if not is_market_closed() and now < market_close_today:
            _start_trading_job()
        else:
            logger.info(
                "장중 매매 작업: 평일 %02d:%02d~%02d:%02d, 간격=%.1f초 (종목 %d개) — 다음 장 시작 시 활성화",
                MARKET_OPEN_HOUR,
                MARKET_OPEN_MINUTE,
                MARKET_CLOSE_HOUR,
                MARKET_CLOSE_MINUTE,
                interval_seconds,
                self._stock_count,
            )

        # 장 마감 후 작업 (평일 15:40)
        self._scheduler.add_job(
            func=self.post_market_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=POST_MARKET_HOUR,
            minute=POST_MARKET_MINUTE,
            id="post_market_job",
            name="장 마감 후 작업",
            replace_existing=True,
        )
        logger.info(
            "장 마감 후 작업 등록: 평일 %02d:%02d",
            POST_MARKET_HOUR,
            POST_MARKET_MINUTE,
        )

    def start(self) -> None:
        """스케줄러를 시작한다."""
        self._register_jobs()
        self._scheduler.start()
        logger.info("매매 스케줄러 시작")

    def shutdown(self) -> None:
        """스케줄러를 종료한다."""
        self._scheduler.shutdown(wait=True)
        logger.info("매매 스케줄러 종료")
