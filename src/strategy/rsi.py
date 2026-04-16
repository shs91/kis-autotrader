"""RSI 기반 매매 전략."""

from __future__ import annotations

import math

import pandas as pd

from src.config import settings
from src.strategy.base import BaseStrategy, Signal, SignalType
from src.utils.exceptions import StrategyError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class RSIStrategy(BaseStrategy):
    """RSI (Relative Strength Index) 기반 매매 전략.

    - RSI < 과매도 임계값 (기본 30): 매수 시그널
    - RSI > 과매수 임계값 (기본 70): 매도 시그널
    - 그 외: 보유 (HOLD)

    신뢰도는 RSI가 극단값에 가까울수록 높아진다.
    """

    def __init__(
        self,
        period: int | None = None,
        oversold_threshold: float | None = None,
        overbought_threshold: float | None = None,
    ) -> None:
        """RSI 전략을 초기화한다.

        Args:
            period: RSI 계산 기간
            oversold_threshold: 과매도 임계값
            overbought_threshold: 과매수 임계값

        Raises:
            StrategyError: 파라미터 값이 유효하지 않은 경우
        """
        scfg = settings.strategy
        period = period if period is not None else scfg.rsi_period
        oversold_threshold = oversold_threshold if oversold_threshold is not None else scfg.rsi_oversold
        overbought_threshold = overbought_threshold if overbought_threshold is not None else scfg.rsi_overbought

        if period < 1:
            raise StrategyError("RSI 기간은 1 이상이어야 합니다.")
        if not 0.0 < oversold_threshold < overbought_threshold < 100.0:
            raise StrategyError(
                f"임계값이 유효하지 않습니다: "
                f"과매도({oversold_threshold}) < 과매수({overbought_threshold}), "
                f"0 < 값 < 100 이어야 합니다."
            )

        self._period = period
        self._oversold = oversold_threshold
        self._overbought = overbought_threshold

    @property
    def name(self) -> str:
        """전략 이름을 반환한다."""
        return f"RSI({self._period})"

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """시장 데이터를 분석하여 RSI 기반 시그널을 생성한다.

        DataFrame에 'close' 컬럼이 필요하다.

        Args:
            market_data: 시장 데이터 (컬럼: close)

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

        # RSI 계산을 위해 최소 period + 1개 데이터 필요
        min_required = self._period + 1
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
                    "last_rsi": None,
                    "guard_triggered": True,
                    "guard_reason": "insufficient_length",
                },
            )

        rsi = self._calculate_rsi(close_series)
        current_rsi = rsi.iloc[-1]
        current_price = float(close_series.iloc[-1])

        last_rsi_val = (
            None if (isinstance(current_rsi, float) and math.isnan(current_rsi))
            else float(current_rsi)
        )

        # NaN 방어: RSI 계산 결과가 NaN이면 시그널 판단 불가
        if last_rsi_val is None:
            logger.warning("RSI 값이 NaN — HOLD 반환")
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason="RSI 값이 NaN — 데이터 부족",
                meta={
                    "series_len": series_len,
                    "nan_ratio": round(nan_ratio, 4),
                    "last_rsi": None,
                    "guard_triggered": True,
                    "guard_reason": "nan_rsi",
                },
            )

        meta: dict[str, object] = {
            "series_len": series_len,
            "nan_ratio": round(nan_ratio, 4),
            "last_rsi": last_rsi_val,
            "guard_triggered": False,
        }

        # 과매도 구간 - 매수 시그널
        if current_rsi < self._oversold:
            confidence = self._calculate_oversold_confidence(current_rsi)
            logger.info(
                "RSI 과매도 시그널: RSI=%.2f (< %.0f), 신뢰도=%.2f, 현재가=%d",
                current_rsi, self._oversold, confidence, current_price,
            )
            return Signal(
                signal_type=SignalType.BUY,
                confidence=confidence,
                target_price=current_price,
                reason=f"과매도 구간 (RSI: {current_rsi:.2f} < {self._oversold})",
                meta=meta,
            )

        # 과매수 구간 - 매도 시그널
        if current_rsi > self._overbought:
            confidence = self._calculate_overbought_confidence(current_rsi)
            logger.info(
                "RSI 과매수 시그널: RSI=%.2f (> %.0f), 신뢰도=%.2f, 현재가=%d",
                current_rsi, self._overbought, confidence, current_price,
            )
            return Signal(
                signal_type=SignalType.SELL,
                confidence=confidence,
                target_price=current_price,
                reason=f"과매수 구간 (RSI: {current_rsi:.2f} > {self._overbought})",
                meta=meta,
            )

        # 정상 범위 - HOLD
        logger.debug("RSI HOLD: RSI=%.2f (정상 범위 %.0f~%.0f)", current_rsi, self._oversold, self._overbought)
        return Signal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reason=f"RSI 정상 범위 ({current_rsi:.2f})",
            meta=meta,
        )

    def _calculate_rsi(self, close_prices: pd.Series) -> pd.Series:  # type: ignore[type-arg]
        """RSI를 계산한다.

        Wilder의 평활화 방식(exponential moving average)을 사용한다.

        Args:
            close_prices: 종가 시리즈

        Returns:
            RSI 시리즈
        """
        delta = close_prices.diff()

        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1.0 / self._period, min_periods=self._period).mean()
        avg_loss = loss.ewm(alpha=1.0 / self._period, min_periods=self._period).mean()

        rs = avg_gain / avg_loss
        rsi: pd.Series[float] = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _calculate_oversold_confidence(self, rsi: float) -> float:
        """과매도 구간의 신뢰도를 계산한다.

        RSI가 0에 가까울수록 신뢰도가 높다.

        Args:
            rsi: 현재 RSI 값

        Returns:
            신뢰도 (0.0 ~ 1.0)
        """
        # RSI 0이면 신뢰도 1.0, 과매도 임계값이면 신뢰도 0.0 근처
        return min(max((self._oversold - rsi) / self._oversold, 0.0), 1.0)

    def _calculate_overbought_confidence(self, rsi: float) -> float:
        """과매수 구간의 신뢰도를 계산한다.

        RSI가 100에 가까울수록 신뢰도가 높다.

        Args:
            rsi: 현재 RSI 값

        Returns:
            신뢰도 (0.0 ~ 1.0)
        """
        # RSI 100이면 신뢰도 1.0, 과매수 임계값이면 신뢰도 0.0 근처
        upper_range = 100.0 - self._overbought
        return min(max((rsi - self._overbought) / upper_range, 0.0), 1.0)

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
