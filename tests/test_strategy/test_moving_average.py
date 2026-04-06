"""이동평균 교차 전략 테스트."""

import math

import pytest
import pandas as pd
import numpy as np

from src.strategy.base import SignalType
from src.strategy.moving_average import MovingAverageStrategy
from src.utils.exceptions import StrategyError


class TestMovingAverageStrategyInit:
    """MovingAverageStrategy 초기화 테스트."""

    def test_default_init(self) -> None:
        """기본값으로 초기화한다."""
        strategy = MovingAverageStrategy()
        assert strategy.name == "이동평균교차(5/20)"

    def test_custom_periods(self) -> None:
        """사용자 지정 기간으로 초기화한다."""
        strategy = MovingAverageStrategy(short_period=10, long_period=30)
        assert strategy.name == "이동평균교차(10/30)"

    def test_short_period_not_less_than_long_raises(self) -> None:
        """단기 기간이 장기 기간 이상이면 에러가 발생한다."""
        with pytest.raises(StrategyError, match="단기 기간"):
            MovingAverageStrategy(short_period=20, long_period=20)

    def test_negative_period_raises(self) -> None:
        """기간이 1 미만이면 에러가 발생한다."""
        with pytest.raises(StrategyError, match="1 이상"):
            MovingAverageStrategy(short_period=0, long_period=10)


class TestMovingAverageAnalyze:
    """MovingAverageStrategy.analyze 테스트."""

    def _make_strategy(self) -> MovingAverageStrategy:
        """테스트용 전략을 생성한다 (단기 3, 장기 5)."""
        return MovingAverageStrategy(short_period=3, long_period=5)

    def test_insufficient_data_returns_hold(self) -> None:
        """데이터가 부족하면 HOLD를 반환한다."""
        strategy = self._make_strategy()
        # 장기(5) + 1 = 6개 필요, 5개만 제공
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0, 104.0]})
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
        assert "데이터 부족" in signal.reason

    def test_empty_data_raises(self) -> None:
        """빈 데이터가 전달되면 StrategyError가 발생한다."""
        strategy = self._make_strategy()
        with pytest.raises(StrategyError, match="비어있습니다"):
            strategy.analyze(pd.DataFrame({"close": []}))

    def test_missing_close_column_raises(self) -> None:
        """'close' 컬럼이 없으면 StrategyError가 발생한다."""
        strategy = self._make_strategy()
        df = pd.DataFrame({"price": [100.0, 200.0]})
        with pytest.raises(StrategyError, match="close"):
            strategy.analyze(df)

    def test_golden_cross_buy_signal(self) -> None:
        """골든크로스 발생 시 매수 시그널을 반환한다."""
        strategy = self._make_strategy()

        # 단기(3) MA가 장기(5) MA를 상향 돌파하는 데이터 구성
        # 하락 추세에서 급반등하여 단기가 장기를 돌파
        prices = [
            100.0, 95.0, 90.0, 85.0, 80.0,  # 하락 추세
            75.0,  # 직전 봉: 단기MA(80,75,??) <= 장기MA
            90.0,  # 반등
            105.0,  # 급등
        ]
        # 직전 봉(index 6) 기준: 단기MA(3) = (75+80+85)/3 ≈ 80, 장기MA(5) = (75+80+85+90+95)/5 = 85 -> 단기 < 장기
        # 현재 봉(index 7) 기준: 단기MA(3) = (105+90+75)/3 = 90, 장기MA(5) = (105+90+75+80+85)/5 = 87 -> 단기 > 장기
        # 교차 발생!
        df = pd.DataFrame({"close": prices})
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.BUY
        assert signal.confidence > 0.0
        assert "골든크로스" in signal.reason

    def test_dead_cross_sell_signal(self) -> None:
        """데드크로스 발생 시 매도 시그널을 반환한다."""
        strategy = self._make_strategy()

        # 상승 추세에서 급락하여 단기가 장기를 하향 돌파
        prices = [
            80.0, 85.0, 90.0, 95.0, 100.0,  # 상승 추세
            105.0,  # 직전 봉: 단기MA >= 장기MA
            90.0,   # 급락
            75.0,   # 추가 하락
        ]
        # 직전 봉(index 6) 기준: 단기MA(3) = (90+105+100)/3 = 98.33, 장기MA(5) = (90+105+100+95+90)/5 = 96 -> 단기 > 장기
        # 현재 봉(index 7) 기준: 단기MA(3) = (75+90+105)/3 = 90, 장기MA(5) = (75+90+105+100+95)/5 = 93 -> 단기 < 장기
        # 데드크로스!
        df = pd.DataFrame({"close": prices})
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.SELL
        assert signal.confidence > 0.0
        assert "데드크로스" in signal.reason

    def test_nan_ma_values_return_hold(self) -> None:
        """MA 값에 NaN이 포함되면 HOLD를 반환한다."""
        strategy = self._make_strategy()

        # 데이터 개수는 충분하지만(7개 >= 6개) 중간에 NaN이 있어
        # rolling mean 결과에 NaN이 포함되는 경우
        prices = [100.0, 102.0, float("nan"), 106.0, 108.0, 110.0, 112.0]
        df = pd.DataFrame({"close": prices})
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
        assert "NaN" in signal.reason

    def test_no_cross_hold_signal(self) -> None:
        """교차가 발생하지 않으면 HOLD를 반환한다."""
        strategy = self._make_strategy()

        # 꾸준한 상승 추세 - 교차 없음
        prices = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0]
        df = pd.DataFrame({"close": prices})
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
        assert "교차 미발생" in signal.reason
