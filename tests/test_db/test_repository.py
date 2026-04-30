"""Repository CRUD 연산 테스트."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import JSON, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, OrderStatus, OrderType, SellReason, TradeType
from src.db.models import ImplementationCategory
from src.db.repository import (
    DailyPerformanceRepository,
    DailySummaryRepository,
    ExecutionRepository,
    ImplementationLogRepository,
    OrderRepository,
    PortfolioRepository,
    ScreeningResultRepository,
    SignalRepository,
    StockRepository,
    SystemMetricRepository,
    TradeRepository,
)


@pytest.fixture()
def session() -> Session:
    """SQLite in-memory 세션을 생성한다.

    JSONB 컬럼을 SQLite에서도 동작하도록 JSON으로 렌더링한다.
    """
    from sqlalchemy.dialects.postgresql import JSONB

    from sqlalchemy import types as satypes

    # SQLite 컴파일러에 JSONB를 JSON으로 렌더링하는 방법 등록
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


class TestStockRepository:
    """StockRepository 테스트."""

    def test_create_and_get_by_code(self, session: Session) -> None:
        """종목 생성 후 코드로 조회할 수 있다."""
        repo = StockRepository(session)
        stock = repo.create("005930", "삼성전자", "KOSPI")
        session.commit()

        found = repo.get_by_code("005930")
        assert found is not None
        assert found.id == stock.id
        assert found.name == "삼성전자"

    def test_get_by_code_not_found(self, session: Session) -> None:
        """존재하지 않는 종목코드 조회 시 None을 반환한다."""
        repo = StockRepository(session)
        assert repo.get_by_code("999999") is None

    def test_list_all(self, session: Session) -> None:
        """전체 종목 목록을 조회한다."""
        repo = StockRepository(session)
        repo.create("005930", "삼성전자", "KOSPI")
        repo.create("000660", "SK하이닉스", "KOSPI")
        session.commit()

        stocks = repo.list_all()
        assert len(stocks) == 2
        # code 기준 정렬이므로 000660이 먼저
        assert stocks[0].code == "000660"


class TestOrderRepository:
    """OrderRepository 테스트."""

    def test_create_order(self, session: Session) -> None:
        """주문을 생성한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        order_repo = OrderRepository(session)
        order = order_repo.create(stock.id, OrderType.BUY, 10, 70000.0)
        session.commit()

        assert order.id is not None
        assert order.status == OrderStatus.PENDING

    def test_update_status(self, session: Session) -> None:
        """주문 상태를 갱신한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        order_repo = OrderRepository(session)
        order = order_repo.create(stock.id, OrderType.BUY, 10, 70000.0)
        session.flush()

        updated = order_repo.update_status(order.id, OrderStatus.SUBMITTED, "KIS12345")
        session.commit()

        assert updated.status == OrderStatus.SUBMITTED
        assert updated.order_no == "KIS12345"

    def test_update_status_not_found(self, session: Session) -> None:
        """존재하지 않는 주문 상태 갱신 시 DatabaseError를 발생시킨다."""
        from src.utils.exceptions import DatabaseError

        order_repo = OrderRepository(session)
        with pytest.raises(DatabaseError):
            order_repo.update_status(9999, OrderStatus.FILLED)

    def test_get_today_orders(self, session: Session) -> None:
        """당일 주문 목록을 조회한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        order_repo = OrderRepository(session)
        order_repo.create(stock.id, OrderType.BUY, 10, 70000.0)
        order_repo.create(stock.id, OrderType.SELL, 5, 72000.0)
        session.commit()

        today_orders = order_repo.get_today_orders()
        assert len(today_orders) == 2


