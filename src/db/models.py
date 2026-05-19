"""SQLAlchemy ORM 모델 정의."""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 선언적 베이스 클래스."""


class EventLevel(enum.Enum):
    """이벤트 심각도."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class TradeType(enum.Enum):
    """매매 유형."""

    BUY = "BUY"
    SELL = "SELL"


class BuyReason(enum.Enum):
    """매수 사유."""

    GOLDEN_CROSS = "GOLDEN_CROSS"
    RSI_OVERSOLD = "RSI_OVERSOLD"
    ENSEMBLE = "ENSEMBLE"
    MANUAL = "MANUAL"


class SellReason(enum.Enum):
    """매도 사유."""

    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    STRATEGY = "STRATEGY"
    MANUAL = "MANUAL"


class OrderType(enum.Enum):
    """주문 유형."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(enum.Enum):
    """주문 상태."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class Stock(Base):
    """종목 마스터 테이블."""

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    is_watchlist: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    orders: Mapped[list[Order]] = relationship("Order", back_populates="stock")
    portfolio: Mapped[Portfolio | None] = relationship("Portfolio", back_populates="stock", uselist=False)

    def __repr__(self) -> str:
        return f"<Stock(code={self.code!r}, name={self.name!r})>"


class Order(Base):
    """주문 이력 테이블."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(
        SAEnum(OrderType, name="order_type_enum"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status_enum"),
        default=OrderStatus.PENDING,
        nullable=False,
    )
    order_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    stock: Mapped[Stock] = relationship("Stock", back_populates="orders")
    executions: Mapped[list[Execution]] = relationship("Execution", back_populates="order")

    def __repr__(self) -> str:
        return (
            f"<Order(id={self.id}, stock_id={self.stock_id}, "
            f"type={self.order_type.value}, status={self.status.value})>"
        )


class Execution(Base):
    """체결 내역 테이블."""

    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), nullable=False)
    executed_price: Mapped[float] = mapped_column(Float, nullable=False)
    executed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    order: Mapped[Order] = relationship("Order", back_populates="executions")

    def __repr__(self) -> str:
        return (
            f"<Execution(id={self.id}, order_id={self.order_id}, "
            f"price={self.executed_price}, qty={self.executed_quantity})>"
        )


class Portfolio(Base):
    """현재 보유 포지션 테이블."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id"), unique=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    stock: Mapped[Stock] = relationship("Stock", back_populates="portfolio")

    def __repr__(self) -> str:
        return (
            f"<Portfolio(stock_id={self.stock_id}, qty={self.quantity}, "
            f"avg={self.avg_price})>"
        )


class DailyPerformance(Base):
    """일일 성과 테이블."""

    __tablename__ = "daily_performances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(unique=True, index=True, nullable=False)
    total_profit_loss: Mapped[float] = mapped_column(Float, nullable=False)
    profit_rate: Mapped[float] = mapped_column(Float, nullable=False)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<DailyPerformance(date={self.date}, "
            f"pl={self.total_profit_loss}, rate={self.profit_rate})>"
        )


class EventLog(Base):
    """시스템 이벤트 로그 테이블."""

    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )
    level: Mapped[EventLevel] = mapped_column(
        SAEnum(EventLevel, name="event_level_enum"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<EventLog(id={self.id}, level={self.level.value}, "
            f"category={self.category!r})>"
        )


class Trade(Base):
    """체결 내역 테이블 (매매 데이터 적재용)."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    trade_type: Mapped[TradeType] = mapped_column(
        SAEnum(TradeType, name="trade_type_enum"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    buy_reason: Mapped[BuyReason | None] = mapped_column(
        SAEnum(BuyReason, name="buy_reason_enum"), nullable=True
    )
    sell_reason: Mapped[SellReason | None] = mapped_column(
        SAEnum(SellReason, name="sell_reason_enum"), nullable=True
    )
    signal_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profit_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_loss_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    traded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Trade(id={self.id}, {self.stock_code} {self.trade_type.value} "
            f"qty={self.quantity} @{self.price})>"
        )


class Signal(Base):
    """전략 시그널 테이블."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    signal_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    action_taken: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Signal(id={self.id}, {self.stock_code} {self.signal_type} "
            f"action={self.action_taken})>"
        )


class ScreeningResult(Base):
    """스크리닝 발굴 테이블."""

    __tablename__ = "screening_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    screening_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_change_pct: Mapped[float] = mapped_column(Float, nullable=False)
    converted_to_trade: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ScreeningResult(id={self.id}, {self.stock_code} "
            f"rank={self.screening_rank})>"
        )


class SystemMetric(Base):
    """시스템 상태 메트릭 테이블."""

    __tablename__ = "system_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SystemMetric(id={self.id}, type={self.metric_type!r})>"


class TaskStatus(enum.Enum):
    """비동기 태스크 상태."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD = "DEAD"


class TaskQueue(Base):
    """비동기 태스크 큐 테이블 (Outbox 패턴)."""

    __tablename__ = "task_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status_enum"),
        default=TaskStatus.PENDING,
        index=True,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<TaskQueue(id={self.id}, type={self.task_type!r}, "
            f"status={self.status.value})>"
        )


class ImplementationCategory(enum.Enum):
    """자동 구현 카테고리."""

    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    PARAM_TUNING = "param_tuning"
    FEATURE = "feature"
    ENHANCEMENT = "enhancement"
    PERFORMANCE = "performance"
    DOCS = "docs"
    CONFIG = "config"


class ProposalState(enum.Enum):
    """제안서 상태 머신."""

    DRAFT = "draft"
    READY = "ready"
    IN_FLIGHT = "in_flight"
    IMPLEMENTED = "implemented"
    FAILED = "failed"
    SKIPPED = "skipped"
    REVIEW_REQUIRED = "review_required"


class ProposalPriority(enum.Enum):
    """제안서 우선순위."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ImplementationLog(Base):
    """자동 구현 변경 이력 테이블 (CHANGELOG 대체)."""

    __tablename__ = "implementation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[ImplementationCategory] = mapped_column(
        SAEnum(ImplementationCategory, name="impl_category_enum"), nullable=False
    )
    proposal_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    changed_files: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_effect: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    implemented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ImplementationLog(id={self.id}, title={self.title!r}, "
            f"category={self.category.value}, version={self.version!r})>"
        )


