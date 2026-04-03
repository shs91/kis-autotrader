# T3-3: 다중 전략 동시 운영 — 상세 설계

> 작성일: 2026-04-03
> 상태: Design
> Plan 문서: `docs/01-plan/features/T3-3-multi-strategy.plan.md`

---

## 1. 파일 목록

### 신규 파일

| 파일 | 설명 |
|------|------|
| `src/strategy/registry.py` | StrategyRegistry — 전략 등록/조회 |
| `src/strategy/selector.py` | StrategySelector — 종목-전략 매핑 |
| `src/strategy/ensemble.py` | EnsembleStrategy — 투표 앙상블 |
| `tests/test_strategy/test_registry.py` | 레지스트리 테스트 |
| `tests/test_strategy/test_selector.py` | 셀렉터 테스트 |
| `tests/test_strategy/test_ensemble.py` | 앙상블 테스트 |

### 수정 파일

| 파일 | 변경 범위 |
|------|-----------|
| `src/engine.py` | `__init__`, `_process_stock`, `_screen_stocks` — selector 통합 |
| `src/config.py` | `StrategyConfig` dataclass 추가 |
| `src/strategy/__init__.py` | 신규 클래스 re-export |

### 변경 없음

| 파일 |
|------|
| `src/strategy/base.py` |
| `src/strategy/moving_average.py` |
| `src/strategy/rsi.py` |

---

## 2. 상세 클래스 설계

### 2.1 `src/strategy/registry.py`

```python
"""전략 레지스트리 — 사용 가능한 전략을 중앙에서 관리한다."""

from __future__ import annotations

from src.strategy.base import BaseStrategy
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class StrategyRegistry:
    """전략을 이름으로 등록하고 조회하는 중앙 저장소.

    전략 이름은 소문자로 정규화된다.
    """

    def __init__(self) -> None:
        """빈 레지스트리를 초기화한다."""
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, name: str, strategy: BaseStrategy) -> None:
        """전략을 등록한다.

        Args:
            name: 전략 이름 (소문자 정규화)
            strategy: BaseStrategy 구현체

        Raises:
            ValueError: 이미 등록된 이름인 경우
        """

    def get(self, name: str) -> BaseStrategy:
        """이름으로 전략을 조회한다.

        Args:
            name: 전략 이름

        Returns:
            등록된 전략

        Raises:
            KeyError: 미등록 전략인 경우
        """

    def has(self, name: str) -> bool:
        """전략 등록 여부를 확인한다."""

    def list_strategies(self) -> list[str]:
        """등록된 전략 이름 목록을 반환한다 (정렬)."""

    @classmethod
    def create_default(cls) -> StrategyRegistry:
        """기본 전략들이 등록된 레지스트리를 생성한다.

        등록 목록:
        - "moving_average": MovingAverageStrategy()
        - "rsi": RSIStrategy()
        """
```

**이름 정규화**: `register("Moving_Average", ...)` → `"moving_average"` 로 저장.
`get("MOVING_AVERAGE")` → `"moving_average"` 로 조회.

---

### 2.2 `src/strategy/selector.py`

```python
"""전략 셀렉터 — 종목별 전략 배정 관리."""

from __future__ import annotations

from dataclasses import dataclass

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
        default_strategy: str = "moving_average",
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

    def get_strategy(self, stock_code: str) -> BaseStrategy:
        """종목에 배정된 전략을 반환한다.

        Args:
            stock_code: 종목코드

        Returns:
            배정된 전략. 매핑 없으면 기본 전략.
        """

    def set_mapping(self, stock_code: str, strategy_name: str) -> None:
        """종목-전략 매핑을 설정/변경한다.

        Args:
            stock_code: 종목코드
            strategy_name: 전략 이름

        Raises:
            KeyError: strategy_name이 레지스트리에 없는 경우
        """

    def remove_mapping(self, stock_code: str) -> None:
        """종목 매핑을 제거한다 (기본 전략으로 복귀).

        Args:
            stock_code: 종목코드
        """

    def get_all_mappings(self) -> dict[str, str]:
        """전체 종목-전략 매핑을 반환한다. {종목코드: 전략이름}"""

    @property
    def default_strategy_name(self) -> str:
        """기본 전략 이름을 반환한다."""

    @classmethod
    def from_config(cls, registry: StrategyRegistry) -> StrategySelector:
        """환경변수에서 매핑을 로드하여 생성한다.

        환경변수:
        - STRATEGY_DEFAULT: 기본 전략 이름 (기본: "moving_average")
        - STRATEGY_MAPPINGS: 쉼표 구분 "종목코드:전략이름" (예: "005930:rsi,000660:ensemble")

        Args:
            registry: 전략 레지스트리

        Returns:
            설정 기반 StrategySelector
        """
```