class TestExecutionRepository:
    """ExecutionRepository 테스트."""

    def test_create_execution(self, session: Session) -> None:
        """체결 내역을 생성한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        order_repo = OrderRepository(session)
        order = order_repo.create(stock.id, OrderType.BUY, 10, 70000.0)
        session.flush()

        exec_repo = ExecutionRepository(session)
        execution = exec_repo.create(order.id, 69500.0, 10)
        session.commit()

        assert execution.id is not None
        assert execution.executed_price == 69500.0
        assert execution.executed_quantity == 10

    def test_get_today_executions(self, session: Session) -> None:
        """당일 체결 내역을 조회한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        order_repo = OrderRepository(session)
        order = order_repo.create(stock.id, OrderType.BUY, 10, 70000.0)
        session.flush()

        exec_repo = ExecutionRepository(session)
        exec_repo.create(order.id, 69500.0, 5)
        exec_repo.create(order.id, 69800.0, 5)
        session.commit()

        today_execs = exec_repo.get_today_executions()
        assert len(today_execs) == 2


class TestPortfolioRepository:
    """PortfolioRepository 테스트."""

    def test_upsert_create(self, session: Session) -> None:
        """포지션이 없으면 새로 생성한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        port_repo = PortfolioRepository(session)
        portfolio = port_repo.upsert(stock.id, 100, 68000.0, 70000.0)
        session.commit()

        assert portfolio.id is not None
        assert portfolio.quantity == 100

    def test_upsert_update(self, session: Session) -> None:
        """포지션이 있으면 갱신한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        port_repo = PortfolioRepository(session)
        port_repo.upsert(stock.id, 100, 68000.0, 70000.0)
        session.flush()

        updated = port_repo.upsert(stock.id, 200, 69000.0, 71000.0)
        session.commit()

        assert updated.quantity == 200
        assert updated.avg_price == 69000.0

    def test_get_all_positions(self, session: Session) -> None:
        """전체 보유 포지션을 조회한다."""
        stock_repo = StockRepository(session)
        s1 = stock_repo.create("005930", "삼성전자", "KOSPI")
        s2 = stock_repo.create("000660", "SK하이닉스", "KOSPI")
        session.flush()

        port_repo = PortfolioRepository(session)
        port_repo.upsert(s1.id, 100, 68000.0, 70000.0)
        port_repo.upsert(s2.id, 50, 120000.0, 125000.0)
        session.commit()

        positions = port_repo.get_all_positions()
        assert len(positions) == 2

    def test_delete(self, session: Session) -> None:
        """포지션을 삭제한다."""
        stock_repo = StockRepository(session)
        stock = stock_repo.create("005930", "삼성전자", "KOSPI")
        session.flush()

        port_repo = PortfolioRepository(session)
        port_repo.upsert(stock.id, 100, 68000.0, 70000.0)
        session.flush()

        port_repo.delete(stock.id)
        session.commit()

        assert port_repo.get_by_stock(stock.id) is None


class TestDailyPerformanceRepository:
    """DailyPerformanceRepository 테스트."""

    def test_create_and_get_by_date(self, session: Session) -> None:
        """일일 성과를 생성하고 날짜로 조회한다."""
        repo = DailyPerformanceRepository(session)
        perf = repo.create(
            perf_date=date(2026, 3, 31),
            total_pl=150000.0,
            rate=0.025,
            count=5,
            details='{"detail": "test"}',
        )
        session.commit()

        found = repo.get_by_date(date(2026, 3, 31))
        assert found is not None
        assert found.total_profit_loss == 150000.0
        assert found.profit_rate == 0.025

    def test_get_by_date_not_found(self, session: Session) -> None:
        """존재하지 않는 날짜 조회 시 None을 반환한다."""
        repo = DailyPerformanceRepository(session)
        assert repo.get_by_date(date(2020, 1, 1)) is None

    def test_get_recent(self, session: Session) -> None:
        """최근 N일간 성과를 조회한다."""
        repo = DailyPerformanceRepository(session)
        today = date.today()
        for i in range(5):
            repo.create(
                perf_date=today - timedelta(days=i),
                total_pl=10000.0 * (i + 1),
                rate=0.01 * (i + 1),
                count=i + 1,
            )
        session.commit()

        recent = repo.get_recent(days=3)
        assert len(recent) <= 4  # 오늘 포함 최대 4일
        # 최신순 정렬 확인
        if len(recent) >= 2:
            assert recent[0].date >= recent[1].date


