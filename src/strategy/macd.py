"""MACD (이동평균수렴확산) 매매 전략."""

from __future__ import annotations

import math

import pandas as pd

from src.config import settings
from src.strategy.base import BaseStrategy, Signal, SignalType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class MACDStrategy(BaseStrategy):
    """MACD 기반 매매 전략.

    - MACD 선이 시그널 선을 상향 돌파 (골든크로스): 매수
    - MACD 선이 시그널 선을 하향 돌파 (데드크로스): 매도
    - 히스토그램 크기로 신뢰도 산출
    """

    def __init__(
        self,
        fast_period: int | None = None,
        slow_period: int | None = None,
        signal_period: int | None = None,
    ) -> None:
        """MACD 전략을 초기화한다.

        Args:
            fast_period: 빠른 EMA 기간 (기본 12)
            slow_period: 느린 EMA 기간 (기본 26)
            signal_period: 시그널 EMA 기간 (기본 9)
        """
        scfg = settings.strategy
        self._fast = fast_period or getattr(scfg, "macd_fast_period", 12)
        self._slow = slow_period or getattr(scfg, "macd_slow_period", 26)
        self._signal = signal_period or getattr(scfg, "macd_signal_period", 9)

    @property
    def name(self) -> str:
        """전략 이름을 반환한다."""
        return f"MACD({self._fast},{self._slow},{self._signal})"

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """시장 데이터를 분석하여 MACD 기반 시그널을 생성한다."""
        series_len = len(market_data)
        close_raw = market_data["close"] if "close" in market_data.columns else None
        nan_ratio = 0.0
        if close_raw is not None and series_len > 0:
            nan_ratio = float(close_raw.isna().sum()) / series_len

        min_required = self._slow + self._signal + 1
        if series_len < min_required:
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason=f"데이터 부족 (필요: {min_required}개, 현재: {series_len}개)",
                meta={
                    "series_len": series_len,
                    "nan_ratio": round(nan_ratio, 4),
                    "last_macd": None,
                    "last_signal": None,
                    "last_hist": None,
                    "guard_triggered": True,
                    "guard_reason": "insufficient_length",
                },
            )

        close = market_data["close"].astype(float)

        ema_fast = close.ewm(span=self._fast, adjust=False).mean()
        ema_slow = close.ewm(span=self._slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self._signal, adjust=False).mean()
        histogram = macd_line - signal_line

        current_hist = float(histogram.iloc[-1])
        prev_hist = float(histogram.iloc[-2])
        current_macd = float(macd_line.iloc[-1])
        current_signal = float(signal_line.iloc[-1])
        current_price = float(close.iloc[-1])

        if any(math.isnan(v) for v in (current_hist, prev_hist, current_macd, current_signal)):
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason="MACD 값에 NaN 포함 — 데이터 부족",
                meta={
                    "series_len": series_len,
                    "nan_ratio": round(nan_ratio, 4),
                    "last_macd": None if math.isnan(current_macd) else current_macd,
                    "last_signal": None if math.isnan(current_signal) else current_signal,
                    "last_hist": None if math.isnan(current_hist) else current_hist,
                    "guard_triggered": True,
                    "guard_reason": "nan_macd",
                },
            )

        meta: dict[str, object] = {
            "series_len": series_len,
            "nan_ratio": round(nan_ratio, 4),
            "last_macd": current_macd,
            "last_signal": current_signal,
            "last_hist": current_hist,
            "guard_triggered": False,
        }

        # 히스토그램이 음→양: 골든크로스 (매수)
        if prev_hist <= 0 < current_hist:
            confidence = min(abs(current_hist) / (current_price * 0.01), 1.0)
            return Signal(
                signal_type=SignalType.BUY,
                confidence=confidence,
                target_price=current_price,
                reason=f"MACD 골든크로스 (hist: {prev_hist:.2f} → {current_hist:.2f})",
                meta=meta,
            )

        # 히스토그램이 양→음: 데드크로스 (매도)
        if prev_hist >= 0 > current_hist:
            confidence = min(abs(current_hist) / (current_price * 0.01), 1.0)
            return Signal(
                signal_type=SignalType.SELL,
                confidence=confidence,
                target_price=current_price,
                reason=f"MACD 데드크로스 (hist: {prev_hist:.2f} → {current_hist:.2f})",
                meta=meta,
            )

        return Signal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reason=f"MACD 교차 미발생 (hist: {current_hist:.2f})",
            meta=meta,
        )
