"""SQLAlchemy ORM 모델 인스턴스 생성 테스트."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import (
    Base,
    DailyPerformance,
    Execution,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Stock,
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


class TestStockModel:
    """Stock 모델 테스트."""

    def test_create_stock(self, session: Session) -> None:
        """종목 인스턴스를 생성할 수 있다."""
        stock = Stock(code="005930", name="삼성전자", market="KOSPI")
        session.add(stock)
        session.commit()

        assert stock.id is not None
        assert stock.code == "005930"
        assert stock.name == "삼성전자"
        assert stock.market == "KOSPI"
        assert stock.created_at is not None

    def test_stock_repr(self, session: Session) -> None:
        """Stock의 repr이 올바르게 출력된다."""
        stock = Stock(code="005930", name="삼성전자", market="KOSPI")
        assert "005930" in repr(stock)
        assert "삼성전자" in repr(stock)

    def test_stock_unique_code(self, session: Session) -> None:
        """종목코드는 고유해야 한다."""
        stock1 = Stock(code="005930", name="삼성전자", market="KOSPI")
        stock2 = Stock(code="005930", name="삼성전자2", market="KOSPI")
        session.add(stock1)
        session.commit()
        session.add(stock2)
        with pytest.raises(Exception):  # IntegrityError
            session.commit()


class TestOrderModel:
    """Order 모델 테스트."""

    def test_create_order(self, session: Session) -> None:
        """주문 인스턴스를 생성할 수 있다."""
        stock = Stock(code="005930", name="삼성전자", market="KOSPI")
        session.add(stock)
        session.commit()

        order = Order(
            stock_id=stock.id,
            order_type=OrderType.BUY,
            quantity=10,
            price=70000.0,
            status=OrderStatus.PENDING,
        )
        session.add(order)
        session.commit()

        assert order.id is not None
        assert order.order_type == OrderType.BUY
        assert order.status == OrderStatus.PENDING
        assert order.quantity == 10
        assert order.price == 70000.0
        assert order.stock.code == "005930"

    def test_order_status_enum(self, session: Session) -> None:
        """주문 상태 Enum 값이 올바르다."""
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
        assert OrderStatus.FAILED.value == "FAILED"


class TestExecutionModel:
    """Execution 모델 테스트."""

    def test_create_execution(self, session: Session) -> None:
        """체결 내역 인스턴스를 생성할 수 있다."""
        stock = Stock(code="005930", name="삼성전자", market="KOSPI")
        session.add(stock)
        session.commit()

        order = Order(
            stock_id=stock.id,
            order_type=OrderType.BUY,
            quantity=10,
            price=70000.0,
            status=OrderStatus.FILLED,
        )
        session.add(order)
        session.commit()

        execution = Execution(
            order_id=order.id,
            executed_price=69500.0,
            executed_quantity=10,
        )
        session.add(execution)
        session.commit()

        assert execution.id is not None
        assert execution.executed_price == 69500.0
        assert execution.executed_quantity == 10
        assert execution.order.id == order.id

    def test_order_executions_relationship(self, session: Session) -> None:
        """주문과 체결의 one-to-many 관계가 동작한다."""
        stock = Stock(code="005930", name="삼성전자", market="KOSPI")
        session.add(stock)
        session.commit()

        order = Order(
            stock_id=stock.id,
            order_type=OrderType.BUY,
            quantity=20,
            price=70000.0,
            status=OrderStatus.PARTIALLY_FILLED,
        )
        session.add(order)
        session.commit()

        exec1 = Execution(order_id=order.id, executed_price=69500.0, executed_quantity=10)
        exec2 = Execution(order_id=order.id, executed_price=69800.0, executed_quantity=10)
        session.add_all([exec1, exec2])
        session.commit()

        session.refresh(order)
        assert len(order.executions) == 2


class TestPortfolioModel:
    """Portfolio 모델 테스트."""

    def test_create_portfolio(self, session: Session) -> None:
        """보유 포지션 인스턴스를 생성할 수 있다."""
        stock = Stock(code="005930", name="삼성전자", market="KOSPI")
        session.add(stock)
        session.commit()

        portfolio = Portfolio(
            stock_id=stock.id,
            quantity=100,
            avg_price=68000.0,
            current_price=70000.0,
        )
        session.add(portfolio)
        session.commit()

        assert portfolio.id is not None
        assert portfolio.quantity == 100
        assert portfolio.avg_price == 68000.0
        assert portfolio.stock.code == "005930"


class TestDailyPerformanceModel:
    """DailyPerformance 모델 테스트."""

    def test_create_daily_performance(self, session: Session) -> None:
        """일일 성과 인스턴스를 생성할 수 있다."""
        perf = DailyPerformance(
            date=date(2026, 3, 31),
            total_profit_loss=150000.0,
            profit_rate=0.025,
            execution_count=5,
            details='{"stocks": []}',
        )
        session.add(perf)
        session.commit()

        assert perf.id is not None
        assert perf.date == date(2026, 3, 31)
        assert perf.total_profit_loss == 150000.0
        assert perf.profit_rate == 0.025
        assert perf.execution_count == 5
        assert perf.details is not None

    def test_daily_performance_unique_date(self, session: Session) -> None:
        """날짜는 고유해야 한다."""
        perf1 = DailyPerformance(
            date=date(2026, 3, 31),
            total_profit_loss=100000.0,
            profit_rate=0.01,
            execution_count=3,
        )
        perf2 = DailyPerformance(
            date=date(2026, 3, 31),
            total_profit_loss=200000.0,
            profit_rate=0.02,
            execution_count=5,
        )
        session.add(perf1)
        session.commit()
        session.add(perf2)
        with pytest.raises(Exception):
            session.commit()
