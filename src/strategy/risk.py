"""리스크 관리 모듈."""

from __future__ import annotations

from src.config import settings
from src.strategy.base import Signal, SignalType
from src.utils.exceptions import RiskLimitError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)



class RiskManager:
    """리스크 관리를 수행하는 클래스.

    최대 손실률, 포지션 사이징, 일일 매매 횟수 제한 등
    매매 리스크를 종합적으로 관리한다.

    설정값은 src/config.py의 settings.trading에서 가져온다.
    """

    def __init__(
        self,
        max_loss_rate: float | None = None,
        max_position_ratio: float | None = None,
        daily_trade_limit: int | None = None,
        take_profit_ratio: float | None = None,
    ) -> None:
        """리스크 관리자를 초기화한다.

        Args:
            max_loss_rate: 최대 손실률 (None이면 설정값 사용, 기본 3%)
            max_position_ratio: 최대 포지션 비율 (None이면 설정값 사용, 기본 20%)
            daily_trade_limit: 일일 매매 횟수 제한 (None이면 설정값 사용, 기본 10건)
            take_profit_ratio: 익절 비율 (기본 5%)
        """
        self._max_loss_rate = (
            max_loss_rate
            if max_loss_rate is not None
            else settings.trading.max_loss_rate
        )
        self._max_position_ratio = (
            max_position_ratio
            if max_position_ratio is not None
            else settings.trading.max_position_ratio
        )
        self._daily_trade_limit = (
            daily_trade_limit
            if daily_trade_limit is not None
            else settings.trading.daily_trade_limit
        )
        self._take_profit_ratio = (
            take_profit_ratio
            if take_profit_ratio is not None
            else settings.strategy.take_profit_ratio
        )
        self._min_confidence = settings.strategy.min_confidence

    def check_max_loss(self, current_price: float, avg_price: float) -> bool:
        """최대 손실률 초과 여부를 확인한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가

        Returns:
            True이면 손실률이 최대 손실률을 초과한 것

        Raises:
            RiskLimitError: 최대 손실률을 초과한 경우
        """
        if avg_price <= 0:
            raise RiskLimitError("평균 매입가는 0보다 커야 합니다.")

        loss_rate = (avg_price - current_price) / avg_price

        if loss_rate > self._max_loss_rate:
            logger.warning(
                "최대 손실률 초과: 현재 %.2f%% > 제한 %.2f%%",
                loss_rate * 100,
                self._max_loss_rate * 100,
            )
            return True

        return False

    def calculate_position_size(self, total_balance: float, price: float) -> int:
        """포지션 크기(매수 가능 수량)를 계산한다.

        계좌 잔고 대비 최대 포지션 비율을 적용하여
        매수 가능한 최대 수량을 반환한다.

        Args:
            total_balance: 총 계좌 잔고
            price: 현재 주가

        Returns:
            매수 가능 수량 (정수)

        Raises:
            RiskLimitError: 잔고 또는 가격이 유효하지 않은 경우
        """
        if total_balance <= 0:
            raise RiskLimitError("계좌 잔고는 0보다 커야 합니다.")
        if price <= 0:
            raise RiskLimitError("주가는 0보다 커야 합니다.")

        max_investment = total_balance * self._max_position_ratio
        quantity = int(max_investment / price)

        logger.info(
            "포지션 사이징: 잔고 %.0f, 주가 %.0f, 최대투자금 %.0f, 수량 %d",
            total_balance,
            price,
            max_investment,
            quantity,
        )

        return quantity

    def check_daily_trade_limit(self, trade_count: int) -> bool:
        """일일 매매 횟수 제한 초과 여부를 확인한다.

        Args:
            trade_count: 당일 매매 횟수

        Returns:
            True이면 제한을 초과한 것

        Raises:
            RiskLimitError: 일일 매매 횟수 제한을 초과한 경우
        """
        if trade_count >= self._daily_trade_limit:
            logger.warning(
                "일일 매매 횟수 제한 초과: %d >= %d",
                trade_count,
                self._daily_trade_limit,
            )
            return True

        return False

    def should_stop_loss(self, current_price: float, avg_price: float) -> bool:
        """손절 여부를 판단한다.

        현재가가 평균 매입가 대비 최대 손실률 이상 하락하면 손절한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가

        Returns:
            True이면 손절해야 함
        """
        if avg_price <= 0:
            return False

        loss_rate = (avg_price - current_price) / avg_price
        should_stop = loss_rate >= self._max_loss_rate

        if should_stop:
            logger.warning(
                "손절 시그널: 손실률 %.2f%% >= 제한 %.2f%%",
                loss_rate * 100,
                self._max_loss_rate * 100,
            )

        return should_stop

    def should_take_profit(
        self,
        current_price: float,
        avg_price: float,
        profit_ratio: float | None = None,
    ) -> bool:
        """익절 여부를 판단한다.

        현재가가 평균 매입가 대비 익절 비율 이상 상승하면 익절한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가
            profit_ratio: 익절 비율 (None이면 기본값 사용)

        Returns:
            True이면 익절해야 함
        """
        if avg_price <= 0:
            return False

        target_ratio = profit_ratio if profit_ratio is not None else self._take_profit_ratio
        current_profit = (current_price - avg_price) / avg_price
        should_profit = current_profit >= target_ratio

        if should_profit:
            logger.info(
                "익절 시그널: 수익률 %.2f%% >= 목표 %.2f%%",
                current_profit * 100,
                target_ratio * 100,
            )

        return should_profit

    def validate_order(
        self,
        signal: Signal,
        balance: float,
        current_positions: int,
    ) -> bool:
        """주문 유효성을 종합적으로 검증한다.

        매수 시그널인 경우:
        - 잔고가 충분한지 확인
        - 포지션 비율 제한 확인

        Args:
            signal: 매매 시그널
            balance: 가용 잔고
            current_positions: 현재 보유 종목 수

        Returns:
            True이면 주문이 유효함

        Raises:
            RiskLimitError: 주문이 유효하지 않은 경우
        """
        # HOLD 시그널은 주문 불필요
        if signal.signal_type == SignalType.HOLD:
            return False

        # 매수 시 잔고 확인
        if signal.signal_type == SignalType.BUY:
            if balance <= 0:
                raise RiskLimitError("가용 잔고가 부족합니다.")

            if signal.target_price is not None and signal.target_price > balance:
                raise RiskLimitError(
                    f"잔고 부족: 필요 {signal.target_price:.0f}, 가용 {balance:.0f}"
                )

        # 신뢰도가 너무 낮은 시그널은 거부
        if signal.confidence < self._min_confidence:
            logger.info(
                "낮은 신뢰도로 주문 거부: %.2f < %.2f",
                signal.confidence,
                self._min_confidence,
            )
            return False

        logger.info(
            "주문 검증 통과: %s, 신뢰도 %.2f, 잔고 %.0f",
            signal.signal_type.value,
            signal.confidence,
            balance,
        )

        return True