class TestTradeRepository:
    """TradeRepository 테스트."""

    def test_record_trade_buy(self, session: Session) -> None:
        """매수 체결을 기록한다."""
        repo = TradeRepository(session)
        trade = repo.record_trade(
            stock_code="005930",
            stock_name="삼성전자",
            trade_type=TradeType.BUY,
            quantity=10,
            price=70000,
            total_amount=700000,
            traded_at=datetime(2026, 4, 7, 9, 30, 0),
            cycle_number=1,
        )
        session.commit()

        assert trade.id is not None
        assert trade.trade_type == TradeType.BUY
        assert trade.total_amount == 700000
        assert trade.sell_reason is None

    def test_record_trade_sell(self, session: Session) -> None:
        """매도 체결을 기록한다 (손익 포함)."""
        repo = TradeRepository(session)
        trade = repo.record_trade(
            stock_code="005930",
            stock_name="삼성전자",
            trade_type=TradeType.SELL,
            quantity=10,
            price=72000,
            total_amount=720000,
            traded_at=datetime(2026, 4, 7, 14, 0, 0),
            cycle_number=1,
            sell_reason=SellReason.TAKE_PROFIT,
            signal_type="GOLDEN_CROSS",
            profit_loss_pct=2.86,
            profit_loss_amount=20000,
        )
        session.commit()

        assert trade.sell_reason == SellReason.TAKE_PROFIT
        assert trade.profit_loss_pct == 2.86
        assert trade.profit_loss_amount == 20000

    def test_get_trades_by_date(self, session: Session) -> None:
        """날짜별 체결 내역을 조회한다."""
        repo = TradeRepository(session)
        repo.record_trade(
            stock_code="005930", stock_name="삼성전자",
            trade_type=TradeType.BUY, quantity=10, price=70000,
            total_amount=700000, traded_at=datetime(2026, 4, 7, 9, 30),
        )
        repo.record_trade(
            stock_code="000660", stock_name="SK하이닉스",
            trade_type=TradeType.BUY, quantity=5, price=120000,
            total_amount=600000, traded_at=datetime(2026, 4, 7, 10, 0),
        )
        # 다른 날짜
        repo.record_trade(
            stock_code="005930", stock_name="삼성전자",
            trade_type=TradeType.SELL, quantity=10, price=72000,
            total_amount=720000, traded_at=datetime(2026, 4, 8, 9, 30),
        )
        session.commit()

        trades = repo.get_trades_by_date(date(2026, 4, 7))
        assert len(trades) == 2

    def test_get_trades_by_stock(self, session: Session) -> None:
        """종목별 체결 내역을 조회한다."""
        repo = TradeRepository(session)
        repo.record_trade(
            stock_code="005930", stock_name="삼성전자",
            trade_type=TradeType.BUY, quantity=10, price=70000,
            total_amount=700000, traded_at=datetime(2026, 4, 7, 9, 30),
        )
        repo.record_trade(
            stock_code="005930", stock_name="삼성전자",
            trade_type=TradeType.SELL, quantity=10, price=72000,
            total_amount=720000, traded_at=datetime(2026, 4, 7, 14, 0),
        )
        session.commit()

        trades = repo.get_trades_by_stock("005930")
        assert len(trades) == 2
        # 최신순
        assert trades[0].traded_at > trades[1].traded_at


class TestSignalRepository:
    """SignalRepository 테스트."""

    def test_record_signal(self, session: Session) -> None:
        """시그널을 기록한다."""
        repo = SignalRepository(session)
        signal = repo.record_signal(
            stock_code="005930",
            stock_name="삼성전자",
            signal_type="GOLDEN_CROSS",
            detected_at=datetime(2026, 4, 7, 9, 15),
            signal_value={"ma5": 70000, "ma20": 68000},
            confidence=0.85,
            action_taken=True,
        )
        session.commit()

        assert signal.id is not None
        assert signal.signal_type == "GOLDEN_CROSS"
        assert signal.confidence == 0.85
        assert signal.action_taken is True

    def test_get_signals_by_date(self, session: Session) -> None:
        """날짜별 시그널을 조회한다."""
        repo = SignalRepository(session)
        repo.record_signal(
            stock_code="005930", stock_name="삼성전자",
            signal_type="GOLDEN_CROSS",
            detected_at=datetime(2026, 4, 7, 9, 15),
        )
        repo.record_signal(
            stock_code="000660", stock_name="SK하이닉스",
            signal_type="RSI_OVERSOLD",
            detected_at=datetime(2026, 4, 7, 10, 0),
        )
        session.commit()

        signals = repo.get_signals_by_date(date(2026, 4, 7))
        assert len(signals) == 2


