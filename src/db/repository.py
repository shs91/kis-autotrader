"""데이터 접근 레이어 (Repository 패턴)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import (
    DailyPerformance,
    EventLevel,
    EventLog,
    Execution,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Stock,
)
from src.utils.exceptions import DatabaseError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class StockRepository:
    """종목 마스터 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def get_by_code(self, code: str) -> Stock | None:
        """종목코드로 종목을 조회한다.

        Args:
            code: 종목코드

        Returns:
            종목 객체 또는 None
        """
        stmt = select(Stock).where(Stock.code == code)
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, code: str, name: str, market: str) -> Stock:
        """종목을 생성한다.

        Args:
            code: 종목코드
            name: 종목명
            market: 시장구분 (KOSPI/KOSDAQ)

        Returns:
            생성된 종목 객체

        Raises:
            DatabaseError: 종목 생성 실패 시
        """
        stock = Stock(code=code, name=name, market=market)
        self._session.add(stock)
        self._session.flush()
        logger.info("종목 생성: %s (%s)", name, code)
        return stock

    def list_all(self) -> list[Stock]:
        """전체 종목 목록을 조회한다.

        Returns:
            종목 리스트
        """
        stmt = select(Stock).order_by(Stock.code)
        return list(self._session.execute(stmt).scalars().all())


class OrderRepository:
    """주문 이력 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def create(
        self,
        stock_id: int,
        order_type: OrderType,
        quantity: int,
        price: float,
    ) -> Order:
        """주문을 생성한다.

        Args:
            stock_id: 종목 ID
            order_type: 주문 유형 (BUY/SELL)
            quantity: 주문 수량
            price: 주문 가격

        Returns:
            생성된 주문 객체
        """
        order = Order(
            stock_id=stock_id,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.PENDING,
        )
        self._session.add(order)
        self._session.flush()
        logger.info(
            "주문 생성: stock_id=%d, type=%s, qty=%d, price=%.0f",
            stock_id,
            order_type.value,
            quantity,
            price,
        )
        return order

    def update_status(
        self,
        order_id: int,
        status: OrderStatus,
        order_no: str | None = None,
    ) -> Order:
        """주문 상태를 갱신한다.

        Args:
            order_id: 주문 ID
            status: 변경할 주문 상태
            order_no: KIS 주문번호 (선택)

        Returns:
            갱신된 주문 객체

        Raises:
            DatabaseError: 주문을 찾을 수 없을 때
        """
        order = self.get_by_id(order_id)
        if order is None:
            raise DatabaseError(f"주문을 찾을 수 없습니다: order_id={order_id}")
        order.status = status
        if order_no is not None:
            order.order_no = order_no
        order.updated_at = datetime.utcnow()
        self._session.flush()
        logger.info("주문 상태 갱신: order_id=%d → %s", order_id, status.value)
        return order

    def get_by_id(self, order_id: int) -> Order | None:
        """주문 ID로 주문을 조회한다.

        Args:
            order_id: 주문 ID

        Returns:
            주문 객체 또는 None
        """
        stmt = select(Order).where(Order.id == order_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_today_orders(self) -> list[Order]:
        """당일 주문 목록을 조회한다.

        Returns:
            당일 주문 리스트
        """
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(Order)
            .where(Order.created_at >= today_start)
            .order_by(Order.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())


class ExecutionRepository:
    """체결 내역 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def create(
        self,
        order_id: int,
        price: float,
        quantity: int,
    ) -> Execution:
        """체결 내역을 생성한다.

        Args:
            order_id: 주문 ID
            price: 체결가
            quantity: 체결수량

        Returns:
            생성된 체결 내역 객체
        """
        execution = Execution(
            order_id=order_id,
            executed_price=price,
            executed_quantity=quantity,
        )
        self._session.add(execution)
        self._session.flush()
        logger.info(
            "체결 생성: order_id=%d, price=%.0f, qty=%d",
            order_id,
            price,
            quantity,
        )
        return execution

    def get_today_executions(self) -> list[Execution]:
        """당일 체결 내역을 조회한다.

        Returns:
            당일 체결 내역 리스트
        """
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(Execution)
            .where(Execution.executed_at >= today_start)
            .order_by(Execution.executed_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())


