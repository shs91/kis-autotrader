"""앙상블 전략 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategy.base import BaseStrategy, Signal, SignalType
from src.strategy.ensemble import EnsembleStrategy


class FixedStrategy(BaseStrategy):
    """테스트용 고정 시그널 전략."""

    def __init__(self, signal_type: SignalType, confidence: float) -> None:
        self._signal = Signal(signal_type=signal_type, confidence=confidence)

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        return self._signal

    @property
    def name(self) -> str:
        return f"fixed({self._signal.signal_type.value})"


EMPTY_DF = pd.DataFrame()


# --- majority vote tests ---


def test_majority_buy_wins() -> None:
    """BUY 2 vs SELL 1 → BUY, confidence ≈ 0.6."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.7),
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.SELL, 0.3),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY
    assert result.confidence == pytest.approx(0.6, abs=0.01)


def test_majority_sell_wins() -> None:
    """SELL 2 vs BUY 1 → SELL."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.SELL, 0.8),
            FixedStrategy(SignalType.SELL, 0.6),
            FixedStrategy(SignalType.BUY, 0.3),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.SELL


def test_majority_tie_hold() -> None:
    """BUY 1 vs SELL 1 → HOLD."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.SELL, 0.5),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD


def test_majority_all_hold() -> None:
    """HOLD + HOLD → HOLD."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    assert result.confidence == 0.0


def test_majority_confidence_avg() -> None:
    """다수결 승자 시그널의 confidence 평균값 검증."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.7),
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.SELL, 0.3),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    # BUY 승리 → (0.7 + 0.5) / 2 = 0.6
    assert result.confidence == pytest.approx((0.7 + 0.5) / 2)


# --- weighted vote tests ---


def test_weighted_buy_wins() -> None:
    """BUY 가중합 1.0 vs SELL 가중합 0.8 → BUY."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.7),
            FixedStrategy(SignalType.BUY, 0.3),
            FixedStrategy(SignalType.SELL, 0.8),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY
    # confidence = buy_weight / len(signals) = 1.0 / 3
    assert result.confidence == pytest.approx(1.0 / 3, abs=0.01)


def test_weighted_sell_wins() -> None:
    """SELL 가중합 0.9 vs BUY 가중합 0.6 → SELL."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.SELL, 0.9),
            FixedStrategy(SignalType.BUY, 0.3),
            FixedStrategy(SignalType.BUY, 0.3),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.SELL
    # confidence = sell_weight / len(signals) = 0.9 / 3
    assert result.confidence == pytest.approx(0.9 / 3, abs=0.01)


# --- init validation tests ---


def test_init_one_strategy() -> None:
    """하위 전략이 1개면 ValueError."""
    with pytest.raises(ValueError, match="최소 2개"):
        EnsembleStrategy([FixedStrategy(SignalType.BUY, 0.5)])


def test_init_invalid_method() -> None:
    """지원하지 않는 투표 방식이면 ValueError."""
    with pytest.raises(ValueError, match="지원하지 않는"):
        EnsembleStrategy(
            [
                FixedStrategy(SignalType.BUY, 0.5),
                FixedStrategy(SignalType.SELL, 0.5),
            ],
            method="invalid",
        )


# --- name format test ---


def test_name_format() -> None:
    """앙상블 이름에 '앙상블' 문자열이 포함되어야 한다."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.SELL, 0.5),
        ],
    )
    assert "앙상블" in ensemble.name