class TestScreeningResultRepository:
    """ScreeningResultRepository 테스트."""

    def test_record_screening(self, session: Session) -> None:
        """스크리닝 결과를 기록한다."""
        repo = ScreeningResultRepository(session)
        result = repo.record_screening(
            stock_code="005930",
            stock_name="삼성전자",
            screening_rank=1,
            volume=5000000,
            price_change_pct=3.5,
            screened_at=datetime(2026, 4, 7, 9, 0),
            cycle_number=1,
        )
        session.commit()

        assert result.id is not None
        assert result.screening_rank == 1
        assert result.volume == 5000000
        assert result.converted_to_trade is False

    def test_get_by_cycle(self, session: Session) -> None:
        """사이클별 스크리닝 결과를 조회한다."""
        repo = ScreeningResultRepository(session)
        repo.record_screening(
            stock_code="005930", stock_name="삼성전자",
            screening_rank=1, volume=5000000, price_change_pct=3.5,
            screened_at=datetime(2026, 4, 7, 9, 0), cycle_number=1,
        )
        repo.record_screening(
            stock_code="000660", stock_name="SK하이닉스",
            screening_rank=2, volume=3000000, price_change_pct=2.1,
            screened_at=datetime(2026, 4, 7, 9, 0), cycle_number=1,
        )
        repo.record_screening(
            stock_code="035420", stock_name="NAVER",
            screening_rank=1, volume=1000000, price_change_pct=1.0,
            screened_at=datetime(2026, 4, 7, 10, 0), cycle_number=2,
        )
        session.commit()

        cycle1 = repo.get_by_cycle(1)
        assert len(cycle1) == 2
        assert cycle1[0].screening_rank == 1  # rank 순

        cycle2 = repo.get_by_cycle(2)
        assert len(cycle2) == 1

    def test_get_by_date_kst_timezone(self, session: Session) -> None:
        """KST 기준 날짜로 스크리닝 결과를 조회한다."""
        from zoneinfo import ZoneInfo
        kst = ZoneInfo("Asia/Seoul")
        repo = ScreeningResultRepository(session)
        # KST 04-30 09:00 = UTC 04-30 00:00
        repo.record_screening(
            stock_code="005930", stock_name="삼성전자",
            screening_rank=1, volume=5000000, price_change_pct=3.5,
            screened_at=datetime(2026, 4, 30, 9, 0, tzinfo=kst),
            cycle_number=1,
        )
        # KST 04-30 15:00 = UTC 04-30 06:00
        repo.record_screening(
            stock_code="000660", stock_name="SK하이닉스",
            screening_rank=2, volume=3000000, price_change_pct=2.1,
            screened_at=datetime(2026, 4, 30, 15, 0, tzinfo=kst),
            cycle_number=2,
        )
        session.commit()

        results = repo.get_by_date(date(2026, 4, 30))
        assert len(results) == 2
        assert results[0].screening_rank == 1

    def test_get_by_date_excludes_other_dates(self, session: Session) -> None:
        """다른 날짜의 스크리닝 결과는 제외한다."""
        from zoneinfo import ZoneInfo
        kst = ZoneInfo("Asia/Seoul")
        repo = ScreeningResultRepository(session)
        # KST 04-29 장중 데이터
        repo.record_screening(
            stock_code="005930", stock_name="삼성전자",
            screening_rank=1, volume=5000000, price_change_pct=3.5,
            screened_at=datetime(2026, 4, 29, 10, 0, tzinfo=kst),
            cycle_number=1,
        )
        session.commit()

        results = repo.get_by_date(date(2026, 4, 30))
        assert len(results) == 0


