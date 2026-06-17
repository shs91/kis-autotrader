"""스케줄러 멀티마켓(P3c-6) — 시장별 타임존/시각/잡 구성 테스트."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from src.market.profile import KRX_PROFILE, US_PROFILE
from src.scheduler.jobs import TradingScheduler


def _cron_hm(job: object) -> tuple[int, int]:
    """cron 잡의 (hour, minute)를 추출한다."""
    fields = {f.name: str(f) for f in job.trigger.fields}  # type: ignore[attr-defined]
    return int(fields["hour"]), int(fields["minute"])


def test_scheduler_timezone_per_market() -> None:
    krx = TradingScheduler(market_profile=KRX_PROFILE)
    us = TradingScheduler(market_profile=US_PROFILE)
    assert krx.scheduler.timezone == ZoneInfo("Asia/Seoul")
    assert us.scheduler.timezone == ZoneInfo("America/New_York")


def test_krx_jobs_use_krx_hours() -> None:
    sched = TradingScheduler(market_profile=KRX_PROFILE)
    sched._register_jobs()
    assert _cron_hm(sched.scheduler.get_job("pre_market_job")) == (8, 30)
    assert _cron_hm(sched.scheduler.get_job("register_trading_job")) == (8, 55)
    assert _cron_hm(sched.scheduler.get_job("post_market_job")) == (15, 40)
    assert _cron_hm(sched.scheduler.get_job("summarize_daily_job")) == (16, 0)
    # KRX는 스크리너 할당량 전환 + 헬스체크 잡 보유
    assert sched.scheduler.get_job("quota_pre_market") is not None
    assert sched.scheduler.get_job("healthcheck_morning") is not None
    assert sched.scheduler.get_job("quota_us_main") is None


def test_us_jobs_use_et_hours_and_skip_screener_jobs() -> None:
    sched = TradingScheduler(market_profile=US_PROFILE)
    sched._register_jobs()
    assert _cron_hm(sched.scheduler.get_job("pre_market_job")) == (9, 0)
    assert _cron_hm(sched.scheduler.get_job("register_trading_job")) == (9, 25)
    assert _cron_hm(sched.scheduler.get_job("post_market_job")) == (16, 10)
    assert _cron_hm(sched.scheduler.get_job("summarize_daily_job")) == (16, 30)
    # US는 스크리너 없음 → 할당량 분할/헬스체크 잡 미등록, 메인 100% 단일 잡만
    assert sched.scheduler.get_job("quota_pre_market") is None
    assert sched.scheduler.get_job("healthcheck_morning") is None
    assert sched.scheduler.get_job("quota_us_main") is not None


def test_default_scheduler_is_krx() -> None:
    sched = TradingScheduler()
    assert sched._market.market_code == "KRX"
    assert sched.scheduler.timezone == ZoneInfo("Asia/Seoul")
