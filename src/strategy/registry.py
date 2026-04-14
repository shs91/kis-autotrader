"""전략 레지스트리 — 사용 가능한 전략을 중앙에서 관리한다."""

from __future__ import annotations

from src.strategy.base import BaseStrategy
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class StrategyRegistry:
    """전략을 이름으로 등록하고 조회하는 중앙 저장소. 이름은 소문자 정규화."""

    def __init__(self) -> None:
        """빈 레지스트리를 초기화한다."""
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, name: str, strategy: BaseStrategy) -> None:
        """전략을 등록한다.

        Raises:
            ValueError: 이미 등록된 이름인 경우
        """
        key = name.strip().lower()
        if key in self._strategies:
            raise ValueError(f"이미 등록된 전략입니다: {key}")
        self._strategies[key] = strategy
        logger.info("전략 등록: %s", key)

    def get(self, name: str) -> BaseStrategy:
        """이름으로 전략을 조회한다.

        Raises:
            KeyError: 미등록 전략인 경우
        """
        key = name.strip().lower()
        if key not in self._strategies:
            raise KeyError(f"등록되지 않은 전략입니다: {key}")
        return self._strategies[key]

    def has(self, name: str) -> bool:
        """전략 등록 여부를 확인한다."""
        return name.strip().lower() in self._strategies

    def list_strategies(self) -> list[str]:
        """등록된 전략 이름 목록을 반환한다 (정렬)."""
        return sorted(self._strategies.keys())

    @classmethod
    def create_default(cls) -> StrategyRegistry:
        """기본 전략들이 등록된 레지스트리를 생성한다.

        전략 파라미터는 settings.strategy에서 자동으로 로드된다.
        앙상블 전략은 개별 전략 4종을 하위 전략으로 포함한다.
        """
        from src.config import settings
        from src.strategy.bollinger import BollingerBandStrategy
        from src.strategy.ensemble import EnsembleStrategy
        from src.strategy.macd import MACDStrategy
        from src.strategy.moving_average import MovingAverageStrategy
        from src.strategy.rsi import RSIStrategy

        ma = MovingAverageStrategy()
        rsi = RSIStrategy()
        macd = MACDStrategy()
        bollinger = BollingerBandStrategy()

        registry = cls()
        registry.register("moving_average", ma)
        registry.register("rsi", rsi)
        registry.register("macd", macd)
        registry.register("bollinger", bollinger)
        registry.register(
            "ensemble",
            EnsembleStrategy(
                strategies=[ma, rsi, macd, bollinger],
                method=settings.strategy.ensemble_method,
            ),
        )
        return registry
