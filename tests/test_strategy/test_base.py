"""매매 전략 기본 클래스 테스트."""

import pytest
import pandas as pd

from src.strategy.base import BaseStrategy, Signal, SignalType


class TestSignalType:
    """SignalType 열거형 테스트."""

    def test_signal_types_exist(self) -> None:
        """BUY, SELL, HOLD 시그널 유형이 존재하는지 확인한다."""
        assert SignalType.BUY.value == "BUY"
        assert SignalType.SELL.value == "SELL"
        assert SignalType.HOLD.value == "HOLD"


class TestSignal:
    """Signal 데이터 클래스 테스트."""

    def test_create_buy_signal(self) -> None:
        """매수 시그널을 정상적으로 생성한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50000.0,
            stop_loss_price=48000.0,
            reason="골든크로스 발생",
        )
        assert signal.signal_type == SignalType.BUY
        assert signal.confidence == 0.8
        assert signal.target_price == 50000.0
        assert signal.stop_loss_price == 48000.0
        assert signal.reason == "골든크로스 발생"

    def test_create_signal_with_defaults(self) -> None:
        """기본값으로 시그널을 생성한다."""
        signal = Signal(signal_type=SignalType.HOLD, confidence=0.0)
        assert signal.target_price is None
        assert signal.stop_loss_price is None
        assert signal.reason == ""

    def test_confidence_boundary_zero(self) -> None:
        """신뢰도 0.0이 유효한지 확인한다."""
        signal = Signal(signal_type=SignalType.HOLD, confidence=0.0)
        assert signal.confidence == 0.0

    def test_confidence_boundary_one(self) -> None:
        """신뢰도 1.0이 유효한지 확인한다."""
        signal = Signal(signal_type=SignalType.BUY, confidence=1.0)
        assert signal.confidence == 1.0

    def test_confidence_below_zero_raises(self) -> None:
        """신뢰도가 0 미만이면 ValueError가 발생한다."""
        with pytest.raises(ValueError, match="신뢰도"):
            Signal(signal_type=SignalType.BUY, confidence=-0.1)

    def test_confidence_above_one_raises(self) -> None:
        """신뢰도가 1 초과이면 ValueError가 발생한다."""
        with pytest.raises(ValueError, match="신뢰도"):
            Signal(signal_type=SignalType.BUY, confidence=1.1)


class TestBaseStrategy:
    """BaseStrategy 추상 클래스 테스트."""

    def test_cannot_instantiate_directly(self) -> None:
        """추상 클래스를 직접 인스턴스화할 수 없다."""
        with pytest.raises(TypeError):
            BaseStrategy()  # type: ignore[abstract]

    def test_concrete_strategy_works(self) -> None:
        """구체 전략 클래스가 정상적으로 동작한다."""

        class DummyStrategy(BaseStrategy):
            def analyze(self, market_data: pd.DataFrame) -> Signal:
                return Signal(signal_type=SignalType.HOLD, confidence=0.0)

            @property
            def name(self) -> str:
                return "더미전략"

        strategy = DummyStrategy()
        assert strategy.name == "더미전략"

        df = pd.DataFrame({"close": [100, 200, 300]})
        signal = strategy.analyze(df)
        assert signal.signal_type == SignalType.HOLD
