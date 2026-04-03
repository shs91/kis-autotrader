# T3-3: 다중 전략 동시 운영

> 작성일: 2026-04-03
> 상태: Plan
> 로드맵 ID: T3-3
> 의존성: T3-2 (백테스팅 프레임워크) — 전략 성능 비교/검증 용도

---

## 1. 현재 상태 분석

### 현재 한계
- `TradingEngine`은 **단일 전략**(`self._strategy`)만 보유
- 모든 종목에 동일 전략(`MovingAverageStrategy`)을 적용
- 전략 교체 시 엔진 재시작 필요
- 시장 상황(추세/횡보)에 따른 전략 전환 불가

### 사용 가능한 전략 (현재 구현됨)
| 전략 | 파일 | 특성 |
|------|------|------|
| `MovingAverageStrategy` | `moving_average.py` | 추세 추종, 골든/데드크로스 |
| `RSIStrategy` | `rsi.py` | 역추세(평균회귀), 과매도/과매수 |

---

## 2. 목적

종목별·상황별로 **다른 전략을 동시에 운영**하여 매매 성과를 개선한다.
- 종목 A → 이동평균 전략, 종목 B → RSI 전략
- 백테스트 결과 기반 최적 전략 배정
- 운영 중 전략 전환 가능 (엔진 재시작 없이)

---

## 3. 핵심 요구사항

### 3.1 필수 (Must Have)

| ID | 요구사항 | 설명 |
|----|----------|------|
| R1 | 전략 레지스트리 | 사용 가능한 전략을 이름으로 등록/조회하는 중앙 저장소 |
| R2 | 종목-전략 매핑 | 종목별로 다른 전략을 배정하는 매핑 테이블 |
| R3 | 기본 전략 (fallback) | 매핑에 없는 종목은 기본 전략 사용 |
| R4 | 투표 기반 앙상블 | 복수 전략의 시그널을 투표로 통합하는 모드 |
| R5 | 엔진 통합 | `TradingEngine`이 종목별로 지정된 전략을 호출하도록 수정 |
| R6 | 설정 기반 구성 | `.env` 또는 JSON 설정 파일로 종목-전략 매핑 관리 |

### 3.2 선택 (Nice to Have)

| ID | 요구사항 | 설명 |
|----|----------|------|
| N1 | 백테스트 기반 자동 배정 | T3-2 백테스트 결과 최고 수익률 전략을 자동 배정 |
| N2 | 시장 상태 감지 | 추세/횡보 구간 판단 후 전략 자동 전환 |
| N3 | 전략 성과 모니터링 | 운영 중 전략별 수익률 추적, 저성과 전략 자동 교체 |

---

## 4. 아키텍처

### 4.1 모듈 구조

```
src/strategy/
├── __init__.py            # (수정) 공개 API 확장
├── base.py                # (변경 없음) BaseStrategy, Signal
├── moving_average.py      # (변경 없음) MovingAverageStrategy
├── rsi.py                 # (변경 없음) RSIStrategy
├── registry.py            # (신규) StrategyRegistry — 전략 등록/조회
├── selector.py            # (신규) StrategySelector — 종목-전략 매핑
└── ensemble.py            # (신규) EnsembleStrategy — 투표 기반 앙상블
```

### 4.2 데이터 흐름

```
TradingEngine._process_stock(stock_code)
     ↓
StrategySelector.get_strategy(stock_code)
     ↓
  ┌─ 매핑 존재 → 해당 전략 반환
  └─ 매핑 없음 → 기본 전략 반환
     ↓
strategy.analyze(df) → Signal
     ↓
(이후 기존과 동일: 리스크 → 주문)
```

### 4.3 앙상블 전략 흐름

```
EnsembleStrategy.analyze(df)
     ↓
  strategy_1.analyze(df) → Signal(BUY, 0.7)
  strategy_2.analyze(df) → Signal(SELL, 0.3)
  strategy_3.analyze(df) → Signal(BUY, 0.5)
     ↓
  투표: BUY=2, SELL=1 → BUY (가중 신뢰도 = 평균)
     ↓
  Signal(BUY, confidence=0.6)
```

---

## 5. 주요 클래스 설계

### 5.1 StrategyRegistry

```python
class StrategyRegistry:
    """전략을 이름으로 등록하고 조회하는 중앙 저장소."""

    def register(self, name: str, strategy: BaseStrategy) -> None:
        """전략을 등록한다."""

    def get(self, name: str) -> BaseStrategy:
        """이름으로 전략을 조회한다."""

    def list_strategies(self) -> list[str]:
        """등록된 전략 이름 목록을 반환한다."""

    @classmethod
    def create_default(cls) -> StrategyRegistry:
        """기본 전략들이 등록된 레지스트리를 생성한다."""
        # MovingAverageStrategy, RSIStrategy 기본 등록
```

### 5.2 StrategySelector

```python
@dataclass
class StockStrategyMapping:
    """종목-전략 매핑 항목."""
    stock_code: str
    strategy_name: str

class StrategySelector:
    """종목별 전략을 선택하는 매핑 관리자."""

    def __init__(
        self,
        registry: StrategyRegistry,
        default_strategy: str = "moving_average",
        mappings: list[StockStrategyMapping] | None = None,
    ) -> None: ...

    def get_strategy(self, stock_code: str) -> BaseStrategy:
        """종목에 배정된 전략을 반환한다. 매핑 없으면 기본 전략."""

    def set_mapping(self, stock_code: str, strategy_name: str) -> None:
        """종목-전략 매핑을 설정/변경한다 (실행 중 전환 가능)."""

    def remove_mapping(self, stock_code: str) -> None:
        """종목 매핑을 제거한다 (기본 전략으로 복귀)."""

    def get_all_mappings(self) -> dict[str, str]:
        """전체 종목-전략 매핑을 반환한다."""

    @classmethod
    def from_config(cls, registry: StrategyRegistry) -> StrategySelector:
        """설정 파일에서 매핑을 로드하여 생성한다."""
```

