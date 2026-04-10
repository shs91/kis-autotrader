"""전략 셀렉터 — 종목별 전략 배정 관리."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.strategy.base import BaseStrategy
from src.strategy.registry import StrategyRegistry
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class StockStrategyMapping:
    """종목-전략 매핑 항목."""

    stock_code: str
    strategy_name: str


class StrategySelector:
    """종목별 전략을 선택하는 매핑 관리자.

    매핑에 없는 종목은 기본 전략을 반환한다.
    """

    def __init__(
        self,
        registry: StrategyRegistry,
        default_strategy: str = "ensemble",
        mappings: list[StockStrategyMapping] | None = None,
    ) -> None:
        """셀렉터를 초기화한다.

        Args:
            registry: 전략 레지스트리
            default_strategy: 기본 전략 이름
            mappings: 초기 종목-전략 매핑 목록

        Raises:
            KeyError: default_strategy가 레지스트리에 없는 경우
        """
        self._registry = registry
        self._default_name = default_strategy.strip().lower()

        # 기본 전략이 레지스트리에 존재하는지 검증
        self._registry.get(self._default_name)

        self._mappings: dict[str, str] = {}
        if mappings:
            for m in mappings:
                self._mappings[m.stock_code] = m.strategy_name.strip().lower()

        logger.info(
            "전략 셀렉터 초기화: 기본=%s, 매핑=%d건",
            self._default_name,
            len(self._mappings),
        )

    def get_strategy(self, stock_code: str) -> BaseStrategy:
        """종목에 배정된 전략을 반환한다.

        Args:
            stock_code: 종목코드

        Returns:
            배정된 전략. 매핑 없으면 기본 전략.
        """
        strategy_name = self._mappings.get(stock_code, self._default_name)
        return self._registry.get(strategy_name)

    def set_mapping(self, stock_code: str, strategy_name: str) -> None:
        """종목-전략 매핑을 설정/변경한다.

        Args:
            stock_code: 종목코드
            strategy_name: 전략 이름

        Raises:
            KeyError: strategy_name이 레지스트리에 없는 경우
        """
        name = strategy_name.strip().lower()
        # 레지스트리에 존재하는지 검증
        self._registry.get(name)
        self._mappings[stock_code] = name
        logger.info("전략 매핑 설정: %s → %s", stock_code, name)

    def remove_mapping(self, stock_code: str) -> None:
        """종목 매핑을 제거한다 (기본 전략으로 복귀).

        Args:
            stock_code: 종목코드
        """
        if stock_code in self._mappings:
            del self._mappings[stock_code]
            logger.info("전략 매핑 제거: %s → 기본(%s)", stock_code, self._default_name)

    def get_all_mappings(self) -> dict[str, str]:
        """전체 종목-전략 매핑을 반환한다."""
        return dict(self._mappings)

    @property
    def default_strategy_name(self) -> str:
        """기본 전략 이름을 반환한다."""
        return self._default_name

    @classmethod
    def from_config(cls, registry: StrategyRegistry) -> StrategySelector:
        """환경변수에서 매핑을 로드하여 생성한다.

        환경변수:
        - STRATEGY_DEFAULT: 기본 전략 이름 (기본: "moving_average")
        - STRATEGY_MAPPINGS: "종목코드:전략이름" 쉼표 구분

        Args:
            registry: 전략 레지스트리

        Returns:
            설정 기반 StrategySelector
        """
        config = settings.strategy
        parsed = config.parse_mappings()

        mappings: list[StockStrategyMapping] = []
        for code, name in parsed.items():
            if registry.has(name):
                mappings.append(StockStrategyMapping(stock_code=code, strategy_name=name))
            else:
                logger.warning(
                    "설정의 전략 '%s'가 레지스트리에 없습니다: %s", name, code,
                )

        default = config.default
        if not registry.has(default):
            logger.warning(
                "기본 전략 '%s'가 레지스트리에 없습니다. 'ensemble'로 대체.",
                default,
            )
            default = "ensemble"

        return cls(registry=registry, default_strategy=default, mappings=mappings)
