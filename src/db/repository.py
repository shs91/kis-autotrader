"""데이터 접근 레이어 (Repository 패턴)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from src.db.models import (
    BuyReason,
    DailyPerformance,
    DailySummary,
    EventLevel,
    EventLog,
    Execution,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    ScreeningResult,
    SellReason,
    Signal,
    Stock,
    SystemMetric,
    Trade,
    TradeType,
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

    def update_name(self, code: str, name: str) -> bool:
        """종목명을 업데이트한다. 이름이 코드와 동일할 때 실제 이름으로 교체용.

        Args:
            code: 종목코드
            name: 종목명

        Returns:
            True: 업데이트됨, False: 종목 없음 또는 이미 정상
        """
        stock = self.get_by_code(code)
        if stock is None or stock.name == name:
            return False
        old_name = stock.name
        stock.name = name
        self._session.flush()
        logger.info("종목명 업데이트: %s → %s (%s)", old_name, name, code)
        return True

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


class TradeRepository:
    """매매 체결 내역 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def record_trade(
        self,
        stock_code: str,
        stock_name: str,
        trade_type: TradeType,
        quantity: int,
        price: int,
        total_amount: int,
        traded_at: datetime,
        cycle_number: int = 0,
        buy_reason: BuyReason | None = None,
        sell_reason: SellReason | None = None,
        signal_type: str | None = None,
        profit_loss_pct: float | None = None,
        profit_loss_amount: int | None = None,
    ) -> Trade:
        """매매 체결 내역을 기록한다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            trade_type: 매매 유형 (BUY/SELL)
            quantity: 수량
            price: 체결가
            total_amount: 체결금액
            traded_at: 체결 시각
            cycle_number: 매매 사이클 번호
            buy_reason: 매수 사유 (매수 시)
            sell_reason: 매도 사유 (매도 시)
            signal_type: 시그널 유형
            profit_loss_pct: 수익률 (매도 시)
            profit_loss_amount: 손익금액 (매도 시)

        Returns:
            생성된 Trade 객체
        """
        trade = Trade(
            stock_code=stock_code,
            stock_name=stock_name,
            trade_type=trade_type,
            quantity=quantity,
            price=price,
            total_amount=total_amount,
            traded_at=traded_at,
            cycle_number=cycle_number,
            buy_reason=buy_reason,
            sell_reason=sell_reason,
            signal_type=signal_type,
            profit_loss_pct=profit_loss_pct,
            profit_loss_amount=profit_loss_amount,
        )
        self._session.add(trade)
        self._session.flush()
        logger.info(
            "매매 기록: %s %s %s qty=%d @%d",
            stock_code,
            stock_name,
            trade_type.value,
            quantity,
            price,
        )
        return trade

    def get_trades_by_date(self, target_date: date) -> list[Trade]:
        """특정 날짜의 체결 내역을 조회한다.

        Args:
            target_date: 조회 날짜

        Returns:
            체결 내역 리스트
        """
        start = datetime(target_date.year, target_date.month, target_date.day)
        end = start + timedelta(days=1)
        stmt = (
            select(Trade)
            .where(Trade.traded_at >= start, Trade.traded_at < end)
            .order_by(Trade.traded_at)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_trades_by_stock(self, stock_code: str) -> list[Trade]:
        """종목별 체결 내역을 조회한다.

        Args:
            stock_code: 종목코드

        Returns:
            체결 내역 리스트
        """
        stmt = (
            select(Trade)
            .where(Trade.stock_code == stock_code)
            .order_by(Trade.traded_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())


class SignalRepository:
    """전략 시그널 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def record_signal(
        self,
        stock_code: str,
        stock_name: str,
        signal_type: str,
        detected_at: datetime,
        signal_value: dict | None = None,
        confidence: float = 0.0,
        action_taken: bool = False,
    ) -> Signal:
        """시그널을 기록한다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            signal_type: 시그널 유형 (예: GOLDEN_CROSS)
            detected_at: 감지 시각
            signal_value: 시그널 상세 값 (JSON)
            confidence: 신뢰도
            action_taken: 실제 매매 실행 여부

        Returns:
            생성된 Signal 객체
        """
        signal = Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            signal_type=signal_type,
            detected_at=detected_at,
            signal_value=signal_value,
            confidence=confidence,
            action_taken=action_taken,
        )
        self._session.add(signal)
        self._session.flush()
        logger.info(
            "시그널 기록: %s %s %s (confidence=%.2f, acted=%s)",
            stock_code,
            stock_name,
            signal_type,
            confidence,
            action_taken,
        )
        return signal

    def get_signals_by_date(self, target_date: date) -> list[Signal]:
        """특정 날짜의 시그널을 조회한다.

        Args:
            target_date: 조회 날짜

        Returns:
            시그널 리스트
        """
        start = datetime(target_date.year, target_date.month, target_date.day)
        end = start + timedelta(days=1)
        stmt = (
            select(Signal)
            .where(Signal.detected_at >= start, Signal.detected_at < end)
            .order_by(Signal.detected_at)
        )
        return list(self._session.execute(stmt).scalars().all())


class ScreeningResultRepository:
    """스크리닝 결과 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def record_screening(
        self,
        stock_code: str,
        stock_name: str,
        screening_rank: int,
        volume: int,
        price_change_pct: float,
        screened_at: datetime,
        cycle_number: int = 0,
        converted_to_trade: bool = False,
    ) -> ScreeningResult:
        """스크리닝 결과를 기록한다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            screening_rank: 순위
            volume: 거래량
            price_change_pct: 등락률
            screened_at: 스크리닝 시각
            cycle_number: 사이클 번호
            converted_to_trade: 매매 전환 여부

        Returns:
            생성된 ScreeningResult 객체
        """
        result = ScreeningResult(
            stock_code=stock_code,
            stock_name=stock_name,
            screening_rank=screening_rank,
            volume=volume,
            price_change_pct=price_change_pct,
            screened_at=screened_at,
            cycle_number=cycle_number,
            converted_to_trade=converted_to_trade,
        )
        self._session.add(result)
        self._session.flush()
        logger.info(
            "스크리닝 기록: %s %s rank=%d volume=%d",
            stock_code,
            stock_name,
            screening_rank,
            volume,
        )
        return result

    def get_by_cycle(self, cycle_number: int) -> list[ScreeningResult]:
        """사이클 번호로 스크리닝 결과를 조회한다.

        Args:
            cycle_number: 사이클 번호

        Returns:
            스크리닝 결과 리스트
        """
        stmt = (
            select(ScreeningResult)
            .where(ScreeningResult.cycle_number == cycle_number)
            .order_by(ScreeningResult.screening_rank)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_by_date(self, target_date: date) -> list[ScreeningResult]:
        """특정 날짜의 스크리닝 결과를 조회한다.

        Args:
            target_date: 조회 날짜

        Returns:
            스크리닝 결과 리스트
        """
        start = datetime.combine(target_date, datetime.min.time())
        end = start + timedelta(days=1)
        stmt = (
            select(ScreeningResult)
            .where(
                ScreeningResult.screened_at >= start,
                ScreeningResult.screened_at < end,
            )
            .order_by(ScreeningResult.screening_rank)
        )
        return list(self._session.execute(stmt).scalars().all())


class SystemMetricRepository:
    """시스템 메트릭 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def record_metric(
        self,
        metric_type: str,
        detail: dict | None = None,
        recorded_at: datetime | None = None,
    ) -> SystemMetric:
        """시스템 메트릭을 기록한다.

        Args:
            metric_type: 메트릭 유형 (CYCLE_START, CYCLE_END, API_LIMIT, ERROR, RESTART)
            detail: 상세 정보 (JSON)
            recorded_at: 기록 시각 (없으면 현재 시각)

        Returns:
            생성된 SystemMetric 객체
        """
        metric = SystemMetric(
            metric_type=metric_type,
            detail=detail,
            recorded_at=recorded_at or datetime.utcnow(),
        )
        self._session.add(metric)
        self._session.flush()
        logger.info("시스템 메트릭 기록: type=%s", metric_type)
        return metric

    def get_by_type(
        self, metric_type: str, since: datetime | None = None
    ) -> list[SystemMetric]:
        """메트릭 유형으로 조회한다.

        Args:
            metric_type: 메트릭 유형
            since: 이 시각 이후만 조회 (선택)

        Returns:
            시스템 메트릭 리스트
        """
        stmt = select(SystemMetric).where(SystemMetric.metric_type == metric_type)
        if since is not None:
            stmt = stmt.where(SystemMetric.recorded_at >= since)
        stmt = stmt.order_by(SystemMetric.recorded_at.desc())
        return list(self._session.execute(stmt).scalars().all())


class DailySummaryRepository:
    """일일 요약 데이터 접근 클래스."""

    def __init__(self, session: Session) -> None:
        """초기화.

        Args:
            session: SQLAlchemy 세션
        """
        self._session = session

    def upsert_daily_summary(self, report_date: date) -> DailySummary:
        """일일 요약을 trades 테이블 기반으로 집계하여 UPSERT한다.

        Args:
            report_date: 리포트 날짜

        Returns:
            생성 또는 갱신된 DailySummary 객체
        """
        start = datetime(report_date.year, report_date.month, report_date.day)
        end = start + timedelta(days=1)

        # trades 집계
        trades = list(
            self._session.execute(
                select(Trade).where(Trade.traded_at >= start, Trade.traded_at < end)
            ).scalars().all()
        )

        buy_count = sum(1 for t in trades if t.trade_type == TradeType.BUY)
        sell_count = sum(1 for t in trades if t.trade_type == TradeType.SELL)
        total_pl = sum(t.profit_loss_amount or 0 for t in trades)

        sells = [t for t in trades if t.trade_type == TradeType.SELL]
        win_count = sum(
            1 for t in sells if t.profit_loss_amount is not None and t.profit_loss_amount > 0
        )
        win_rate = (win_count / len(sells)) if sells else 0.0

        stop_loss = sum(1 for t in sells if t.sell_reason == SellReason.STOP_LOSS)
        take_profit = sum(1 for t in sells if t.sell_reason == SellReason.TAKE_PROFIT)
        strategy_sell = sum(1 for t in sells if t.sell_reason == SellReason.STRATEGY)

        # screening_results 집계
        screenings = list(
            self._session.execute(
                select(ScreeningResult).where(
                    ScreeningResult.screened_at >= start,
                    ScreeningResult.screened_at < end,
                )
            ).scalars().all()
        )
        screening_count = len(screenings)
        screening_conversion = sum(1 for s in screenings if s.converted_to_trade)

        # system_metrics 에러 집계
        error_count_result = self._session.execute(
            sa_select(func.count()).select_from(SystemMetric).where(
                SystemMetric.metric_type == "ERROR",
                SystemMetric.recorded_at >= start,
                SystemMetric.recorded_at < end,
            )
        ).scalar_one()

        # 사이클 수 집계
        cycle_count_result = self._session.execute(
            sa_select(func.count()).select_from(SystemMetric).where(
                SystemMetric.metric_type == "CYCLE_START",
                SystemMetric.recorded_at >= start,
                SystemMetric.recorded_at < end,
            )
        ).scalar_one()

        # UPSERT
        stmt = select(DailySummary).where(DailySummary.report_date == report_date)
        summary = self._session.execute(stmt).scalar_one_or_none()

        if summary is None:
            summary = DailySummary(report_date=report_date)
            self._session.add(summary)

        summary.total_buy_count = buy_count
        summary.total_sell_count = sell_count
        summary.total_profit_loss = total_pl
        summary.win_rate = win_rate
        summary.stop_loss_count = stop_loss
        summary.take_profit_count = take_profit
        summary.strategy_sell_count = strategy_sell
        summary.screening_count = screening_count
        summary.screening_conversion_count = screening_conversion
        summary.error_count = error_count_result
        summary.cycle_count = cycle_count_result

        self._session.flush()
        logger.info(
            "일일 요약 갱신: date=%s, buys=%d, sells=%d, pl=%d",
            report_date,
            buy_count,
            sell_count,
            total_pl,
        )
        return summary

    def get_by_date(self, report_date: date) -> DailySummary | None:
        """날짜로 일일 요약을 조회한다.

        Args:
            report_date: 조회 날짜

        Returns:
            DailySummary 객체 또는 None
        """
        stmt = select(DailySummary).where(DailySummary.report_date == report_date)
        return self._session.execute(stmt).scalar_one_or_none()