class TestSystemMetricRepository:
    """SystemMetricRepository 테스트."""

    def test_record_metric(self, session: Session) -> None:
        """시스템 메트릭을 기록한다."""
        repo = SystemMetricRepository(session)
        metric = repo.record_metric(
            metric_type="CYCLE_START",
            detail={"cycle": 1, "stocks": ["005930", "000660"]},
            recorded_at=datetime(2026, 4, 7, 9, 0),
        )
        session.commit()

        assert metric.id is not None
        assert metric.metric_type == "CYCLE_START"

    def test_get_by_type(self, session: Session) -> None:
        """메트릭 유형으로 조회한다."""
        repo = SystemMetricRepository(session)
        repo.record_metric("CYCLE_START", recorded_at=datetime(2026, 4, 7, 9, 0))
        repo.record_metric("CYCLE_END", recorded_at=datetime(2026, 4, 7, 9, 5))
        repo.record_metric("ERROR", detail={"msg": "timeout"}, recorded_at=datetime(2026, 4, 7, 9, 3))
        session.commit()

        starts = repo.get_by_type("CYCLE_START")
        assert len(starts) == 1
        errors = repo.get_by_type("ERROR")
        assert len(errors) == 1

    def test_get_by_type_with_since(self, session: Session) -> None:
        """since 필터로 메트릭을 조회한다."""
        repo = SystemMetricRepository(session)
        repo.record_metric("ERROR", recorded_at=datetime(2026, 4, 6, 9, 0))
        repo.record_metric("ERROR", recorded_at=datetime(2026, 4, 7, 9, 0))
        session.commit()

        errors = repo.get_by_type("ERROR", since=datetime(2026, 4, 7, 0, 0))
        assert len(errors) == 1


class TestDailySummaryRepository:
    """DailySummaryRepository 테스트."""

    def test_upsert_daily_summary_empty(self, session: Session) -> None:
        """매매 없는 날 요약을 생성한다."""
        repo = DailySummaryRepository(session)
        summary = repo.upsert_daily_summary(date(2026, 4, 7))
        session.commit()

        assert summary.id is not None
        assert summary.total_buy_count == 0
        assert summary.total_sell_count == 0
        assert summary.total_profit_loss == 0

    def test_upsert_daily_summary_with_trades(self, session: Session) -> None:
        """매매 데이터가 있을 때 정확히 집계한다."""
        trade_repo = TradeRepository(session)
        trade_repo.record_trade(
            stock_code="005930", stock_name="삼성전자",
            trade_type=TradeType.BUY, quantity=10, price=70000,
            total_amount=700000, traded_at=datetime(2026, 4, 7, 9, 30),
            cycle_number=1,
        )
        trade_repo.record_trade(
            stock_code="005930", stock_name="삼성전자",
            trade_type=TradeType.SELL, quantity=10, price=72000,
            total_amount=720000, traded_at=datetime(2026, 4, 7, 14, 0),
            cycle_number=1, sell_reason=SellReason.TAKE_PROFIT,
            profit_loss_amount=20000, profit_loss_pct=2.86,
        )
        trade_repo.record_trade(
            stock_code="000660", stock_name="SK하이닉스",
            trade_type=TradeType.BUY, quantity=5, price=120000,
            total_amount=600000, traded_at=datetime(2026, 4, 7, 10, 0),
            cycle_number=1,
        )
        trade_repo.record_trade(
            stock_code="000660", stock_name="SK하이닉스",
            trade_type=TradeType.SELL, quantity=5, price=118000,
            total_amount=590000, traded_at=datetime(2026, 4, 7, 14, 30),
            cycle_number=1, sell_reason=SellReason.STOP_LOSS,
            profit_loss_amount=-10000, profit_loss_pct=-1.67,
        )
        session.flush()

        repo = DailySummaryRepository(session)
        summary = repo.upsert_daily_summary(date(2026, 4, 7))
        session.commit()

        assert summary.total_buy_count == 2
        assert summary.total_sell_count == 2
        assert summary.total_profit_loss == 10000  # 20000 + (-10000)
        assert summary.win_rate == 0.5  # 1 win / 2 sells
        assert summary.take_profit_count == 1
        assert summary.stop_loss_count == 1

    def test_upsert_updates_existing(self, session: Session) -> None:
        """기존 요약이 있으면 갱신한다."""
        repo = DailySummaryRepository(session)
        summary1 = repo.upsert_daily_summary(date(2026, 4, 7))
        session.flush()
        first_id = summary1.id

        # 매매 추가 후 재집계
        trade_repo = TradeRepository(session)
        trade_repo.record_trade(
            stock_code="005930", stock_name="삼성전자",
            trade_type=TradeType.BUY, quantity=10, price=70000,
            total_amount=700000, traded_at=datetime(2026, 4, 7, 9, 30),
        )
        session.flush()

        summary2 = repo.upsert_daily_summary(date(2026, 4, 7))
        session.commit()

        assert summary2.id == first_id  # 같은 레코드
        assert summary2.total_buy_count == 1

    def test_get_by_date(self, session: Session) -> None:
        """날짜로 요약을 조회한다."""
        repo = DailySummaryRepository(session)
        repo.upsert_daily_summary(date(2026, 4, 7))
        session.commit()

        found = repo.get_by_date(date(2026, 4, 7))
        assert found is not None
        assert found.report_date == date(2026, 4, 7)

        not_found = repo.get_by_date(date(2026, 4, 8))
        assert not_found is None