class Proposal(Base):
    """자동 구현 파이프라인의 제안서 상태 테이블.

    md 파일은 사람이 읽는 표현. 본 테이블이 상태의 sole source of truth다.
    상태 전이는 ProposalRepository의 mark_* 메소드를 통해서만 일어난다.
    """

    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[ImplementationCategory] = mapped_column(
        SAEnum(ImplementationCategory, name="impl_category_enum", create_type=False),
        nullable=False,
    )
    state: Mapped[ProposalState] = mapped_column(
        SAEnum(ProposalState, name="proposal_state_enum"),
        nullable=False,
        index=True,
    )
    priority: Mapped[ProposalPriority] = mapped_column(
        SAEnum(ProposalPriority, name="proposal_priority_enum"),
        nullable=False,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    prediction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Proposal(id={self.id}, path={self.path!r}, "
            f"state={self.state.value}, category={self.category.value})>"
        )


class TrajectoryStep(enum.Enum):
    """사이클 trajectory 단계."""

    INITIALIZER = "initializer"
    VALIDATOR = "validator"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    EVALUATOR = "evaluator"
    RECORDER = "recorder"
    ROLLBACK = "rollback"


class TrajectoryStatus(enum.Enum):
    """trajectory entry 결과."""

    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class TrajectoryEntry(Base):
    """사이클 단계별 trajectory entry — Experience Observability."""

    __tablename__ = "trajectory_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step: Mapped[TrajectoryStep] = mapped_column(
        SAEnum(TrajectoryStep, name="trajectory_step_enum"),
        nullable=False, index=True,
    )
    proposal_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    agent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[TrajectoryStatus] = mapped_column(
        SAEnum(TrajectoryStatus, name="trajectory_status_enum"),
        nullable=False,
    )
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_usage_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TrajectoryEntry(cycle={self.cycle_id}, step={self.step.value}, "
            f"status={self.status.value})>"
        )


class DailySummary(Base):
    """일일 요약 테이블 (리포트용 집계)."""

    __tablename__ = "daily_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(
        Date, unique=True, index=True, nullable=False
    )
    total_buy_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_sell_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_profit_loss: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stop_loss_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    take_profit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    strategy_sell_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    screening_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    screening_conversion_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<DailySummary(date={self.report_date}, "
            f"buys={self.total_buy_count}, sells={self.total_sell_count})>"
        )


class NewsSourceType(enum.Enum):
    """뉴스/공시 데이터 소스 유형."""

    DISCLOSURE = "disclosure"
    NEWS = "news"
    EARNINGS = "earnings"
    REPORT = "report"


class NewsChunk(Base):
    """뉴스·공시 데이터의 임베딩 청크 테이블 (RAG 컨텍스트).

    한 source 문서가 여러 chunk로 분할될 수 있으며, (ticker, content_hash)로
    중복 적재를 차단한다. event_time(원천 사건 시각)과 fetched_at(수집 시각)을
    분리해 retriever가 시점 기반 필터를 정확히 걸 수 있도록 한다.
    """

    __tablename__ = "news_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    source_type: Mapped[NewsSourceType] = mapped_column(
        SAEnum(NewsSourceType, name="news_source_type"),
        nullable=False,
        index=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 512 = feed_label(영문 prefix) + ':' + 길어질 수 있는 RSS guid/URL 여유분.
    # DART rcept_no는 12자라 짧지만, RSS guid는 종종 기사 URL을 그대로 사용.
    source_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    corr_source_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    chunk_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("ticker", "content_hash", name="uq_news_chunks_ticker_hash"),
    )

    def __repr__(self) -> str:
        return (
            f"<NewsChunk(id={self.id}, ticker={self.ticker!r}, "
            f"source={self.source_type.value}, idx={self.chunk_index})>"
        )


class NewsCollectionState(Base):
    """소스별 마지막 수집 시각 추적 (증분 수집용)."""

    __tablename__ = "news_collection_state"

    source_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<NewsCollectionState(source={self.source_name!r}, "
            f"last={self.last_collected_at.isoformat()})>"
        )