**내부 저장소**: `self._mappings: dict[str, str]` — `{종목코드: 전략이름}`
`get_strategy()`가 호출될 때마다 `registry.get()`으로 실제 전략 인스턴스를 반환.

---

### 2.3 `src/strategy/ensemble.py`

```python
"""앙상블 전략 — 복수 전략의 시그널을 투표로 통합한다."""

from __future__ import annotations

from collections import Counter

import pandas as pd

from src.strategy.base import BaseStrategy, Signal, SignalType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 투표 방식
MAJORITY: str = "majority"
WEIGHTED: str = "weighted"


class EnsembleStrategy(BaseStrategy):
    """복수 전략의 시그널을 투표로 통합하는 앙상블 전략.

    BaseStrategy를 상속하므로 단일 전략과 동일하게 사용 가능.
    StrategyRegistry에 "ensemble"로 등록할 수 있다.
    """

    def __init__(
        self,
        strategies: list[BaseStrategy],
        method: str = MAJORITY,
    ) -> None:
        """앙상블 전략을 초기화한다.

        Args:
            strategies: 하위 전략 목록 (최소 2개)
            method: 투표 방식 ("majority" 또는 "weighted")

        Raises:
            ValueError: strategies가 2개 미만이거나 method가 올바르지 않을 때
        """

    @property
    def name(self) -> str:
        """앙상블 전략 이름을 반환한다.

        형식: "앙상블(이동평균교차(5/20)+RSI(14))"
        """

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """모든 하위 전략의 시그널을 수집하여 투표로 결정한다.

        majority 방식:
        1. 각 전략의 analyze() 호출
        2. HOLD를 제외한 시그널에서 다수결
        3. 동수면 HOLD
        4. 신뢰도 = 해당 시그널들의 confidence 평균

        weighted 방식:
        1. 각 전략의 analyze() 호출
        2. BUY 가중합 = sum(confidence for BUY signals)
        3. SELL 가중합 = sum(confidence for SELL signals)
        4. 최대 가중합 방향 선택, 신뢰도 = 가중합 / 전략 수

        Args:
            market_data: 시장 데이터 DataFrame

        Returns:
            투표 결과 시그널
        """

    def _majority_vote(self, signals: list[Signal]) -> Signal:
        """다수결 투표를 수행한다.

        Args:
            signals: 하위 전략 시그널 목록

        Returns:
            다수결 결과 시그널
        """

    def _weighted_vote(self, signals: list[Signal]) -> Signal:
        """가중 투표를 수행한다.

        Args:
            signals: 하위 전략 시그널 목록

        Returns:
            가중 투표 결과 시그널
        """
```

**투표 로직 상세 (majority)**:
```
signals = [BUY(0.7), SELL(0.3), BUY(0.5)]

HOLD 제외 후:
  BUY: 2건, SELL: 1건
  → BUY 승리
  → confidence = avg(0.7, 0.5) = 0.6
  → reason = "앙상블 다수결: BUY 2/3 (이동평균교차, RSI)"
```

**투표 로직 상세 (weighted)**:
```
signals = [BUY(0.7), SELL(0.8), BUY(0.3)]

BUY 가중합 = 0.7 + 0.3 = 1.0
SELL 가중합 = 0.8
→ BUY 승리 (1.0 > 0.8)
→ confidence = 1.0 / 3 = 0.33
→ reason = "앙상블 가중투표: BUY 1.00 vs SELL 0.80"
```

**동수/무시그널 처리**:
- majority에서 BUY=SELL 동수 → HOLD(confidence=0.0)
- 모든 전략이 HOLD → HOLD(confidence=0.0)

---

### 2.4 `src/config.py` 수정

