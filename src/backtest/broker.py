"""가상 브로커 — 백테스트용 주문 실행 및 잔고 관리."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TradeSide(Enum):
    """매매 방향."""

    BUY = "BUY"
    SELL = "SELL"


@dataclass
class BacktestConfig:
    """백테스트 설정."""

    initial_capital: int = 10_000_000
    """초기 자본금 (원)."""
    commission_rate: float = 0.00015
    """수수료율 0.015%."""
    slippage_rate: float = 0.001
    """슬리피지 0.1%."""
    max_position_ratio: float = 0.2
    """1종목 최대 투자 비율."""
    max_loss_rate: float = 0.03
    """손절 기준 (3%)."""
    take_profit_ratio: float = 0.05
    """익절 기준 (5%)."""


@dataclass
class Position:
    """보유 포지션."""

    stock_code: str
    """종목 코드."""
    quantity: int
    """보유 수량."""
    avg_price: float
    """평균 매수 단가."""
    entry_date: str
    """진입 일자 (YYYY-MM-DD)."""


@dataclass
class TradeRecord:
    """거래 기록."""

    date: str
    """거래 일자 (YYYY-MM-DD)."""
    stock_code: str
    """종목 코드."""
    side: TradeSide
    """매매 방향."""
    price: float
    """체결 단가 (슬리피지 반영)."""
    quantity: int
    """체결 수량."""
    commission: float
    """수수료."""
    profit_loss: float = 0.0
    """실현 손익 (매도 시에만)."""
    profit_rate: float = 0.0
    """수익률 % (매도 시에만)."""


class VirtualBroker:
    """가상 브로커.

    백테스트 엔진에서 사용하는 가상 주문 실행기.
    수수료·슬리피지를 반영하여 매수/매도를 처리하고,
    포지션 및 현금을 관리한다.
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        """초기화.

        Args:
            config: 백테스트 설정. None이면 기본값 사용.
        """
        self._config = config or BacktestConfig()
        self._cash: float = float(self._config.initial_capital)
        self._positions: dict[str, Position] = {}
        self._trade_history: list[TradeRecord] = []

    # ------------------------------------------------------------------
    # 매수
    # ------------------------------------------------------------------

    def buy(
        self, stock_code: str, price: float, date: str
    ) -> TradeRecord | None:
        """매수 주문을 실행한다.

        슬리피지를 반영한 체결가로 max_position_ratio 만큼 매수한다.

        Args:
            stock_code: 종목 코드.
            price: 현재가 (슬리피지 반영 전).
            date: 거래 일자 (YYYY-MM-DD).

        Returns:
            체결된 TradeRecord. 이미 보유 중이거나 현금 부족 시 None.
        """
        if stock_code in self._positions:
            logger.debug("이미 보유 중인 종목: %s", stock_code)
            return None

        adjusted_price = price * (1 + self._config.slippage_rate)
        investable = self._cash * self._config.max_position_ratio
        quantity = int(investable / adjusted_price)

        if quantity <= 0:
            logger.debug("매수 가능 수량 부족: %s (현금=%.0f)", stock_code, self._cash)
            return None

        commission = adjusted_price * quantity * self._config.commission_rate
        total_cost = adjusted_price * quantity + commission

        if total_cost > self._cash:
            # 수수료 포함 시 현금 초과 → 수량 1주 줄여 재계산
            quantity -= 1
            if quantity <= 0:
                return None
            commission = adjusted_price * quantity * self._config.commission_rate
            total_cost = adjusted_price * quantity + commission
            if total_cost > self._cash:
                return None

        self._cash -= total_cost
        self._positions[stock_code] = Position(
            stock_code=stock_code,
            quantity=quantity,
            avg_price=adjusted_price,
            entry_date=date,
        )

        record = TradeRecord(
            date=date,
            stock_code=stock_code,
            side=TradeSide.BUY,
            price=adjusted_price,
            quantity=quantity,
            commission=commission,
        )
        self._trade_history.append(record)
        logger.info(
            "[BUY] %s | %s | %d주 @ %.0f | 수수료 %.0f",
            date, stock_code, quantity, adjusted_price, commission,
        )
        return record

    # ------------------------------------------------------------------
    # 매도
    # ------------------------------------------------------------------

    def sell(
        self,
        stock_code: str,
        price: float,
        date: str,
        reason: str = "",
    ) -> TradeRecord | None:
        """매도 주문을 실행한다.

        보유 포지션 전량을 슬리피지 반영가로 매도한다.

        Args:
            stock_code: 종목 코드.
            price: 현재가 (슬리피지 반영 전).
            date: 거래 일자 (YYYY-MM-DD).
            reason: 매도 사유 (로그용).

        Returns:
            체결된 TradeRecord. 미보유 시 None.
        """
        position = self._positions.get(stock_code)
        if position is None:
            logger.debug("미보유 종목 매도 시도: %s", stock_code)
            return None

        adjusted_price = price * (1 - self._config.slippage_rate)
        quantity = position.quantity
        commission = adjusted_price * quantity * self._config.commission_rate
        proceeds = adjusted_price * quantity - commission

        profit_loss = (adjusted_price - position.avg_price) * quantity - commission
        profit_rate = (adjusted_price - position.avg_price) / position.avg_price * 100

        self._cash += proceeds
        del self._positions[stock_code]

        record = TradeRecord(
            date=date,
            stock_code=stock_code,
            side=TradeSide.SELL,
            price=adjusted_price,
            quantity=quantity,
            commission=commission,
            profit_loss=profit_loss,
            profit_rate=profit_rate,
        )
        self._trade_history.append(record)
        reason_str = f" ({reason})" if reason else ""
        logger.info(
            "[SELL] %s | %s | %d주 @ %.0f | 손익 %.0f (%.2f%%)%s",
            date, stock_code, quantity, adjusted_price,
            profit_loss, profit_rate, reason_str,
        )
        return record

    # ------------------------------------------------------------------
    # 손절 / 익절 판정
    # ------------------------------------------------------------------

    def check_stop_loss(self, stock_code: str, current_price: float) -> bool:
        """손절 기준 도달 여부를 확인한다.

        Args:
            stock_code: 종목 코드.
            current_price: 현재가.

        Returns:
            손절 기준 이상 하락 시 True.
        """
        position = self._positions.get(stock_code)
        if position is None:
            return False
        loss_rate = (position.avg_price - current_price) / position.avg_price
        return loss_rate >= self._config.max_loss_rate

    def check_take_profit(self, stock_code: str, current_price: float) -> bool:
        """익절 기준 도달 여부를 확인한다.

        Args:
            stock_code: 종목 코드.
            current_price: 현재가.

        Returns:
            익절 기준 이상 상승 시 True.
        """
        position = self._positions.get(stock_code)
        if position is None:
            return False
        gain_rate = (current_price - position.avg_price) / position.avg_price
        return gain_rate >= self._config.take_profit_ratio

    # ------------------------------------------------------------------
    # 조회 프로퍼티
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        """현재 보유 현금을 반환한다."""
        return self._cash

    @property
    def positions(self) -> dict[str, Position]:
        """현재 보유 포지션 딕셔너리를 반환한다."""
        return dict(self._positions)

    def portfolio_value(self, current_prices: dict[str, float]) -> float:
        """포트폴리오 총 평가액을 계산한다.

        Args:
            current_prices: 종목별 현재가 딕셔너리.

        Returns:
            현금 + 보유 종목 평가액 합계.
        """
        stock_value = sum(
            pos.quantity * current_prices.get(pos.stock_code, pos.avg_price)
            for pos in self._positions.values()
        )
        return self._cash + stock_value

    @property
    def trade_history(self) -> list[TradeRecord]:
        """전체 거래 기록 리스트를 반환한다."""
        return list(self._trade_history)
