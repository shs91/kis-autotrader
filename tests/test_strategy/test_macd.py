"""MACD 전략 단위 테스트."""

from __future__ import annotations

import pandas as pd

from src.strategy.base import SignalType
from src.strategy.macd import MACDStrategy


def _make_df(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": prices})


class TestMACDStrategy:
    """MACD 전략 테스트."""

    def test_insufficient_data_returns_hold(self) -> None:
        """데이터 부족 시 HOLD를 반환한다."""
        strategy = MACDStrategy(fast_period=12, slow_period=26, signal_period=9)
        df = _make_df([100.0] * 10)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
        assert "데이터 부족" in signal.reason

    def test_golden_cross_returns_buy(self) -> None:
        """MACD 골든크로스 시 매수 시그널을 반환한다."""
        strategy = MACDStrategy(fast_period=3, slow_period=6, signal_period=3)
        # V자: 하락→바닥→반등, 인덱스 21에서 교차 (22개 사용)
        prices = list(range(100, 80, -1)) + [80, 82]
        df = _make_df(prices)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.BUY
        assert "골든크로스" in signal.reason

    def test_dead_cross_returns_sell(self) -> None:
        """MACD 데드크로스 시 매도 시그널을 반환한다."""
        strategy = MACDStrategy(fast_period=3, slow_period=6, signal_period=3)
        # 역V자: 상승→천장→하락, 인덱스 1에서 교차
        prices = list(range(80, 100)) + [100, 98]
        df = _make_df(prices)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.SELL
        assert "데드크로스" in signal.reason

    def test_no_cross_returns_hold(self) -> None:
        """교차 미발생 시 HOLD를 반환한다."""
        strategy = MACDStrategy(fast_period=3, slow_period=6, signal_period=3)
        prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
        df = _make_df(prices)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD

    def test_name(self) -> None:
        """전략 이름이 파라미터를 포함한다."""
        strategy = MACDStrategy(fast_period=12, slow_period=26, signal_period=9)
        assert "12" in strategy.name
        assert "26" in strategy.name
