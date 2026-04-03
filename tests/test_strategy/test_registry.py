"""StrategyRegistry 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategy.base import BaseStrategy, Signal, SignalType
from src.strategy.registry import StrategyRegistry


class StubStrategy(BaseStrategy):
    """테스트용 스텁 전략."""

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        return Signal(SignalType.HOLD, 0.0)

    @property
    def name(self) -> str:
        return "stub"


class StubStrategy2(BaseStrategy):
    """두 번째 테스트용 스텁 전략."""

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        return Signal(SignalType.BUY, 0.5)

    @property
    def name(self) -> str:
        return "stub2"


class TestStrategyRegistry:
    """StrategyRegistry 테스트 스위트."""

    def test_register_and_get(self) -> None:
        """등록한 전략을 동일 이름으로 조회할 수 있어야 한다."""
        registry = StrategyRegistry()
        stub = StubStrategy()
        registry.register("my_strategy", stub)

        result = registry.get("my_strategy")
        assert result is stub

    def test_register_duplicate(self) -> None:
        """같은 이름으로 두 번 등록하면 ValueError가 발생해야 한다."""
        registry = StrategyRegistry()
        registry.register("dup", StubStrategy())

        with pytest.raises(ValueError, match="이미 등록된 전략입니다"):
            registry.register("dup", StubStrategy2())

    def test_get_unknown(self) -> None:
        """등록되지 않은 이름 조회 시 KeyError가 발생해야 한다."""
        registry = StrategyRegistry()

        with pytest.raises(KeyError, match="등록되지 않은 전략입니다"):
            registry.get("nonexistent")

    def test_name_normalization(self) -> None:
        """이름은 대소문자 무시하고 정규화되어야 한다."""
        registry = StrategyRegistry()
        stub = StubStrategy()
        registry.register("Moving_Average", stub)

        result = registry.get("MOVING_AVERAGE")
        assert result is stub

    def test_list_strategies(self) -> None:
        """등록된 전략 이름을 정렬된 리스트로 반환해야 한다."""
        registry = StrategyRegistry()
        registry.register("zebra", StubStrategy())
        registry.register("alpha", StubStrategy2())

        result = registry.list_strategies()
        assert result == ["alpha", "zebra"]

    def test_has(self) -> None:
        """등록된 전략은 True, 미등록은 False를 반환해야 한다."""
        registry = StrategyRegistry()
        registry.register("exists", StubStrategy())

        assert registry.has("exists") is True
        assert registry.has("unknown") is False

    def test_create_default(self) -> None:
        """기본 레지스트리에 moving_average와 rsi가 등록되어 있어야 한다."""
        registry = StrategyRegistry.create_default()

        assert registry.has("moving_average")
        assert registry.has("rsi")
        assert "moving_average" in registry.list_strategies()
        assert "rsi" in registry.list_strategies()
