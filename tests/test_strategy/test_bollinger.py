"""볼린저밴드 전략 단위 테스트."""

from __future__ import annotations

import pandas as pd

from src.strategy.base import SignalType
from src.strategy.bollinger import BollingerBandStrategy


def _make_df(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": prices})


class TestBollingerBandStrategy:
    """볼린저밴드 전략 테스트."""

    def test_insufficient_data_returns_hold(self) -> None:
        """데이터 부족 시 HOLD를 반환한다."""
        strategy = BollingerBandStrategy(period=20, num_std=2.0)
        df = _make_df([100.0] * 10)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
        assert "데이터 부족" in signal.reason

    def test_price_below_lower_band_returns_buy(self) -> None:
        """하단밴드 이하 시 매수 시그널을 반환한다."""
        strategy = BollingerBandStrategy(period=5, num_std=1.5)
        # 안정적 가격 후 급락
        prices = [100, 100, 100, 100, 100, 80]
        df = _make_df(prices)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.BUY
        assert "하단 돌파" in signal.reason

    def test_price_above_upper_band_returns_sell(self) -> None:
        """상단밴드 이상 시 매도 시그널을 반환한다."""
        strategy = BollingerBandStrategy(period=5, num_std=1.5)
        # 안정적 가격 후 급등
        prices = [100, 100, 100, 100, 100, 120]
        df = _make_df(prices)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.SELL
        assert "상단 돌파" in signal.reason

    def test_price_within_band_returns_hold(self) -> None:
        """밴드 내 가격은 HOLD를 반환한다."""
        strategy = BollingerBandStrategy(period=5, num_std=2.0)
        prices = [100, 101, 99, 100, 101, 100]
        df = _make_df(prices)
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
        assert "밴드 내" in signal.reason

    def test_name(self) -> None:
        """전략 이름이 파라미터를 포함한다."""
        strategy = BollingerBandStrategy(period=20, num_std=2.0)
        assert "20" in strategy.name
