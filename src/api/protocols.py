"""시세/주문/계좌 Provider 인터페이스(Protocol).

국내(Domestic*)와 해외(Overseas*, P2 예정) 구현체가 공유하는 계약이다.
엔진/스케줄러는 구체 클래스가 아니라 이 Protocol에만 의존한다.

``runtime_checkable``은 메서드 이름 존재 여부만 런타임 검사한다. 인자/반환
타입의 정확한 일치는 mypy(strict)가 정적으로 보장한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.api.account import Balance, Execution
from src.api.order import OrderResult
from src.api.overseas_quote import (
    OverseasCurrentPrice,
    OverseasDailyPriceItem,
    OverseasRankItem,
)
from src.api.quote import CurrentPrice, DailyPriceItem


@runtime_checkable
class QuoteProvider(Protocol):
    """시세 조회 인터페이스."""

    async def get_current_price(self, stock_code: str) -> CurrentPrice:
        """종목 현재가를 조회한다."""
        ...

    async def get_daily_price(
        self,
        stock_code: str,
        period: str = "D",
        adjusted: bool = True,
        lookback_days: int = 60,
    ) -> list[DailyPriceItem]:
        """종목 일봉을 조회한다(최신→과거 순)."""
        ...


@runtime_checkable
class OrderProvider(Protocol):
    """주문(매수/매도/정정/취소) 인터페이스."""

    async def buy(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0,
        order_type: str = "01",
    ) -> OrderResult:
        """매수 주문을 실행한다."""
        ...

    async def sell(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0,
        order_type: str = "01",
    ) -> OrderResult:
        """매도 주문을 실행한다."""
        ...

    async def modify(
        self,
        order_no: str,
        stock_code: str,
        quantity: int,
        price: int,
    ) -> OrderResult:
        """주문을 정정한다."""
        ...

    async def cancel(
        self,
        order_no: str,
        stock_code: str,
        quantity: int,
    ) -> OrderResult:
        """주문을 취소한다."""
        ...


@runtime_checkable
class AccountProvider(Protocol):
    """잔고/체결 조회 인터페이스."""

    async def get_balance(self) -> Balance:
        """잔고(보유종목+예수금)를 조회한다."""
        ...

    async def get_executions(self) -> list[Execution]:
        """당일 체결 내역을 조회한다."""
        ...


@runtime_checkable
class OverseasQuoteProvider(Protocol):
    """해외 시세 조회 인터페이스 (가격 Decimal, EXCD/SYMB 기반)."""

    async def get_current_price(
        self, symbol: str, exchange: str
    ) -> OverseasCurrentPrice:
        """해외 종목 현재가를 조회한다."""
        ...

    async def get_daily_price(
        self,
        symbol: str,
        exchange: str,
        period: str = "D",
        lookback_days: int = 60,
    ) -> list[OverseasDailyPriceItem]:
        """해외 종목 일봉을 조회한다(최신→과거)."""
        ...

    async def get_ranking(
        self, exchange: str, top_n: int = 20
    ) -> list[OverseasRankItem]:
        """거래소별 거래량순위를 조회한다."""
        ...