```python
@dataclass(frozen=True)
class StrategyConfig:
    """전략 관련 설정."""

    default: str = field(
        default_factory=lambda: _env("STRATEGY_DEFAULT", "moving_average")
    )
    mappings_raw: str = field(
        default_factory=lambda: _env("STRATEGY_MAPPINGS", "")
    )

    def parse_mappings(self) -> dict[str, str]:
        """STRATEGY_MAPPINGS 환경변수를 파싱한다.

        형식: "005930:rsi,000660:ensemble"

        Returns:
            {종목코드: 전략이름} 딕셔너리
        """
        if not self.mappings_raw:
            return {}
        result: dict[str, str] = {}
        for pair in self.mappings_raw.split(","):
            pair = pair.strip()
            if ":" in pair:
                code, strategy = pair.split(":", 1)
                result[code.strip()] = strategy.strip()
        return result
```

`Settings` 클래스에 추가:
```python
class Settings:
    ...
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
```

---

### 2.5 `src/engine.py` 수정

**변경 1: `__init__`**

```python
# 현재
def __init__(
    self,
    watchlist: list[str] | None = None,
    strategy: BaseStrategy | None = None,
) -> None:
    ...
    self._strategy = strategy or MovingAverageStrategy()

# 변경 후
def __init__(
    self,
    watchlist: list[str] | None = None,
    strategy: BaseStrategy | None = None,
    selector: StrategySelector | None = None,
) -> None:
    ...
    if selector is not None:
        self._selector = selector
    elif strategy is not None:
        # 하위 호환: 단일 전략 파라미터 → 모든 종목에 동일 전략
        registry = StrategyRegistry()
        registry.register("custom", strategy)
        self._selector = StrategySelector(registry, default_strategy="custom")
    else:
        # 기본: 설정 파일 기반
        registry = StrategyRegistry.create_default()
        self._selector = StrategySelector.from_config(registry)
```

**변경 2: `_process_stock`**

```python
# 현재 (4곳에서 self._strategy.analyze() 호출)
signal = self._strategy.analyze(df)

# 변경 후
strategy = self._selector.get_strategy(stock_code)
signal = strategy.analyze(df)
```

**변경 3: `_screen_stocks`**

```python
# 현재
signal = self._strategy.analyze(df)

# 변경 후
strategy = self._selector.get_strategy(item.stock_code)
signal = strategy.analyze(df)
```

**변경 4: 로그 메시지에 전략 이름 추가**

```python
logger.info(
    "[%s %s] 전략=%s, 보유=%s, 시그널=%s, ...",
    stock_code, current.stock_name,
    strategy.name,   # 추가
    "Y" if is_held else "N",
    signal.signal_type.value,
    ...
)
```

---

### 2.6 `src/strategy/__init__.py`

```python
"""매매 전략 패키지."""

from src.strategy.base import BaseStrategy, Signal, SignalType
from src.strategy.ensemble import EnsembleStrategy
from src.strategy.moving_average import MovingAverageStrategy
from src.strategy.registry import StrategyRegistry
from src.strategy.rsi import RSIStrategy
from src.strategy.selector import StrategySelector, StockStrategyMapping

__all__ = [
    "BaseStrategy",
    "EnsembleStrategy",
    "MovingAverageStrategy",
    "RSIStrategy",
    "Signal",
    "SignalType",
    "StockStrategyMapping",
    "StrategyRegistry",
    "StrategySelector",
]
```

---

## 3. 데이터 흐름 상세

```
TradingEngine.__init__()
│
├─ selector 파라미터 → 직접 사용
├─ strategy 파라미터 → StrategySelector로 래핑 (하위 호환)
└─ 둘 다 없음 → StrategyRegistry.create_default() + from_config()
     │
     ▼
TradingEngine._process_stock(stock_code)
     │
     ├─ self._selector.get_strategy(stock_code)
     │     │
     │     ├─ _mappings에 stock_code 있음 → registry.get(매핑된 전략)
     │     └─ 없음 → registry.get(default_strategy)
     │
     ▼
  strategy.analyze(df) → Signal
     │
     ├─ 일반 전략: MovingAverageStrategy / RSIStrategy
     └─ 앙상블: EnsembleStrategy
              │
              ├─ sub_strategy_1.analyze(df) → Signal
              ├─ sub_strategy_2.analyze(df) → Signal
              └─ 투표 → 최종 Signal
```

---

## 4. 에러 처리

