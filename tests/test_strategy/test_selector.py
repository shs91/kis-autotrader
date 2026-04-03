"""StrategySelector 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.config import StrategyConfig
from src.strategy.base import BaseStrategy, Signal, SignalType
from src.strategy.registry import StrategyRegistry
from src.strategy.selector import StrategySelector


class StubStrategy(BaseStrategy):
    """테스트용 스텁 전략."""

    def __init__(self, n: str) -> None:
        self._name = n

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        return Signal(SignalType.HOLD, 0.0)

    @property
    def name(self) -> str:
        return self._name


@pytest.fixture
def registry() -> StrategyRegistry:
    r = StrategyRegistry()
    r.register("alpha", StubStrategy("alpha"))
    r.register("beta", StubStrategy("beta"))
    return r


class TestStrategySelector:
    """StrategySelector 테스트 모음."""

    def test_get_mapped_strategy(self, registry: StrategyRegistry) -> None:
        """매핑된 종목에 대해 지정된 전략을 반환한다."""
        selector = StrategySelector(registry, default_strategy="alpha")
        selector.set_mapping("005930", "alpha")
        strategy = selector.get_strategy("005930")
        assert strategy.name == "alpha"

    def test_get_default_strategy(self, registry: StrategyRegistry) -> None:
        """매핑되지 않은 종목에 대해 기본 전략을 반환한다."""
        selector = StrategySelector(registry, default_strategy="alpha")
        strategy = selector.get_strategy("999999")
        assert strategy.name == "alpha"

    def test_set_mapping(self, registry: StrategyRegistry) -> None:
        """set_mapping으로 설정한 매핑이 get_strategy에 반영된다."""
        selector = StrategySelector(registry, default_strategy="alpha")
        selector.set_mapping("005930", "beta")
        strategy = selector.get_strategy("005930")
        assert strategy.name == "beta"

    def test_set_mapping_unknown(self, registry: StrategyRegistry) -> None:
        """레지스트리에 없는 전략으로 매핑하면 KeyError가 발생한다."""
        selector = StrategySelector(registry, default_strategy="alpha")
        with pytest.raises(KeyError):
            selector.set_mapping("005930", "unknown_strategy")

    def test_remove_mapping(self, registry: StrategyRegistry) -> None:
        """매핑 제거 후 기본 전략으로 복귀한다."""
        selector = StrategySelector(registry, default_strategy="alpha")
        selector.set_mapping("005930", "beta")
        selector.remove_mapping("005930")
        strategy = selector.get_strategy("005930")
        assert strategy.name == "alpha"

    def test_get_all_mappings(self, registry: StrategyRegistry) -> None:
        """전체 매핑 딕셔너리를 반환한다."""
        selector = StrategySelector(registry, default_strategy="alpha")
        selector.set_mapping("005930", "beta")
        selector.set_mapping("000660", "alpha")
        mappings = selector.get_all_mappings()
        assert mappings == {"005930": "beta", "000660": "alpha"}

    def test_default_strategy_name(self, registry: StrategyRegistry) -> None:
        """default_strategy_name 프로퍼티가 올바른 이름을 반환한다."""
        selector = StrategySelector(registry, default_strategy="beta")
        assert selector.default_strategy_name == "beta"

    def test_default_unknown(self, registry: StrategyRegistry) -> None:
        """레지스트리에 없는 기본 전략으로 초기화하면 KeyError가 발생한다."""
        with pytest.raises(KeyError):
            StrategySelector(registry, default_strategy="nonexistent")

    def test_from_config(
        self, registry: StrategyRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """from_config가 환경변수 기반으로 셀렉터를 올바르게 생성한다."""
        from src.config import Settings

        mock_config = StrategyConfig(default="alpha", mappings_raw="005930:beta")
        mock_settings = Settings(strategy=mock_config)
        monkeypatch.setattr("src.strategy.selector.settings", mock_settings)
        selector = StrategySelector.from_config(registry)
        assert selector.default_strategy_name == "alpha"
        assert selector.get_strategy("005930").name == "beta"