### 5.3 EnsembleStrategy

```python
class EnsembleStrategy(BaseStrategy):
    """복수 전략의 시그널을 투표로 통합하는 앙상블 전략.

    BaseStrategy를 상속하므로 다른 전략과 동일하게 사용 가능.
    """

    def __init__(
        self,
        strategies: list[BaseStrategy],
        method: str = "majority",  # "majority" | "weighted"
    ) -> None: ...

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """모든 하위 전략의 시그널을 수집하여 투표로 결정한다."""

    @property
    def name(self) -> str:
        """앙상블 전략 이름을 반환한다."""
```

---

## 6. 엔진 수정 범위

### 6.1 `TradingEngine.__init__` 변경

```python
# 현재 (단일 전략)
self._strategy = strategy or MovingAverageStrategy()

# 변경 후 (다중 전략)
self._registry = StrategyRegistry.create_default()
self._selector = StrategySelector.from_config(self._registry)
```

### 6.2 `TradingEngine._process_stock` 변경

```python
# 현재
signal = self._strategy.analyze(df)

# 변경 후
strategy = self._selector.get_strategy(stock_code)
signal = strategy.analyze(df)
```

### 6.3 영향 범위

| 파일 | 변경 내용 | 크기 |
|------|-----------|------|
| `src/engine.py` | `__init__`, `_process_stock` 수정 | 소 (10줄 이내) |
| `src/config.py` | `StrategyConfig` 추가 또는 JSON 설정 경로 | 소 |
| `src/strategy/__init__.py` | 신규 클래스 re-export | 소 |

**기존 전략 파일(base.py, moving_average.py, rsi.py)은 변경 없음.**

---

## 7. 설정 형식

### 7.1 환경변수 방식 (간단)
```env
# .env
STRATEGY_DEFAULT=moving_average
STRATEGY_MAPPINGS=005930:rsi,000660:ensemble,035420:moving_average
```

### 7.2 JSON 파일 방식 (상세)
```json
// config/strategies.json
{
  "default": "moving_average",
  "mappings": {
    "005930": "rsi",
    "000660": {
      "type": "ensemble",
      "strategies": ["moving_average", "rsi"]
    }
  }
}
```

---

## 8. 구현 순서

| 순서 | 파일 | 내용 | 의존성 |
|------|------|------|--------|
| 1 | `src/strategy/registry.py` | StrategyRegistry | base.py |
| 2 | `src/strategy/selector.py` | StrategySelector + 설정 로드 | registry |
| 3 | `src/strategy/ensemble.py` | EnsembleStrategy | base.py |
| 4 | `src/engine.py` | 엔진 수정 (selector 통합) | selector |
| 5 | `src/strategy/__init__.py` | re-export 확장 | 전체 |
| 6 | `tests/test_strategy/` | 단위 테스트 | 전체 |

---

## 9. 검증 기준

- [ ] 종목별로 다른 전략이 배정되어 독립적으로 시그널 생성
- [ ] 매핑에 없는 종목은 기본 전략(MovingAverage)으로 처리
- [ ] 앙상블 전략이 복수 시그널을 투표로 통합
- [ ] 운영 중 `set_mapping()`으로 전략 전환 가능
- [ ] T3-2 백테스트 엔진에서도 다중 전략 사용 가능
- [ ] 기존 단일 전략 모드와 하위 호환 (strategy 파라미터 전달 시 기존 동작)
- [ ] `pytest tests/test_strategy/` 전체 통과
- [ ] `ruff check src/strategy/` + `mypy src/strategy/` 통과

---

## 10. 리스크 및 제약사항

| 리스크 | 대응 |
|--------|------|
| 전략 수 증가 → API 호출량 증가 | 앙상블 전략은 동일 데이터를 재사용 (API 호출 증가 없음) |
| 종목-전략 매핑 관리 복잡도 | 기본 전략 fallback으로 관리 부담 최소화 |
| 엔진 수정 시 기존 기능 퇴행 | `strategy` 파라미터 하위 호환 유지 |
| 전략 간 상충 시그널 | 앙상블 투표로 해결, 과반 없으면 HOLD |

---

## 11. 사용 예시 (완성 후)

```python
# 1. 종목별 전략 배정
registry = StrategyRegistry.create_default()
selector = StrategySelector(
    registry=registry,
    default_strategy="moving_average",
)
selector.set_mapping("005930", "rsi")        # 삼성전자 → RSI
selector.set_mapping("000660", "ensemble")   # SK하이닉스 → 앙상블

engine = TradingEngine(selector=selector)

# 2. 백테스트에서 전략 비교
from src.backtest import BacktestEngine, DataLoader
loader = DataLoader()
data = loader.from_csv("data/005930.csv")

for strategy_name in registry.list_strategies():
    strategy = registry.get(strategy_name)
    result = BacktestEngine(strategy=strategy).run(data, "005930")
    print(f"{strategy_name}: {result.total_return:+.2f}%")
```
