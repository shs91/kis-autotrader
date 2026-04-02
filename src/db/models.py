"""SQLAlchemy ORM 모델 정의."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 선언적 베이스 클래스."""


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
