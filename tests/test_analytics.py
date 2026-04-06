"""매매 분석 쿼리 테스트."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.analytics import (
    get_cumulative_pnl,
    get_daily_errors,
    get_daily_screening,
    get_daily_signals,
    get_daily_summary,
    get_daily_trades,
    get_optimal_risk_params,
    get_screening_conversion_rate,
    get_signal_accuracy,
    get_strategy_comparison,
    get_weekly_error_trend,
    get_weekly_risk_analysis,
    get_weekly_signal_performance,
    get_weekly_stock_frequency,
    get_weekly_trade_stats,
)
from src.db.models import (
    Base,
    SellReason,
    TradeType,
)
from src.db.repository import (
    ScreeningResultRepository,
    SignalRepository,
    SystemMetricRepository,
    TradeRepository,
)

# ── Fixture ────────────────────────────────────────────────


@pytest.fixture()
def session() -> Session:
    """SQLite in-memory 세션 (JSONB→JSON 호환)."""
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess  # type: ignore[misc]
    sess.close()
    engine.dispose()


# 2026-04-07 (화요일, ISO 주차 15)
DAY1 = datetime(2026, 4, 7, 9, 30)
DAY1_DATE = date(2026, 4, 7)
DAY2 = datetime(2026, 4, 8, 9, 30)
DAY2_DATE = date(2026, 4, 8)
DAY3 = datetime(2026, 4, 9, 10, 0)


@pytest.fixture()
def seeded_session(session: Session) -> Session:
    """분석용 테스트 데이터가 시드된 세션."""
    trade_repo = TradeRepository(session)
    signal_repo = SignalRepository(session)
    screening_repo = ScreeningResultRepository(session)
    metric_repo = SystemMetricRepository(session)

    # ── Day 1: 2026-04-07 ──

    # 매수 2건
    trade_repo.record_trade(
        stock_code="005930", stock_name="삼성전자",
        trade_type=TradeType.BUY, quantity=10, price=70000,
        total_amount=700000, traded_at=DAY1, cycle_number=1,
    )
    trade_repo.record_trade(
        stock_code="000660", stock_name="SK하이닉스",
        trade_type=TradeType.BUY, quantity=5, price=120000,
        total_amount=600000, traded_at=DAY1 + timedelta(minutes=10), cycle_number=1,
    )
    # 매도 2건
    trade_repo.record_trade(
        stock_code="005930", stock_name="삼성전자",
        trade_type=TradeType.SELL, quantity=10, price=72000,
        total_amount=720000, traded_at=DAY1 + timedelta(hours=4),
        cycle_number=1, sell_reason=SellReason.TAKE_PROFIT,
        signal_type="GOLDEN_CROSS",
        profit_loss_pct=2.86, profit_loss_amount=20000,
    )
    trade_repo.record_trade(
        stock_code="000660", stock_name="SK하이닉스",
        trade_type=TradeType.SELL, quantity=5, price=118000,
        total_amount=590000, traded_at=DAY1 + timedelta(hours=5),
        cycle_number=1, sell_reason=SellReason.STOP_LOSS,
        signal_type="DEAD_CROSS",
        profit_loss_pct=-1.67, profit_loss_amount=-10000,
    )

    # 시그널
    signal_repo.record_signal(
        stock_code="005930", stock_name="삼성전자",
        signal_type="GOLDEN_CROSS",
        detected_at=DAY1 + timedelta(minutes=-5),
        signal_value={"ma5": 70500, "ma20": 68000},
        confidence=0.85, action_taken=True,
    )
    signal_repo.record_signal(
        stock_code="000660", stock_name="SK하이닉스",
        signal_type="DEAD_CROSS",
        detected_at=DAY1 + timedelta(hours=3),
        confidence=0.6, action_taken=True,
    )
    signal_repo.record_signal(
        stock_code="035420", stock_name="NAVER",
        signal_type="GOLDEN_CROSS",
        detected_at=DAY1 + timedelta(hours=2),
        confidence=0.3, action_taken=False,
    )

    # 스크리닝
    screening_repo.record_screening(
        stock_code="005930", stock_name="삼성전자",
        screening_rank=1, volume=5000000, price_change_pct=3.5,
        screened_at=DAY1, cycle_number=1, converted_to_trade=True,
    )
    screening_repo.record_screening(
        stock_code="035420", stock_name="NAVER",
        screening_rank=2, volume=3000000, price_change_pct=2.0,
        screened_at=DAY1, cycle_number=1, converted_to_trade=False,
    )

    # 시스템 메트릭
    metric_repo.record_metric("CYCLE_START", {"cycle": 1}, DAY1)
    metric_repo.record_metric("ERROR", {"msg": "timeout"}, DAY1 + timedelta(hours=1))
    metric_repo.record_metric("CYCLE_END", {"cycle": 1}, DAY1 + timedelta(hours=6))

    # ── Day 2: 2026-04-08 ──

    trade_repo.record_trade(
        stock_code="005930", stock_name="삼성전자",
        trade_type=TradeType.BUY, quantity=15, price=71000,
        total_amount=1065000, traded_at=DAY2, cycle_number=2,
    )
    trade_repo.record_trade(
        stock_code="005930", stock_name="삼성전자",
        trade_type=TradeType.SELL, quantity=15, price=73000,
        total_amount=1095000, traded_at=DAY2 + timedelta(hours=3),
        cycle_number=2, sell_reason=SellReason.STRATEGY,
        signal_type="GOLDEN_CROSS",
        profit_loss_pct=2.82, profit_loss_amount=30000,
    )

    signal_repo.record_signal(
        stock_code="005930", stock_name="삼성전자",
        signal_type="GOLDEN_CROSS",
        detected_at=DAY2 + timedelta(minutes=-5),
        confidence=0.9, action_taken=True,
    )

    metric_repo.record_metric("ERROR", {"msg": "rate limit"}, DAY2 + timedelta(hours=2))
    metric_repo.record_metric("API_LIMIT", {"cycle": 2}, DAY2 + timedelta(hours=4))

    # 스크리닝 Day 2
    screening_repo.record_screening(
        stock_code="005930", stock_name="삼성전자",
        screening_rank=1, volume=6000000, price_change_pct=4.0,
        screened_at=DAY2, cycle_number=2, converted_to_trade=True,
    )

    session.flush()
    return session


# ── 일일 분석 테스트 ───────────────────────────────────────


class TestDailyAnalytics:
    """일일 분석 쿼리 테스트."""

    def test_get_daily_trades(self, seeded_session: Session) -> None:
        """당일 체결 내역을 반환한다."""
        result = get_daily_trades(seeded_session, DAY1_DATE)
        assert len(result) == 4
        buys = [t for t in result if t["trade_type"] == "BUY"]
        sells = [t for t in result if t["trade_type"] == "SELL"]
        assert len(buys) == 2
        assert len(sells) == 2
        assert result[0]["traded_at"] <= result[-1]["traded_at"]

    def test_get_daily_trades_empty(self, seeded_session: Session) -> None:
        """매매 없는 날은 빈 리스트를 반환한다."""
        result = get_daily_trades(seeded_session, date(2026, 1, 1))
        assert result == []

    def test_get_daily_signals(self, seeded_session: Session) -> None:
        """당일 시그널을 반환한다."""
        result = get_daily_signals(seeded_session, DAY1_DATE)
        assert len(result) == 3
        acted = [s for s in result if s["action_taken"]]
        assert len(acted) == 2

    def test_get_daily_screening(self, seeded_session: Session) -> None:
        """당일 스크리닝 결과와 전환율을 반환한다."""
        result = get_daily_screening(seeded_session, DAY1_DATE)
        assert result["total_screened"] == 2
        assert result["converted_count"] == 1
        assert result["conversion_rate"] == 50.0

    def test_get_daily_errors(self, seeded_session: Session) -> None:
        """당일 에러를 집계한다."""
        result = get_daily_errors(seeded_session, DAY1_DATE)
        assert result["total_errors"] == 1

    def test_get_daily_summary(self, seeded_session: Session) -> None:
        """당일 요약을 반환한다 (없으면 자동 생성)."""
        result = get_daily_summary(seeded_session, DAY1_DATE)
        assert result["report_date"] == "2026-04-07"
        assert result["total_buy_count"] == 2
        assert result["total_sell_count"] == 2
        assert result["total_profit_loss"] == 10000  # 20000 - 10000
        assert result["win_rate"] == 0.5

    def test_get_signal_accuracy(self, seeded_session: Session) -> None:
        """시그널 정확도를 계산한다."""
        result = get_signal_accuracy(seeded_session, DAY1_DATE)
        assert result["total_signals"] == 3
        assert result["acted_count"] == 2
        # 2개 acted 시그널 중 실제 체결 확인
        assert result["confirmed_count"] >= 1
        assert result["accuracy_rate"] > 0


# ── 주간 분석 테스트 ───────────────────────────────────────


class TestWeeklyAnalytics:
    """주간 분석 쿼리 테스트."""

    def test_get_weekly_trade_stats(self, seeded_session: Session) -> None:
        """주간 일별 매매 통계를 반환한다."""
        result = get_weekly_trade_stats(seeded_session, 2026, 15)
        assert result["total_trades"] == 6  # 4 + 2
        stats = result["daily_stats"]
        assert len(stats) == 2  # 2일
        assert stats[0]["date"] == "2026-04-07"
        assert stats[0]["buy_count"] == 2
        assert stats[0]["sell_count"] == 2

    def test_get_weekly_stock_frequency(self, seeded_session: Session) -> None:
        """주간 종목별 매매 빈도를 반환한다."""
        result = get_weekly_stock_frequency(seeded_session, 2026, 15)
        assert len(result) >= 1
        # 삼성전자가 가장 많이 매매됨
        assert result[0]["stock_code"] == "005930"
        assert result[0]["trade_count"] == 4  # buy2 + sell2

    def test_get_weekly_signal_performance(self, seeded_session: Session) -> None:
        """주간 시그널 유형별 성공률을 반환한다."""
        result = get_weekly_signal_performance(seeded_session, 2026, 15)
        assert len(result) >= 1
        golden = next(r for r in result if r["signal_type"] == "GOLDEN_CROSS")
        assert golden["total"] == 3  # Day1: 2, Day2: 1
        assert golden["acted"] >= 2

    def test_get_weekly_risk_analysis(self, seeded_session: Session) -> None:
        """주간 손절/익절 통계를 반환한다."""
        result = get_weekly_risk_analysis(seeded_session, 2026, 15)
        assert result["total_sells"] == 3
        assert "TAKE_PROFIT" in result["by_reason"]
        assert "STOP_LOSS" in result["by_reason"]
        assert result["by_reason"]["TAKE_PROFIT"]["count"] == 1
        assert result["by_reason"]["STOP_LOSS"]["count"] == 1

    def test_get_screening_conversion_rate(self, seeded_session: Session) -> None:
        """주간 스크리닝 전환율을 반환한다."""
        result = get_screening_conversion_rate(seeded_session, 2026, 15)
        assert result["total_screened"] == 3
        assert result["total_converted"] == 2
        assert len(result["daily"]) == 2

    def test_get_weekly_error_trend(self, seeded_session: Session) -> None:
        """주간 에러 추이를 반환한다."""
        result = get_weekly_error_trend(seeded_session, 2026, 15)
        assert result["total_errors"] == 2
        assert len(result["daily"]) == 2

    def test_weekly_empty(self, seeded_session: Session) -> None:
        """매매 없는 주차는 빈 결과를 반환한다."""
        result = get_weekly_trade_stats(seeded_session, 2026, 1)
        assert result["total_trades"] == 0
        assert result["daily_stats"] == []


# ── 중장기 분석 테스트 ─────────────────────────────────────


class TestLongTermAnalytics:
    """중장기 분석 쿼리 테스트."""

    def test_get_cumulative_pnl(self, seeded_session: Session) -> None:
        """누적 손익 곡선을 반환한다."""
        result = get_cumulative_pnl(
            seeded_session, date(2026, 4, 7), date(2026, 4, 8),
        )
        assert result["trading_days"] == 2
        curve = result["curve"]
        assert curve[0]["date"] == "2026-04-07"
        assert curve[0]["daily_pnl"] == 10000  # 20000 - 10000
        assert curve[1]["date"] == "2026-04-08"
        assert curve[1]["daily_pnl"] == 30000
        assert curve[1]["cumulative_pnl"] == 40000

    def test_get_cumulative_pnl_empty(self, seeded_session: Session) -> None:
        """매도 없는 기간은 빈 곡선을 반환한다."""
        result = get_cumulative_pnl(
            seeded_session, date(2026, 1, 1), date(2026, 1, 31),
        )
        assert result["trading_days"] == 0
        assert result["total_pnl"] == 0

    def test_get_strategy_comparison(self, seeded_session: Session) -> None:
        """시그널 유형별 성과를 비교한다."""
        result = get_strategy_comparison(
            seeded_session, date(2026, 4, 7), date(2026, 4, 8),
        )
        assert len(result) >= 1
        # GOLDEN_CROSS 시그널 확인
        golden = next((r for r in result if r["signal_type"] == "GOLDEN_CROSS"), None)
        assert golden is not None
        assert golden["signal_count"] >= 2

    def test_get_optimal_risk_params(self, seeded_session: Session) -> None:
        """리스크 파라미터 분석을 반환한다."""
        result = get_optimal_risk_params(seeded_session, lookback_days=30)
        assert result["total_sells"] == 3
        assert result["stop_loss"]["count"] == 1
        assert result["take_profit"]["count"] == 1
        assert result["strategy"]["count"] == 1
        assert "recommendation" in result
        assert result["recommendation"]["stop_loss_rate"] > 0
        assert result["recommendation"]["take_profit_rate"] > 0

    def test_get_optimal_risk_params_empty(self, session: Session) -> None:
        """매도 없을 때 기본값을 반환한다."""
        result = get_optimal_risk_params(session, lookback_days=30)
        assert result["total_sells"] == 0
        assert result["recommendation"]["stop_loss_rate"] == 0.03
        assert result["recommendation"]["take_profit_rate"] == 0.05
