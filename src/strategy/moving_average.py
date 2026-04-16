"""이동평균 교차 매매 전략."""

from __future__ import annotations

import math

import pandas as pd

from src.config import settings
from src.strategy.base import BaseStrategy, Signal, SignalType
from src.utils.exceptions import StrategyError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)  # 최대 괴리율 (5%)


class MovingAverageStrategy(BaseStrategy):
    """이동평균 교차 전략.

    단기 이동평균과 장기 이동평균의 교차를 기반으로
    매수/매도 시그널을 생성한다.

    - 골든크로스 (단기 MA > 장기 MA 교차): 매수 시그널
    - 데드크로스 (단기 MA < 장기 MA 교차): 매도 시그널
    """

    def __init__(
        self,
        short_period: int | None = None,
        long_period: int | None = None,
    ) -> None:
        """이동평균 교차 전략을 초기화한다.

        Args:
            short_period: 단기 이동평균 기간
            long_period: 장기 이동평균 기간

        Raises:
            StrategyError: 단기 기간이 장기 기간 이상인 경우
        """
        scfg = settings.strategy
        short_period = short_period if short_period is not None else scfg.ma_short_period
        long_period = long_period if long_period is not None else scfg.ma_long_period

        if short_period >= long_period:
            raise StrategyError(
                f"단기 기간({short_period})은 장기 기간({long_period})보다 작아야 합니다."
            )
        if short_period < 1 or long_period < 1:
            raise StrategyError("이동평균 기간은 1 이상이어야 합니다.")

        self._short_period = short_period
        self._long_period = long_period
        self._max_divergence = scfg.ma_max_divergence

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

        series_len = len(market_data)
        close_series = market_data["close"]
        nan_count = int(close_series.isna().sum())
        nan_ratio = (nan_count / series_len) if series_len > 0 else 0.0

        # 데이터가 장기 이동평균 계산에 필요한 최소 개수 + 1 (교차 확인용)보다 적으면 HOLD
        min_required = self._long_period + 1
        if series_len < min_required:
            logger.info(
                "데이터 부족 (필요: %d, 현재: %d) - HOLD 반환",
                min_required,
                series_len,
            )
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason=f"데이터 부족 (필요: {min_required}개, 현재: {series_len}개)",
                meta={
                    "series_len": series_len,
                    "nan_ratio": round(nan_ratio, 4),
                    "last_short": None,
                    "last_long": None,
                    "guard_triggered": True,
                    "guard_reason": "insufficient_length",
                },
            )

        # 이동평균 계산
        short_ma = close_series.rolling(window=self._short_period).mean()
        long_ma = close_series.rolling(window=self._long_period).mean()

        # 현재 봉과 직전 봉의 MA 값
        current_short = short_ma.iloc[-1]
        current_long = long_ma.iloc[-1]
        prev_short = short_ma.iloc[-2]
        prev_long = long_ma.iloc[-2]

        last_short_val = (
            None if math.isnan(current_short) else float(current_short)
        )
        last_long_val = (
            None if math.isnan(current_long) else float(current_long)
        )

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
                meta={
                    "series_len": series_len,
                    "nan_ratio": round(nan_ratio, 4),
                    "last_short": last_short_val,
                    "last_long": last_long_val,
                    "guard_triggered": True,
                    "guard_reason": "nan_in_ma",
                },
            )

        # 괴리율 기반 신뢰도 계산
        divergence_rate = abs(current_short - current_long) / current_long if current_long != 0 else 0.0
        confidence = min(divergence_rate / self._max_divergence, 1.0)

        current_price = float(close_series.iloc[-1])

        meta: dict[str, object] = {
            "series_len": series_len,
            "nan_ratio": round(nan_ratio, 4),
            "last_short": float(current_short),
            "last_long": float(current_long),
            "guard_triggered": False,
        }

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
                meta=meta,
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
                meta=meta,
            )

        # 교차가 발생하지 않은 경우
        return Signal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reason="이동평균 교차 미발생",
            meta=meta,
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
