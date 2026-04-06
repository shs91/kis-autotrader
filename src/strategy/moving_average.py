"""이동평균 교차 매매 전략."""

from __future__ import annotations

import math

import pandas as pd

from src.strategy.base import BaseStrategy, Signal, SignalType
from src.utils.exceptions import StrategyError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 기본 이동평균 기간
DEFAULT_SHORT_PERIOD: int = 5
DEFAULT_LONG_PERIOD: int = 20

# 신뢰도 계산 상수
MAX_DIVERGENCE_RATE: float = 0.05  # 최대 괴리율 (5%)


class MovingAverageStrategy(BaseStrategy):
    """이동평균 교차 전략.

    단기 이동평균과 장기 이동평균의 교차를 기반으로
    매수/매도 시그널을 생성한다.

    - 골든크로스 (단기 MA > 장기 MA 교차): 매수 시그널
    - 데드크로스 (단기 MA < 장기 MA 교차): 매도 시그널
    """

    def __init__(
        self,
        short_period: int = DEFAULT_SHORT_PERIOD,
        long_period: int = DEFAULT_LONG_PERIOD,
    ) -> None:
        """이동평균 교차 전략을 초기화한다.

        Args:
            short_period: 단기 이동평균 기간
            long_period: 장기 이동평균 기간

        Raises:
            StrategyError: 단기 기간이 장기 기간 이상인 경우
        """
        if short_period >= long_period:
            raise StrategyError(
                f"단기 기간({short_period})은 장기 기간({long_period})보다 작아야 합니다."
            )
        if short_period < 1 or long_period < 1:
            raise StrategyError("이동평균 기간은 1 이상이어야 합니다.")

        self._short_period = short_period
        self._long_period = long_period

    @property
    def name(self) -> str:
        """전략 이름을 반환한다."""
        return f"이동평균교차({self._short_period}/{self._long_period})"

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """시장 데이터를 분석하여 이동평균 교차 기반 시그널을 생성한다.

        DataFrame에 'close' 컬럼이 필요하다.

        Args:
            market_data: 시장 데이터 (컬럼: close, date)

        Returns:
            매매 시그널

        Raises:
            StrategyError: 필수 컬럼이 없는 경우
        """
        self._validate_data(market_data)

        # 데이터가 장기 이동평균 계산에 필요한 최소 개수 + 1 (교차 확인용)보다 적으면 HOLD
        min_required = self._long_period + 1
        if len(market_data) < min_required:
            logger.info(
                "데이터 부족 (필요: %d, 현재: %d) - HOLD 반환",
                min_required,
                len(market_data),
            )
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason=f"데이터 부족 (필요: {min_required}개, 현재: {len(market_data)}개)",
            )

        # 이동평균 계산
        short_ma = market_data["close"].rolling(window=self._short_period).mean()
        long_ma = market_data["close"].rolling(window=self._long_period).mean()

        # 현재 봉과 직전 봉의 MA 값
        current_short = short_ma.iloc[-1]
        current_long = long_ma.iloc[-1]
        prev_short = short_ma.iloc[-2]
        prev_long = long_ma.iloc[-2]

        # NaN 방어: MA 값 중 하나라도 NaN이면 시그널 판단 불가
        if any(math.isnan(v) for v in [current_short, current_long, prev_short, prev_long]):
            logger.warning(
                "MA 값에 NaN 포함 — HOLD 반환 (short: %s, long: %s)",
                current_short,
                current_long,
            )
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason="이동평균 값에 NaN 포함 — 데이터 부족",
            )

        # 괴리율 기반 신뢰도 계산
        divergence_rate = abs(current_short - current_long) / current_long if current_long != 0 else 0.0
        confidence = min(divergence_rate / MAX_DIVERGENCE_RATE, 1.0)

        current_price = float(market_data["close"].iloc[-1])

        # 골든크로스: 직전 봉에서 단기 <= 장기였는데 현재 봉에서 단기 > 장기
        if prev_short <= prev_long and current_short > current_long:
            logger.info(
                "골든크로스 발생 - 단기MA: %.2f, 장기MA: %.2f, 신뢰도: %.2f",
                current_short,
                current_long,
                confidence,
            )
            return Signal(
                signal_type=SignalType.BUY,
                confidence=confidence,
                target_price=current_price,
                reason=(
                    f"골든크로스 발생 (단기MA {current_short:.2f} > 장기MA {current_long:.2f})"
                ),
            )

        # 데드크로스: 직전 봉에서 단기 >= 장기였는데 현재 봉에서 단기 < 장기
        if prev_short >= prev_long and current_short < current_long:
            logger.info(
                "데드크로스 발생 - 단기MA: %.2f, 장기MA: %.2f, 신뢰도: %.2f",
                current_short,
                current_long,
                confidence,
            )
            return Signal(
                signal_type=SignalType.SELL,
                confidence=confidence,
                target_price=current_price,
                reason=(
                    f"데드크로스 발생 (단기MA {current_short:.2f} < 장기MA {current_long:.2f})"
                ),
            )

        # 교차가 발생하지 않은 경우
        return Signal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reason="이동평균 교차 미발생",
        )

    def _validate_data(self, market_data: pd.DataFrame) -> None:
        """입력 데이터의 유효성을 검증한다.

        Args:
            market_data: 검증할 DataFrame

        Raises:
            StrategyError: 필수 컬럼이 없거나 데이터가 비어있는 경우
        """
        if market_data.empty:
            raise StrategyError("시장 데이터가 비어있습니다.")

        if "close" not in market_data.columns:
            raise StrategyError("'close' 컬럼이 필요합니다.")
