"""스케줄러 작업 등록 테스트."""

from __future__ import annotations

import pytest

from src.scheduler.jobs import TradingScheduler, _calculate_trading_interval


class TestCalculateTradingInterval:
    """시세 조회 간격 계산 테스트."""

    def test_ten_stocks(self) -> None:
        """10종목일 때 최소 3.4초 이상 간격이어야 한다."""
        interval = _calculate_trading_interval(10)
        assert interval >= 3.4

    def test_five_stocks(self) -> None:
        """5종목일 때 최소 1.7초 이상 간격이어야 한다."""
        interval = _calculate_trading_interval(5)
        assert interval >= 1.7

    def test_one_stock(self) -> None:
        """1종목일 때 최소 1.0초 이상 간격이어야 한다."""
        interval = _calculate_trading_interval(1)
        assert interval >= 1.0

    def test_zero_stocks(self) -> None:
        """0종목일 때 기본 1.0초 간격이어야 한다."""
        interval = _calculate_trading_interval(0)
        assert interval == 1.0

    def test_negative_stocks(self) -> None:
        """음수 종목일 때 기본 1.0초 간격이어야 한다."""
        interval = _calculate_trading_interval(-1)
        assert interval == 1.0


class TestTradingScheduler:
    """TradingScheduler 테스트."""

    def test_scheduler_creation(self) -> None:
        """스케줄러 인스턴스를 생성할 수 있다."""
        scheduler = TradingScheduler()
        assert scheduler.scheduler is not None

    def test_set_stock_count(self) -> None:
        """모니터링 종목 수를 설정할 수 있다."""
        scheduler = TradingScheduler()
        scheduler.set_stock_count(5)
        assert scheduler._stock_count == 5

    def test_start_and_shutdown(self) -> None:
        """스케줄러를 시작하고 종료할 수 있다."""
        scheduler = TradingScheduler()
        scheduler.set_stock_count(3)
        scheduler.start()

        # 작업이 등록되었는지 확인
        jobs = scheduler.scheduler.get_jobs()
        job_ids = [job.id for job in jobs]

        assert "pre_market_job" in job_ids
        # trading_job은 장중 시간에만 즉시 등록되고,
        # 장외 시간에는 register_trading_job이 대신 등록된다.
        assert "trading_job" in job_ids or "register_trading_job" in job_ids
        assert "post_market_job" in job_ids

        scheduler.shutdown()

    def test_jobs_have_correct_settings(self) -> None:
        """작업이 올바른 설정(misfire_grace_time, max_instances)으로 등록된다."""
        scheduler = TradingScheduler()
        scheduler.start()

        for job in scheduler.scheduler.get_jobs():
            assert job.misfire_grace_time == 60
            assert job.max_instances == 1

        scheduler.shutdown()

    def test_pre_market_job_runs(self) -> None:
        """장 시작 전 작업이 에러 없이 실행된다."""
        scheduler = TradingScheduler()
        # 직접 호출해도 에러가 나지 않아야 한다
        scheduler.pre_market_job()

    def test_trading_job_runs(self) -> None:
        """장중 매매 작업이 에러 없이 실행된다."""
        scheduler = TradingScheduler()
        scheduler.trading_job()

    def test_post_market_job_runs(self) -> None:
        """장 마감 후 작업이 에러 없이 실행된다."""
        scheduler = TradingScheduler()
        scheduler.post_market_job()

    def test_summarize_daily_job_registered(self) -> None:
        """일일 요약 집계 작업이 스케줄러에 등록된다."""
        scheduler = TradingScheduler()
        scheduler.start()

        job_ids = [job.id for job in scheduler.scheduler.get_jobs()]
        assert "summarize_daily_job" in job_ids

        scheduler.shutdown()

    def test_summarize_daily_job_runs(self) -> None:
        """일일 요약 집계 작업이 에러 없이 실행된다."""
        scheduler = TradingScheduler()
        # DB 없어도 예외가 전파되지 않아야 한다
        scheduler.summarize_daily_job()