| 상황 | 처리 |
|------|------|
| 미등록 전략 이름으로 register | `ValueError` |
| 미등록 전략 이름으로 get | `KeyError` |
| 레지스트리에 없는 기본 전략 | `KeyError` (StrategySelector.__init__) |
| 레지스트리에 없는 매핑 전략 | `KeyError` (set_mapping) |
| 앙상블에 전략 1개 미만 | `ValueError` |
| 잘못된 투표 방식 | `ValueError` |
| STRATEGY_MAPPINGS 잘못된 형식 | 해당 항목 무시 + 로그 경고 |

---

## 5. 구현 순서

| 순서 | 파일 | 의존성 | 테스트 |
|------|------|--------|--------|
| 1 | `src/strategy/registry.py` | base.py | `test_registry.py` |
| 2 | `src/strategy/ensemble.py` | base.py | `test_ensemble.py` |
| 3 | `src/config.py` (StrategyConfig 추가) | - | - |
| 4 | `src/strategy/selector.py` | registry, config | `test_selector.py` |
| 5 | `src/engine.py` 수정 | selector | 기존 테스트 통과 확인 |
| 6 | `src/strategy/__init__.py` | 전체 | - |

---

## 6. 테스트 설계

### 6.1 `test_registry.py`

| 테스트 | 검증 |
|--------|------|
| `test_register_and_get` | 등록 후 조회 성공 |
| `test_register_duplicate` | 중복 이름 등록 → ValueError |
| `test_get_unknown` | 미등록 이름 → KeyError |
| `test_name_normalization` | 대소문자 무시 등록/조회 |
| `test_list_strategies` | 등록된 이름 목록 반환 (정렬) |
| `test_has` | 존재/미존재 확인 |
| `test_create_default` | moving_average, rsi 기본 등록 확인 |

### 6.2 `test_ensemble.py`

| 테스트 | 검증 |
|--------|------|
| `test_majority_buy_wins` | BUY 2 vs SELL 1 → BUY |
| `test_majority_sell_wins` | BUY 1 vs SELL 2 → SELL |
| `test_majority_tie_hold` | BUY 1 vs SELL 1 → HOLD |
| `test_majority_all_hold` | 모두 HOLD → HOLD |
| `test_majority_confidence_avg` | BUY(0.7)+BUY(0.5) → confidence=0.6 |
| `test_weighted_buy_wins` | BUY 가중합 > SELL 가중합 → BUY |
| `test_weighted_sell_wins` | SELL 가중합 > BUY 가중합 → SELL |
| `test_init_one_strategy` | 1개 전략 → ValueError |
| `test_init_invalid_method` | 잘못된 method → ValueError |
| `test_name_format` | 이름 형식 검증 |

### 6.3 `test_selector.py`

| 테스트 | 검증 |
|--------|------|
| `test_get_mapped_strategy` | 매핑된 종목 → 해당 전략 반환 |
| `test_get_default_strategy` | 매핑 없는 종목 → 기본 전략 반환 |
| `test_set_mapping` | 매핑 설정 후 get_strategy 확인 |
| `test_set_mapping_unknown` | 미등록 전략 매핑 → KeyError |
| `test_remove_mapping` | 매핑 제거 → 기본 전략 복귀 |
| `test_get_all_mappings` | 전체 매핑 딕셔너리 반환 |
| `test_from_config` | 환경변수 기반 생성 (monkeypatch) |
| `test_default_unknown` | 기본 전략이 레지스트리에 없음 → KeyError |

---

## 7. 하위 호환성 보장

### 기존 코드 동작 보존

```python
# 기존 방식 — 여전히 동작해야 함
engine = TradingEngine(strategy=MovingAverageStrategy())

# 새로운 방식 — selector 직접 전달
engine = TradingEngine(selector=selector)

# 기본 방식 — 설정 파일에서 로드
engine = TradingEngine()
```

### BacktestEngine 호환

`BacktestEngine`은 `BaseStrategy`를 받으므로 변경 없음.
`EnsembleStrategy`는 `BaseStrategy`를 상속하므로 그대로 백테스트 가능.

```python
ensemble = EnsembleStrategy([MovingAverageStrategy(), RSIStrategy()])
result = BacktestEngine(strategy=ensemble).run(data, "005930")
```
