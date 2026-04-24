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


def test_hold_meta_all_hold() -> None:
    """모든 전략이 HOLD일 때 투표 meta가 채워진다."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    assert "method" in result.meta
    assert result.meta["method"] == "majority"
    assert len(result.meta["votes"]) == 2
    assert result.meta["votes"][0]["action"] == "HOLD"


def test_hold_meta_tie() -> None:
    """동수 투표로 HOLD 수렴 시 투표 meta가 채워진다."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.7),
            FixedStrategy(SignalType.SELL, 0.5),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    assert result.meta["method"] == "majority"
    assert result.meta["votes"][0]["action"] == "BUY"
    assert result.meta["votes"][1]["action"] == "SELL"


def test_buy_signal_no_hold_meta() -> None:
    """BUY 시그널에는 투표 meta가 비어있다."""
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
    assert result.meta == {}


def test_name_format() -> None:
    """앙상블 이름에 '앙상블' 문자열이 포함되어야 한다."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.BUY, 0.5),
            FixedStrategy(SignalType.SELL, 0.5),
        ],
    )
    assert "앙상블" in ensemble.name


def test_weighted_hold_majority_guard() -> None:
    """HOLD 대다수(75% 초과) 시 가중투표가 HOLD를 반환하는지 확인한다."""
    # 4개 전략 중 4개 HOLD → HOLD 대다수 → HOLD 반환
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    assert result.confidence == 0.0
    assert "HOLD 대다수" in result.reason
    assert "4/4" in result.reason


def test_weighted_hold_3_of_4_passes_through() -> None:
    """3/4 HOLD + 1 BUY → weighted vote로 진행하여 BUY 반환."""
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.BUY, 0.5),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.BUY


def test_weighted_hold_not_majority_allows_sell() -> None:
    """HOLD가 과반이 아니면 기존 가중투표 로직이 동작한다."""
    # 4개 전략 중 2개 HOLD, 2개 SELL → HOLD 과반 아님 → SELL 반환
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.SELL, 0.8),
            FixedStrategy(SignalType.SELL, 0.6),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.SELL


def test_weighted_hold_majority_meta_populated() -> None:
    """HOLD 대다수 가드 발동 시 vote_meta가 채워지는지 확인한다."""
    # 4개 전략 전부 HOLD → 대다수 가드 발동
    ensemble = EnsembleStrategy(
        [
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
            FixedStrategy(SignalType.HOLD, 0.0),
        ],
        method="weighted",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD
    # analyze()에서 HOLD일 때 meta를 채우므로
    assert "method" in result.meta
    assert result.meta["method"] == "weighted"
    assert len(result.meta["votes"]) == 4


class FixedMetaStrategy(BaseStrategy):
    """Signal.meta에 임의 필드를 넣어 반환하는 테스트용 전략."""

    def __init__(
        self,
        signal_type: SignalType,
        confidence: float,
        meta: dict[str, object],
    ) -> None:
        self._signal = Signal(signal_type=signal_type, confidence=confidence, meta=meta)

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        return self._signal

    @property
    def name(self) -> str:
        return f"meta({self._signal.signal_type.value})"


def test_sub_strategy_meta_merged_into_vote() -> None:
    """하위 전략의 Signal.meta가 vote_meta.votes 항목에 병합되어야 한다.

    기존 shape(strategy/action/confidence)은 유지되고, sub-meta 키가
    그대로 추가되어야 한다. proposal 2026-04-16 observability.
    """
    ensemble = EnsembleStrategy(
        [
            FixedMetaStrategy(
                SignalType.HOLD,
                0.0,
                meta={
                    "series_len": 25,
                    "nan_ratio": 0.0,
                    "last_rsi": 45.2,
                    "guard_triggered": False,
                },
            ),
            FixedMetaStrategy(
                SignalType.HOLD,
                0.0,
                meta={
                    "series_len": 10,
                    "nan_ratio": 0.0,
                    "last_macd": None,
                    "guard_triggered": True,
                    "guard_reason": "insufficient_length",
                },
            ),
        ],
        method="majority",
    )
    result = ensemble.analyze(EMPTY_DF)
    assert result.signal_type == SignalType.HOLD

    votes = result.meta["votes"]
    assert len(votes) == 2

    # 기존 shape 유지
    assert votes[0]["strategy"].startswith("meta")
    assert votes[0]["action"] == "HOLD"
    assert votes[0]["confidence"] == 0.0

    # sub-meta 키가 병합됨
    assert votes[0]["series_len"] == 25
    assert votes[0]["last_rsi"] == 45.2
    assert votes[0]["guard_triggered"] is False

    assert votes[1]["series_len"] == 10
    assert votes[1]["guard_triggered"] is True
    assert votes[1]["guard_reason"] == "insufficient_length"
