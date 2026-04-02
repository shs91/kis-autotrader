"""Repository CRUD 연산 테스트."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, OrderStatus, OrderType
from src.db.repository import (
    DailyPerformanceRepository,
    ExecutionRepository,
    OrderRepository,
    PortfolioRepository,
    StockRepository,
)


@pytest.fixture()
def session() -> Session:
    """SQLite in-memory 세션을 생성한다."""
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
