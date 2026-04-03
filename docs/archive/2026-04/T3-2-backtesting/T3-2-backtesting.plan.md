# T3-2: 백테스팅 프레임워크

> 작성일: 2026-04-03
> 상태: Plan
> 로드맵 ID: T3-2
> 의존성: 없음 (T3-3 다중전략이 이 기능에 의존)

---

## 1. 목적

현재 시스템은 실시간 매매만 가능하며, 전략의 성능을 사전에 검증할 방법이 없다.
백테스팅 프레임워크를 도입하여 **과거 데이터 기반 전략 시뮬레이션**을 수행하고,
전략 파라미터 최적화 및 신규 전략 검증을 가능하게 한다.

---

## 2. 핵심 요구사항

### 2.1 필수 (Must Have)

| ID | 요구사항 | 설명 |
|----|----------|------|
| R1 | 기존 전략 재사용 | `BaseStrategy.analyze()` 인터페이스를 그대로 사용하여 실전/백테스트 코드 분기 없음 |
| R2 | 과거 일봉 데이터 로드 | KIS API `get_daily_price()` 또는 로컬 CSV/DB에서 일봉 데이터 로드 |
| R3 | 시뮬레이션 엔진 | 날짜별 순회하며 시그널 생성 → 가상 매매 실행 → 포지션/잔고 추적 |
| R4 | 리스크 관리 적용 | 실전과 동일한 `RiskManager` 로직 (손절/익절/포지션 사이즈) |
| R5 | 성과 지표 산출 | 총수익률, 최대낙폭(MDD), 승률, 샤프비율, 거래횟수 |
| R6 | 결과 리포트 | 터미널 텍스트 리포트 + 결과 데이터 반환 |

### 2.2 선택 (Nice to Have)

| ID | 요구사항 | 설명 |
|----|----------|------|
| N1 | 차트 시각화 | matplotlib로 수익률 곡선, 매매 시점 마킹 |
| N2 | 파라미터 최적화 | 전략 파라미터 범위를 지정하여 최적값 탐색 |
| N3 | 벤치마크 비교 | KOSPI 지수 대비 초과수익률 |

---

## 3. 아키텍처

### 3.1 모듈 구조

```
src/backtest/
├── __init__.py
├── data_loader.py    # 과거 데이터 로드 (API/CSV)
├── engine.py         # 백테스트 시뮬레이션 엔진
├── broker.py         # 가상 브로커 (주문 실행, 잔고 관리)
└── report.py         # 성과 지표 계산 및 리포트
```

### 3.2 데이터 흐름

```
DataLoader → DataFrame(일봉)
     ↓
BacktestEngine (날짜별 순회)
     ↓
  BaseStrategy.analyze(sliding_window_df) → Signal
     ↓
  VirtualBroker.execute(signal, current_price)
     ↓
  포지션/잔고 업데이트
     ↓
BacktestReport (성과 지표 계산)
```

### 3.3 핵심 설계 원칙

1. **전략 인터페이스 동일**: `BaseStrategy.analyze(df: pd.DataFrame) -> Signal` 그대로 사용
2. **API 미호출**: 백테스트는 로컬 데이터만 사용 (Rate Limiter 부담 없음)
3. **실전 리스크 동일 적용**: `RiskManager`의 손절/익절/포지션비율 로직 재사용
4. **단일 종목 단위**: 종목 1개 기준 백테스트 → 이후 T3-3에서 다중 종목 확장

---

## 4. 주요 클래스 설계

### 4.1 DataLoader

```python
class DataLoader:
    """과거 데이터를 로드한다."""

    async def from_api(self, stock_code: str, days: int = 100) -> pd.DataFrame:
        """KIS API에서 일봉을 가져와 DataFrame으로 반환한다."""

    def from_csv(self, file_path: str) -> pd.DataFrame:
        """CSV 파일에서 일봉을 로드한다."""
        # 컬럼: date, open, high, low, close, volume
```

### 4.2 VirtualBroker

```python
@dataclass
class BacktestConfig:
    initial_capital: int = 10_000_000   # 초기 자본금 (1000만원)
    commission_rate: float = 0.00015    # 수수료율 (0.015%)
    slippage_rate: float = 0.001        # 슬리피지 (0.1%)
    max_position_ratio: float = 0.2     # 최대 포지션 비율

class VirtualBroker:
    """가상 브로커 — 주문 실행 및 잔고를 관리한다."""

    def buy(self, stock_code: str, price: float, quantity: int) -> bool
    def sell(self, stock_code: str, price: float, quantity: int) -> bool
    @property
    def portfolio_value(self) -> float  # 현재 총 평가액
    @property
    def positions(self) -> dict[str, Position]  # 보유 포지션
```

### 4.3 BacktestEngine