class PortfolioRepository:
    """보유 포지션 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def upsert(
        self,
        stock_id: int,
        quantity: int,
        avg_price: float,
        current_price: float,
    ) -> Portfolio:
        """보유 포지션을 생성하거나 갱신한다.

        Args:
            stock_id: 종목 ID
            quantity: 보유수량
            avg_price: 평균매수단가
            current_price: 현재가

        Returns:
            생성 또는 갱신된 포지션 객체
        """
        portfolio = self.get_by_stock(stock_id)
        if portfolio is None:
            portfolio = Portfolio(
                stock_id=stock_id,
                quantity=quantity,
                avg_price=avg_price,
                current_price=current_price,
            )
            self._session.add(portfolio)
        else:
            portfolio.quantity = quantity
            portfolio.avg_price = avg_price
            portfolio.current_price = current_price
            portfolio.updated_at = datetime.utcnow()
        self._session.flush()
        logger.info(
            "포지션 갱신: stock_id=%d, qty=%d, avg=%.0f",
            stock_id,
            quantity,
            avg_price,
        )
        return portfolio

    def get_by_stock(self, stock_id: int) -> Portfolio | None:
        """종목 ID로 포지션을 조회한다.

        Args:
            stock_id: 종목 ID

        Returns:
            포지션 객체 또는 None
        """
        stmt = select(Portfolio).where(Portfolio.stock_id == stock_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_all_positions(self) -> list[Portfolio]:
        """전체 보유 포지션을 조회한다.

        Returns:
            포지션 리스트
        """
        stmt = select(Portfolio).order_by(Portfolio.stock_id)
        return list(self._session.execute(stmt).scalars().all())

    def delete(self, stock_id: int) -> None:
        """포지션을 삭제한다.

        Args:
            stock_id: 종목 ID
        """
        portfolio = self.get_by_stock(stock_id)
        if portfolio is not None:
            self._session.delete(portfolio)
            self._session.flush()
            logger.info("포지션 삭제: stock_id=%d", stock_id)


class DailyPerformanceRepository:
    """일일 성과 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def create(
        self,
        perf_date: date,
        total_pl: float,
        rate: float,
        count: int,
        details: str | None = None,
    ) -> DailyPerformance:
        """일일 성과를 생성한다.

        Args:
            perf_date: 날짜
            total_pl: 총손익 금액
            rate: 수익률
            count: 체결건수
            details: 종목별 상세 내역 (JSON 문자열)

        Returns:
            생성된 일일 성과 객체
        """
        performance = DailyPerformance(
            date=perf_date,
            total_profit_loss=total_pl,
            profit_rate=rate,
            execution_count=count,
            details=details,
        )
        self._session.add(performance)
        self._session.flush()
        logger.info(
            "일일 성과 생성: date=%s, pl=%.0f, rate=%.2f%%",
            perf_date,
            total_pl,
            rate * 100,
        )
        return performance

    def get_by_date(self, perf_date: date) -> DailyPerformance | None:
        """날짜로 일일 성과를 조회한다.

        Args:
            perf_date: 조회 날짜

        Returns:
            일일 성과 객체 또는 None
        """
        stmt = select(DailyPerformance).where(DailyPerformance.date == perf_date)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_recent(self, days: int = 30) -> list[DailyPerformance]:
        """최근 N일간 일일 성과를 조회한다.

        Args:
            days: 조회 기간 (일수, 기본 30일)

        Returns:
            일일 성과 리스트 (최신순)
        """
        since = date.today() - timedelta(days=days)
        stmt = (
            select(DailyPerformance)
            .where(DailyPerformance.date >= since)
            .order_by(DailyPerformance.date.desc())
        )
        return list(self._session.execute(stmt).scalars().all())


class EventLogRepository:
    """이벤트 로그 데이터 접근 레이어."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def log(
        self,
        level: EventLevel,
        category: str,
        message: str,
        details: str | None = None,
    ) -> EventLog:
        """이벤트를 기록한다."""
        event = EventLog(
            level=level,
            category=category,
            message=message,
            details=details,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def info(self, category: str, message: str, details: str | None = None) -> EventLog:
        """INFO 이벤트를 기록한다."""
        return self.log(EventLevel.INFO, category, message, details)

    def warning(self, category: str, message: str, details: str | None = None) -> EventLog:
        """WARNING 이벤트를 기록한다."""
        return self.log(EventLevel.WARNING, category, message, details)

    def error(self, category: str, message: str, details: str | None = None) -> EventLog:
        """ERROR 이벤트를 기록한다."""
        return self.log(EventLevel.ERROR, category, message, details)


class WatchlistRepository:
    """관심종목 관리 레포지토리."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def get_codes(self) -> list[str]:
        """관심종목 코드 목록을 반환한다 (코드 정렬).

        Returns:
            관심종목 코드 리스트
        """
        stmt = (
            select(Stock.code)
            .where(Stock.is_watchlist.is_(True))
            .order_by(Stock.code)
        )
        return list(self._session.execute(stmt).scalars().all())

    def add(self, stock_code: str, stock_name: str = "") -> bool:
        """종목을 관심종목에 추가한다.

        종목이 stocks 테이블에 없으면 새로 생성한다.
        이미 관심종목이면 False를 반환한다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명 (없으면 코드로 대체)

        Returns:
            True: 추가됨, False: 이미 관심종목
        """
        stock = self._get_or_create(stock_code, stock_name)
        if stock.is_watchlist:
            return False
        stock.is_watchlist = True
        stock.updated_at = datetime.utcnow()
        self._session.flush()
        logger.info("관심종목 추가: %s (%s)", stock.name, stock.code)
        return True

    def remove(self, stock_code: str) -> bool:
        """종목을 관심종목에서 제거한다.

        종목 자체는 삭제하지 않고 is_watchlist만 False로 변경.

        Args:
            stock_code: 종목코드

        Returns:
            True: 제거됨, False: 관심종목이 아니었음
        """
        stock_repo = StockRepository(self._session)
        stock = stock_repo.get_by_code(stock_code)
        if stock is None or not stock.is_watchlist:
            return False
        stock.is_watchlist = False
        stock.updated_at = datetime.utcnow()
        self._session.flush()
        logger.info("관심종목 제거: %s (%s)", stock.name, stock.code)
        return True

    def is_watched(self, stock_code: str) -> bool:
        """관심종목 여부를 확인한다.

        Args:
            stock_code: 종목코드

        Returns:
            관심종목이면 True
        """
        stmt = select(Stock.is_watchlist).where(Stock.code == stock_code)
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is True

    def count(self) -> int:
        """관심종목 수를 반환한다."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(Stock)
            .where(Stock.is_watchlist.is_(True))
        )
        return self._session.execute(stmt).scalar_one()

    def _get_or_create(self, stock_code: str, stock_name: str = "") -> Stock:
        """종목을 조회하거나 없으면 생성한다."""
        stock_repo = StockRepository(self._session)
        stock = stock_repo.get_by_code(stock_code)
        if stock is None:
            stock = stock_repo.create(stock_code, stock_name or stock_code, "KOSPI")
        return stock
