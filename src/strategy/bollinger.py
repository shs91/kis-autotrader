"""볼린저밴드 매매 전략."""

from __future__ import annotations

import pandas as pd

from src.config import settings
from src.strategy.base import BaseStrategy, Signal, SignalType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BollingerBandStrategy(BaseStrategy):
    """볼린저밴드 기반 매매 전략.

    - 종가가 하단밴드 이하: 과매도 → 매수
    - 종가가 상단밴드 이상: 과매수 → 매도
    - %B 지표로 신뢰도 산출 (0에 가까울수록 매수 신뢰도 ↑)
    """

    def __init__(
        self,
        period: int | None = None,
        num_std: float | None = None,
    ) -> None:
        """볼린저밴드 전략을 초기화한다.

        Args:
            period: 이동평균 기간 (기본 20)
            num_std: 표준편차 배수 (기본 2.0)
        """
        scfg = settings.strategy
        self._period = period or getattr(scfg, "bb_period", 20)
        self._num_std = num_std or getattr(scfg, "bb_num_std", 2.0)

    @property
    def name(self) -> str:
        """전략 이름을 반환한다."""
        return f"볼린저({self._period},{self._num_std})"

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """시장 데이터를 분석하여 볼린저밴드 기반 시그널을 생성한다."""
        if len(market_data) < self._period + 1:
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason=f"데이터 부족 (필요: {self._period + 1}개, 현재: {len(market_data)}개)",
            )

        close = market_data["close"].astype(float)

        sma = close.rolling(window=self._period).mean()
        std = close.rolling(window=self._period).std()

        upper = sma + self._num_std * std
        lower = sma - self._num_std * std

        current_price = float(close.iloc[-1])
        current_upper = float(upper.iloc[-1])
        current_lower = float(lower.iloc[-1])
        current_sma = float(sma.iloc[-1])
        band_width = current_upper - current_lower

        # %B 계산: (종가 - 하단) / (상단 - 하단)
        pct_b = (current_price - current_lower) / band_width if band_width > 0 else 0.5

        # 하단밴드 이하: 매수
        if current_price <= current_lower:
            confidence = min(1.0 - pct_b, 1.0)  # 0에 가까울수록 신뢰도 높음
            return Signal(
                signal_type=SignalType.BUY,
                confidence=max(confidence, 0.1),
                target_price=current_sma,  # 중심선까지 반등 목표
                reason=f"볼린저 하단 돌파 (%B={pct_b:.2f}, 가격={current_price:,.0f} <= 하단={current_lower:,.0f})",
            )

        # 상단밴드 이상: 매도
        if current_price >= current_upper:
            confidence = min(pct_b - 1.0 + 0.5, 1.0)  # 1 초과 시 신뢰도 상승
            return Signal(
                signal_type=SignalType.SELL,
                confidence=max(confidence, 0.1),
                target_price=current_sma,
                reason=f"볼린저 상단 돌파 (%B={pct_b:.2f}, 가격={current_price:,.0f} >= 상단={current_upper:,.0f})",
            )

        return Signal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reason=f"볼린저 밴드 내 (%B={pct_b:.2f})",
        )
