"""RSI 전략 테스트."""

import pytest
import pandas as pd

from src.strategy.base import SignalType
from src.strategy.rsi import RSIStrategy
from src.utils.exceptions import StrategyError


class TestRSIStrategyInit:
    """RSIStrategy 초기화 테스트."""

    def test_default_init(self) -> None:
        """기본값으로 초기화한다."""
        strategy = RSIStrategy()
        assert strategy.name == "RSI(14)"

    def test_custom_params(self) -> None:
        """사용자 지정 파라미터로 초기화한다."""
        strategy = RSIStrategy(period=7, oversold_threshold=25.0, overbought_threshold=75.0)
        assert strategy.name == "RSI(7)"

    def test_invalid_period_raises(self) -> None:
        """기간이 1 미만이면 에러가 발생한다."""
        with pytest.raises(StrategyError, match="1 이상"):
            RSIStrategy(period=0)

    def test_invalid_thresholds_raises(self) -> None:
        """과매도 임계값이 과매수 이상이면 에러가 발생한다."""
        with pytest.raises(StrategyError, match="임계값"):
            RSIStrategy(oversold_threshold=70.0, overbought_threshold=30.0)


def _generate_declining_prices(count: int, start: float = 100.0, drop: float = 2.0) -> list[float]:
    """하락하는 가격 데이터를 생성한다."""
    return [start - i * drop for i in range(count)]


def _generate_rising_prices(count: int, start: float = 100.0, rise: float = 2.0) -> list[float]:
    """상승하는 가격 데이터를 생성한다."""
    return [start + i * rise for i in range(count)]


class TestRSIAnalyze:
    """RSIStrategy.analyze 테스트."""

    def test_insufficient_data_returns_hold(self) -> None:
        """데이터가 부족하면 HOLD를 반환한다."""
        strategy = RSIStrategy(period=14)
        df = pd.DataFrame({"close": list(range(10))})
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
        assert "데이터 부족" in signal.reason

    def test_empty_data_raises(self) -> None:
        """빈 데이터가 전달되면 에러가 발생한다."""
        strategy = RSIStrategy()
        with pytest.raises(StrategyError, match="비어있습니다"):
            strategy.analyze(pd.DataFrame({"close": []}))

    def test_missing_close_column_raises(self) -> None:
        """'close' 컬럼이 없으면 에러가 발생한다."""
        strategy = RSIStrategy()
        with pytest.raises(StrategyError, match="close"):
            strategy.analyze(pd.DataFrame({"price": [100.0]}))

    def test_oversold_buy_signal(self) -> None:
        """지속적 하락으로 RSI < 30이면 매수 시그널을 반환한다."""
        strategy = RSIStrategy(period=5)

        # 충분한 하락 데이터 생성 (RSI가 30 이하가 되도록)
        prices = _generate_declining_prices(30, start=200.0, drop=5.0)
        df = pd.DataFrame({"close": prices})
        signal = strategy.analyze(df)

        assert signal.signal_type == SignalType.BUY
        assert signal.confidence > 0.0
        assert "과매도" in signal.reason

    def test_overbought_sell_signal(self) -> None:
        """지속적 상승으로 RSI > 70이면 매도 시그널을 반환한다."""
        strategy = RSIStrategy(period=5)

        # 충분한 상승 데이터 생성 (RSI가 70 이상이 되도록)
        prices = _generate_rising_prices(30, start=100.0, rise=5.0)
        df = pd.DataFrame({"close": prices})
        signal = strategy.analyze(df)

        assert signal.signal_type == SignalType.SELL
        assert signal.confidence > 0.0
        assert "과매수" in signal.reason

    def test_normal_range_hold_signal(self) -> None:
        """RSI가 30~70 사이이면 HOLD를 반환한다."""
        strategy = RSIStrategy(period=5)

        # 등락을 반복하는 횡보 데이터 (RSI가 중간 범위에 위치하도록)
        prices = []
        for i in range(30):
            if i % 2 == 0:
                prices.append(100.0 + (i % 5))
            else:
                prices.append(100.0 - (i % 5))

        df = pd.DataFrame({"close": prices})
        signal = strategy.analyze(df)

        assert signal.signal_type == SignalType.HOLD
        assert "정상 범위" in signal.reason
