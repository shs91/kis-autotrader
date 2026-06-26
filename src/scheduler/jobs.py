"""APScheduler 작업 정의 모듈."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Coroutine
from datetime import datetime, time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, JobSubmissionEvent
from apscheduler.schedulers.background import BackgroundScheduler

from src.config import settings
from src.market.profile import MarketProfile, active_market_profile
from src.scheduler.holidays import is_market_closed
from src.utils.logger import setup_logger

QUOTA_PRE_MARKET_HOUR = 8
QUOTA_PRE_MARKET_MINUTE = 25
QUOTA_MARKET_OPEN_HOUR = 8
QUOTA_MARKET_OPEN_MINUTE = 55
QUOTA_POST_MARKET_HOUR = 15
QUOTA_POST_MARKET_MINUTE = 25

# 일일 헬스체크 (KST) — 오전 점검 + 마감 직후
HEALTHCHECK_MORNING_HOUR = 12
HEALTHCHECK_MORNING_MINUTE = 30
HEALTHCHECK_CLOSING_HOUR = 15
HEALTHCHECK_CLOSING_MINUTE = 35

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
SUMMARY_HOUR = 16
SUMMARY_MINUTE = 0
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
    min_interval = settings.trading.min_trading_interval_seconds
    if stock_count <= 0:
        # 종목 미확정(스크리닝 의존으로 셋업 시 0종목 등) 상황에서도 1초 폭주를
        # 막기 위해 설정 하한을 적용한다.
        return min_interval
    # 종목당 2건(일봉+현재가) + 잔고 1건 = stock_count * 2 + 1
    calls_per_cycle = stock_count * 2 + 1
    # 여유 계수 1.2를 곱하여 안전 마진 확보
    interval = math.ceil((calls_per_cycle / rate_limit) * 1.2 * 10) / 10
    return max(interval, min_interval)  # 설정 하한(기본 10초) 보장


def _run_async(coro: Coroutine[Any, Any, Any]) -> None:
    """비동기 코루틴을 동기 컨텍스트에서 실행한다.

    예외가 발생해도 스케줄러 작업 자체는 죽지 않도록 보호한다.
    APScheduler는 작업에서 미처리 예외가 발생하면 해당 작업을 에러로
    표시하고 후속 실행을 중단할 수 있으므로, 반드시 여기서 처리한다.
    """
    try:
        asyncio.run(coro)
    except Exception:
        logger.exception("스케줄러 작업 실행 중 에러 발생 (다음 실행에 영향 없음)")


async def _update_quota(quotas: dict[str, int]) -> None:
    """Redis에 역할별 API 할당량을 설정한다."""
    from src.api.rate_limiter import update_redis_quota

    await update_redis_quota(quotas)


class TradingScheduler:
    """매매 스케줄러.

    APScheduler를 이용하여 장 시작 전/중/후 작업을 스케줄링한다.
    TradingEngine을 주입받아 실제 매매 로직을 실행한다.
    """

    def __init__(
        self,
        engine: TradingEngine | None = None,
        market_profile: MarketProfile | None = None,
    ) -> None:
        """스케줄러를 초기화한다.

        Args:
            engine: 매매 엔진 인스턴스
            market_profile: 시장 프로파일 (None이면 MARKET env 기반 활성 시장)
        """
        # 시장별 타임존에서 cron을 돌린다 — US는 ET에서 같은 날 세션(자정 교차 회피),
        # KRX는 Asia/Seoul(KST 서버의 system-local과 동일 → 행동 불변).
        self._market = market_profile or active_market_profile()
        self._tz = ZoneInfo(self._market.timezone)
        self._scheduler = BackgroundScheduler(
            timezone=self._tz,
            job_defaults={
                "misfire_grace_time": MISFIRE_GRACE_TIME,
                "max_instances": MAX_INSTANCES,
            },
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
        """장 시작 전 작업 (장 시작 전, 시장별 시각)."""
        if is_market_closed(market_code=self._market.market_code):
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
        """장 마감 후 작업 (장 마감 후, 시장별 시각)."""
        if is_market_closed(market_code=self._market.market_code):
            logger.info("휴장일이므로 장 마감 후 작업 스킵")
            return
        if self._engine is None:
            logger.warning("매매 엔진이 설정되지 않음, 스킵")
            return
        _run_async(self._engine.post_market())

    def healthcheck_morning_job(self) -> None:
        """오전 헬스체크 (12:30 KST). 휴장일·엔진없음은 healthcheck 내부에서 스킵."""
        from src.scheduler.healthcheck import HealthcheckSlot, run_healthcheck

        _run_async(run_healthcheck(self._engine, slot=HealthcheckSlot.MORNING))

    def healthcheck_closing_job(self) -> None:
        """장 마감 직후 헬스체크 (15:35 KST)."""
        from src.scheduler.healthcheck import HealthcheckSlot, run_healthcheck

        _run_async(run_healthcheck(self._engine, slot=HealthcheckSlot.CLOSING))

    def summarize_daily_job(self) -> None:
        """일일 요약 집계 작업 (장 마감 후, 시장별 시각).

        trades, signals, screening_results, system_metrics를 집계하여
        daily_summary 테이블에 UPSERT한다. 이미 존재하면 덮어쓴다.
        """
        if is_market_closed(market_code=self._market.market_code):
            logger.info("휴장일이므로 일일 요약 집계 스킵")
            return

        try:
            from src.db.repository import DailySummaryRepository
            from src.db.session import get_session

            today = datetime.now(self._tz).date()
            with get_session() as session:
                repo = DailySummaryRepository(session)
                summary = repo.upsert_daily_summary(
                    today, self._market.market_code
                )
                logger.info(
                    "일일 요약 집계 완료: %s [%s] (매수=%d, 매도=%d, 손익=%d)",
                    today,
                    self._market.market_code,
                    summary.total_buy_count,
                    summary.total_sell_count,
                    summary.total_profit_loss,
                )
        except Exception:
            logger.exception("일일 요약 집계 실패 (매매에 영향 없음)")

    def cleanup_price_snapshots_job(self) -> None:
        """7일 초과 가격/후보 스냅샷을 삭제한다(롤링 정리). 시장 무관(공유 테이블)."""
        try:
            from datetime import UTC, timedelta

            from src.db.repository import (
                CandidateSnapshotRepository,
                PriceSnapshotRepository,
            )
            from src.db.session import get_session

            cutoff = datetime.now(UTC) - timedelta(days=7)
            with get_session() as session:
                deleted = PriceSnapshotRepository(session).delete_older_than(cutoff)
                deleted_cand = CandidateSnapshotRepository(session).delete_older_than(
                    cutoff
                )
            logger.info(
                "스냅샷 정리: 가격 %d행 / 후보 %d행 삭제 (7일 초과)",
                deleted,
                deleted_cand,
            )
        except Exception:
            logger.exception("스냅샷 정리 실패 (매매에 영향 없음)")

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

        # 시장별 스케줄 시각(시,분) — KRX는 jobs.py 기존 상수와 동일(행동 불변).
        th = self._market.trading_hours
        mc = self._market.market_code
        pre_h, pre_m = th.pre_market
        reg_h, reg_m = th.register
        open_h, open_m = th.market_open
        close_h, close_m = th.market_close
        post_h, post_m = th.post_market
        sum_h, sum_m = th.summary

        # 장 시작 전 작업 (평일)
        self._scheduler.add_job(
            func=self.pre_market_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=pre_h,
            minute=pre_m,
            id="pre_market_job",
            name="장 시작 전 작업",
            replace_existing=True,
        )
        logger.info("장 시작 전 작업 등록: 평일 %02d:%02d (%s)", pre_h, pre_m, mc)

        # 장중 매매 작업 (종목 수에 따른 간격)
        interval_seconds = _calculate_trading_interval(self._stock_count)

        # 매일 장 시작 시 trading_job을 재등록하는 래퍼 작업
        def _start_trading_job() -> None:
            """장 시작 시 당일 trading_job을 등록한다."""
            today = datetime.now(self._tz).date()
            if is_market_closed(today, mc):
                logger.info("휴장일이므로 장중 매매 작업 스킵 (%s)", today)
                return

            start = datetime.combine(today, time(open_h, open_m))
            end = datetime.combine(today, time(close_h, close_m))

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
                today, open_h, open_m, close_h, close_m, interval_seconds,
            )

        # 매일 장 시작 직전(register 시각)에 당일 trading_job을 등록
        self._scheduler.add_job(
            func=_start_trading_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=reg_h,
            minute=reg_m,
            id="register_trading_job",
            name="장중 매매 작업 등록",
            replace_existing=True,
        )

        # 오늘이 평일이고 아직 장중 시간이면 즉시 등록 (시장 타임존 기준)
        now = datetime.now(self._tz)
        market_close_today = datetime.combine(
            now.date(), time(close_h, close_m), tzinfo=self._tz
        )
        if not is_market_closed(now.date(), mc) and now < market_close_today:
            _start_trading_job()
        else:
            logger.info(
                "장중 매매 작업: 평일 %02d:%02d~%02d:%02d, 간격=%.1f초 "
                "(종목 %d개, %s) — 다음 장 시작 시 활성화",
                open_h, open_m, close_h, close_m, interval_seconds,
                self._stock_count, mc,
            )

        # 장 마감 후 작업 (평일)
        self._scheduler.add_job(
            func=self.post_market_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=post_h,
            minute=post_m,
            id="post_market_job",
            name="장 마감 후 작업",
            replace_existing=True,
        )
        logger.info("장 마감 후 작업 등록: 평일 %02d:%02d (%s)", post_h, post_m, mc)

        # 일일 요약 집계 작업 (평일)
        self._scheduler.add_job(
            func=self.summarize_daily_job,
            trigger="cron",
            day_of_week="mon-fri",
            hour=sum_h,
            minute=sum_m,
            id="summarize_daily_job",
            name="일일 요약 집계",
            replace_existing=True,
        )
        logger.info("일일 요약 집계 등록: 평일 %02d:%02d (%s)", sum_h, sum_m, mc)

        # 가격 스냅샷 7일 롤링 정리 (매일 04:30, 시장 무관)
        self._scheduler.add_job(
            func=self.cleanup_price_snapshots_job,
            trigger="cron",
            hour=4,
            minute=30,
            id="cleanup_price_snapshots",
            name="가격 스냅샷 7일 정리",
            replace_existing=True,
        )

        # API 할당량 시간대 전환 (Redis Rate Limiter). KRX는 항상 메인/스크리너 분할.
        # US는 SCREENING_US_ENABLED=true면 KRX 동형 분할, false면 메인 100%(워커 없음).
        # NOTE(후속): 시작 시점 즉시 catch-up(현재 구간 쿼터 1회 적용) 미구현 — KRX/US
        # 공통으로 첫 cron 트리거 전까지 default 쿼터 의존(재시작 직후 한정). 별도 개선.
        total = settings.rate_limit.per_second

        if self._market.is_overseas and settings.screening.us_enabled:
            # US 동적 스크리너 활성 → KRX 동형 분할(US 시각). 장전 스크리너 100% →
            # 장중 메인 80%/스크리너 20% → 마감후 메인 100%.
            def _us_quota_pre() -> None:
                _run_async(_update_quota({"main": 0, "screener": total}))

            def _us_quota_open() -> None:
                main_q = int(total * 0.8)
                _run_async(_update_quota({"main": main_q, "screener": total - main_q}))

            def _us_quota_post() -> None:
                _run_async(_update_quota({"main": total, "screener": 0}))

            self._scheduler.add_job(
                func=_us_quota_pre, trigger="cron", day_of_week="mon-fri",
                hour=pre_h, minute=pre_m, id="quota_us_pre",
                name="API 할당량: 스크리닝 전용(US)", replace_existing=True,
            )
            self._scheduler.add_job(
                func=_us_quota_open, trigger="cron", day_of_week="mon-fri",
                hour=open_h, minute=open_m, id="quota_us_open",
                name="API 할당량: 장중 배분(US)", replace_existing=True,
            )
            self._scheduler.add_job(
                func=_us_quota_post, trigger="cron", day_of_week="mon-fri",
                hour=post_h, minute=post_m, id="quota_us_post",
                name="API 할당량: 메인 전용(US)", replace_existing=True,
            )
            logger.info(
                "API 할당량(US 동적): %02d:%02d(스크리닝)/%02d:%02d(장중)/%02d:%02d(마감후)",
                pre_h, pre_m, open_h, open_m, post_h, post_m,
            )
        elif self._market.is_overseas:
            def _set_quota_us_main() -> None:
                """US 정적(watchlist): 스크리너 없음 → 메인 100%."""
                _run_async(_update_quota({"main": total, "screener": 0}))

            self._scheduler.add_job(
                func=_set_quota_us_main,
                trigger="cron",
                day_of_week="mon-fri",
                hour=pre_h,
                minute=pre_m,
                id="quota_us_main",
                name="API 할당량: 메인 전용(US)",
                replace_existing=True,
            )
            logger.info("API 할당량(US): 메인 100%% — 평일 %02d:%02d 설정", pre_h, pre_m)
        else:
            def _set_quota_pre_market() -> None:
                """장 시작 전: 스크리닝 100%."""
                _run_async(_update_quota({"main": 0, "screener": total}))

            def _set_quota_market_open() -> None:
                """장 시작: 메인 80% + 스크리닝 20%."""
                main_q = int(total * 0.8)
                _run_async(_update_quota({"main": main_q, "screener": total - main_q}))

            def _set_quota_post_market() -> None:
                """장 마감 후: 메인 100%."""
                _run_async(_update_quota({"main": total, "screener": 0}))

            self._scheduler.add_job(
                func=_set_quota_pre_market,
                trigger="cron",
                day_of_week="mon-fri",
                hour=QUOTA_PRE_MARKET_HOUR,
                minute=QUOTA_PRE_MARKET_MINUTE,
                id="quota_pre_market",
                name="API 할당량: 스크리닝 전용",
                replace_existing=True,
            )
            self._scheduler.add_job(
                func=_set_quota_market_open,
                trigger="cron",
                day_of_week="mon-fri",
                hour=QUOTA_MARKET_OPEN_HOUR,
                minute=QUOTA_MARKET_OPEN_MINUTE,
                id="quota_market_open",
                name="API 할당량: 장중 배분",
                replace_existing=True,
            )
            self._scheduler.add_job(
                func=_set_quota_post_market,
                trigger="cron",
                day_of_week="mon-fri",
                hour=QUOTA_POST_MARKET_HOUR,
                minute=QUOTA_POST_MARKET_MINUTE,
                id="quota_post_market",
                name="API 할당량: 메인 전용",
                replace_existing=True,
            )
            logger.info(
                "API 할당량 전환 등록: %02d:%02d(스크리닝), %02d:%02d(장중), %02d:%02d(마감후)",
                QUOTA_PRE_MARKET_HOUR, QUOTA_PRE_MARKET_MINUTE,
                QUOTA_MARKET_OPEN_HOUR, QUOTA_MARKET_OPEN_MINUTE,
                QUOTA_POST_MARKET_HOUR, QUOTA_POST_MARKET_MINUTE,
            )

            # 일일 헬스체크 (평일 12:30, 15:35) — KRX 전용(매매 0건 감지 Telegram 경고).
            self._scheduler.add_job(
                func=self.healthcheck_morning_job,
                trigger="cron",
                day_of_week="mon-fri",
                hour=HEALTHCHECK_MORNING_HOUR,
                minute=HEALTHCHECK_MORNING_MINUTE,
                id="healthcheck_morning",
                name="일일 헬스체크 (오전)",
                replace_existing=True,
            )
            self._scheduler.add_job(
                func=self.healthcheck_closing_job,
                trigger="cron",
                day_of_week="mon-fri",
                hour=HEALTHCHECK_CLOSING_HOUR,
                minute=HEALTHCHECK_CLOSING_MINUTE,
                id="healthcheck_closing",
                name="일일 헬스체크 (마감)",
                replace_existing=True,
            )
            logger.info(
                "일일 헬스체크 등록: 평일 %02d:%02d(오전), %02d:%02d(마감)",
                HEALTHCHECK_MORNING_HOUR, HEALTHCHECK_MORNING_MINUTE,
                HEALTHCHECK_CLOSING_HOUR, HEALTHCHECK_CLOSING_MINUTE,
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