class TestImplementationLogRepository:
    """ImplementationLogRepository 테스트."""

    def test_create(self, session: Session) -> None:
        """구현 이력을 생성한다."""
        repo = ImplementationLogRepository(session)
        log = repo.create(
            title="버그 수정 — 종목명 누락",
            category=ImplementationCategory.BUG_FIX,
            implemented_at=datetime(2026, 4, 14, 21, 0),
            proposal_path="docs/proposals/2026-04-14_stock-name-fix.md",
            changed_files={"src/engine.py": "fallback 로직 추가"},
            verification={"summary": "pytest ✅ | mypy ✅ | ruff ✅"},
        )
        session.commit()

        assert log.id is not None
        assert log.title == "버그 수정 — 종목명 누락"
        assert log.category == ImplementationCategory.BUG_FIX
        assert log.changed_files is not None
        assert "src/engine.py" in log.changed_files

    def test_list_recent(self, session: Session) -> None:
        """최근 이력을 조회한다."""
        repo = ImplementationLogRepository(session)
        for i in range(7):
            repo.create(
                title=f"변경 #{i}",
                category=ImplementationCategory.ENHANCEMENT,
                implemented_at=datetime(2026, 4, 1 + i, 21, 0),
            )
        session.commit()

        recent = repo.list_recent(limit=5)
        assert len(recent) == 5
        assert recent[0].title == "변경 #6"  # 최신순

    def test_list_by_category(self, session: Session) -> None:
        """카테고리별 이력을 조회한다."""
        repo = ImplementationLogRepository(session)
        repo.create(
            title="버그 A",
            category=ImplementationCategory.BUG_FIX,
            implemented_at=datetime(2026, 4, 1, 21, 0),
        )
        repo.create(
            title="리팩토링 B",
            category=ImplementationCategory.REFACTOR,
            implemented_at=datetime(2026, 4, 2, 21, 0),
        )
        repo.create(
            title="버그 C",
            category=ImplementationCategory.BUG_FIX,
            implemented_at=datetime(2026, 4, 3, 21, 0),
        )
        session.commit()

        bugs = repo.list_by_category(ImplementationCategory.BUG_FIX)
        assert len(bugs) == 2
        assert all(b.category == ImplementationCategory.BUG_FIX for b in bugs)

    def test_count(self, session: Session) -> None:
        """전체 건수를 반환한다."""
        repo = ImplementationLogRepository(session)
        assert repo.count() == 0

        repo.create(
            title="변경 1",
            category=ImplementationCategory.CONFIG,
            implemented_at=datetime(2026, 4, 1, 21, 0),
        )
        session.commit()
        assert repo.count() == 1