```python
class BacktestEngine:
    """백테스트 시뮬레이션을 실행한다."""

    def __init__(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig | None = None,
    ) -> None: ...

    def run(self, data: pd.DataFrame, stock_code: str) -> BacktestResult:
        """일봉 DataFrame으로 백테스트를 실행한다."""
        # 날짜별 슬라이딩 윈도우로 strategy.analyze() 호출
        # VirtualBroker로 가상 매매 실행
        # RiskManager 로직 적용 (손절/익절)
```

### 4.4 BacktestReport

```python
@dataclass
class BacktestResult:
    total_return: float          # 총수익률 (%)
    max_drawdown: float          # 최대낙폭 (%)
    win_rate: float              # 승률 (%)
    sharpe_ratio: float          # 샤프비율
    total_trades: int            # 총 거래 횟수
    profit_trades: int           # 수익 거래 수
    loss_trades: int             # 손실 거래 수
    avg_profit: float            # 평균 수익률 (%)
    avg_loss: float              # 평균 손실률 (%)
    equity_curve: list[float]    # 일별 자산 곡선
    trade_log: list[TradeRecord] # 거래 기록

class BacktestReport:
    """백테스트 결과를 리포트로 출력한다."""

    def print_summary(self, result: BacktestResult) -> None:
        """터미널에 성과 요약을 출력한다."""

    def to_dataframe(self, result: BacktestResult) -> pd.DataFrame:
        """거래 기록을 DataFrame으로 변환한다."""
```

---

## 5. 구현 순서

| 순서 | 파일 | 내용 | 예상 규모 |
|------|------|------|-----------|
| 1 | `src/backtest/__init__.py` | 패키지 초기화 | 소 |
| 2 | `src/backtest/data_loader.py` | 데이터 로드 (CSV + API) | 중 |
| 3 | `src/backtest/broker.py` | VirtualBroker + BacktestConfig + Position | 중 |
| 4 | `src/backtest/engine.py` | BacktestEngine (핵심 루프) | 대 |
| 5 | `src/backtest/report.py` | 성과 지표 + 리포트 출력 | 중 |
| 6 | `scripts/run_backtest.py` | CLI 실행 스크립트 | 소 |
| 7 | `tests/test_backtest/` | 단위 테스트 | 중 |

---

## 6. 기존 코드 영향도

| 기존 파일 | 변경 내용 | 영향도 |
|-----------|-----------|--------|
| `src/strategy/base.py` | 변경 없음 (인터페이스 그대로 사용) | 없음 |
| `src/strategy/moving_average.py` | 변경 없음 | 없음 |
| `src/strategy/risk.py` | 변경 없음 (RiskManager 로직 재사용) | 없음 |
| `src/api/quote.py` | DataLoader에서 `get_daily_price()` 참조만 | 없음 |

**신규 모듈만 추가하며, 기존 코드 수정은 없다.**

---

## 7. 검증 기준

- [ ] `BaseStrategy`를 구현한 모든 전략이 백테스트 가능
- [ ] 초기자본 1000만원 기준 MovingAverageStrategy 100일 시뮬레이션 실행
- [ ] 수수료/슬리피지 반영된 수익률 산출
- [ ] 손절/익절 로직이 실전과 동일하게 동작
- [ ] `pytest tests/test_backtest/` 전체 통과
- [ ] `mypy src/backtest/` 타입 체크 통과
- [ ] `ruff check src/backtest/` 린트 통과

---

## 8. 리스크 및 제약사항

| 리스크 | 대응 |
|--------|------|
| KIS API 일봉 데이터 100건 제한 | CSV 파일 로드 기능으로 장기 데이터 지원 |
| 실시간 호가/틱 데이터 미반영 | 일봉 종가 기반 시뮬레이션 (v1 한계 명시) |
| 미체결/부분체결 미반영 | 전량 즉시체결 가정 (v1 단순화) |
| 분할매수/매도 미지원 | 단일 진입/청산 방식 (T3-3에서 확장) |

---

## 9. 사용 예시 (완성 후)

```python
from src.backtest.data_loader import DataLoader
from src.backtest.engine import BacktestEngine
from src.backtest.broker import BacktestConfig
from src.backtest.report import BacktestReport
from src.strategy.moving_average import MovingAverageStrategy

# 데이터 로드
loader = DataLoader()
data = loader.from_csv("data/samsung_daily.csv")

# 백테스트 실행
engine = BacktestEngine(
    strategy=MovingAverageStrategy(short_period=5, long_period=20),
    config=BacktestConfig(initial_capital=10_000_000),
)
result = engine.run(data, stock_code="005930")

# 결과 출력
report = BacktestReport()
report.print_summary(result)
# 총수익률: +12.5%, MDD: -4.2%, 승률: 58.3%, 거래: 24건
```
