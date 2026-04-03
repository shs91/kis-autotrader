# T3-2: 백테스팅 프레임워크 — 상세 설계

> 작성일: 2026-04-03
> 상태: Design
> Plan 문서: `docs/01-plan/features/T3-2-backtesting.plan.md`

---

## 1. 모듈 구조 및 파일 목록

```
src/backtest/
├── __init__.py           # 공개 API re-export
├── data_loader.py        # DataLoader 클래스
├── broker.py             # BacktestConfig, Position, TradeRecord, VirtualBroker
├── engine.py             # BacktestEngine
└── report.py             # BacktestResult, BacktestReport

scripts/
└── run_backtest.py       # CLI 실행 스크립트

tests/test_backtest/
├── __init__.py
├── test_data_loader.py
├── test_broker.py
├── test_engine.py
└── test_report.py
```

---

## 2. 상세 클래스 설계

### 2.1 `src/backtest/data_loader.py`

```python
"""백테스트용 과거 데이터 로더."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.api.client import KISClient
from src.api.quote import QuoteAPI


class DataLoader:
    """과거 일봉 데이터를 로드한다.

    CSV 파일 또는 KIS API에서 일봉 데이터를 pandas DataFrame으로 변환한다.
    반환 DataFrame 컬럼: date(str), open(int), high(int), low(int), close(int), volume(int)
    정렬: 날짜 오름차순 (과거 → 최근)
    """

    # CSV 필수 컬럼
    REQUIRED_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")

    def from_csv(self, file_path: str | Path) -> pd.DataFrame:
        """CSV 파일에서 일봉 데이터를 로드한다.

        Args:
            file_path: CSV 파일 경로

        Returns:
            일봉 DataFrame (날짜 오름차순)

        Raises:
            FileNotFoundError: 파일이 존재하지 않을 때
            ValueError: 필수 컬럼이 누락되었을 때
        """

    async def from_api(
        self,
        stock_code: str,
        days: int = 100,
        client: KISClient | None = None,
    ) -> pd.DataFrame:
        """KIS API에서 일봉 데이터를 가져온다.

        Args:
            stock_code: 종목코드 (6자리)
            days: 조회할 일수 (KIS API 최대 100건)
            client: KISClient 인스턴스 (None이면 새로 생성)

        Returns:
            일봉 DataFrame (날짜 오름차순)

        Note:
            KIS API는 최근 100건까지만 제공하므로,
            장기 데이터가 필요하면 from_csv()를 사용할 것.
        """

    def _validate_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame의 컬럼과 정렬을 검증/정규화한다.

        - 필수 컬럼 존재 확인
        - 날짜 오름차순 정렬
        - 숫자 컬럼 int 변환

        Returns:
            정규화된 DataFrame
        """
```

**DataFrame 스키마**:

| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| date | str | 날짜 (YYYYMMDD) | "20260401" |
| open | int | 시가 | 70000 |
| high | int | 고가 | 71500 |
| low | int | 저가 | 69500 |
| close | int | 종가 | 71000 |
| volume | int | 거래량 | 15234567 |

**기존 코드 연동**: `QuoteAPI.get_daily_price()` → `DailyPriceItem` 리스트를 DataFrame으로 변환.
실전 `TradingEngine._get_daily_df()`와 동일한 방식이되, `close` 외에 OHLCV 전체를 포함.

---

### 2.2 `src/backtest/broker.py`

```python
"""가상 브로커 — 백테스트용 주문 실행 및 잔고 관리."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TradeSide(Enum):
    """거래 방향."""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class BacktestConfig:
    """백테스트 설정.

    Attributes:
        initial_capital: 초기 자본금 (원)
        commission_rate: 매매 수수료율 (매수/매도 각각 적용)
        slippage_rate: 슬리피지 비율 (체결가 불리하게 적용)
        max_position_ratio: 1종목 최대 투자 비율 (자본금 대비)
        max_loss_rate: 손절 기준 손실률
        take_profit_ratio: 익절 기준 수익률
    """
    initial_capital: int = 10_000_000
    commission_rate: float = 0.00015     # 0.015% (증권사 온라인 수수료 수준)
    slippage_rate: float = 0.001         # 0.1%
    max_position_ratio: float = 0.2      # 20%
    max_loss_rate: float = 0.03          # 3%
    take_profit_ratio: float = 0.05      # 5%


@dataclass
class Position:
    """보유 포지션 정보.

    Attributes:
        stock_code: 종목코드
        quantity: 보유 수량
        avg_price: 평균 매입 단가
        entry_date: 진입일
    """
    stock_code: str
    quantity: int
    avg_price: float
    entry_date: str


@dataclass
class TradeRecord:
    """개별 거래 기록.

    Attributes:
        date: 거래일
        stock_code: 종목코드
        side: 매수/매도
        price: 체결가 (슬리피지 적용 후)
        quantity: 수량
        commission: 수수료
        profit_loss: 실현 손익 (매도 시만, 매수 시 0)
        profit_rate: 실현 수익률 (매도 시만, 매수 시 0.0)
    """
    date: str
    stock_code: str
    side: TradeSide
    price: float
    quantity: int
    commission: float
    profit_loss: float = 0.0
    profit_rate: float = 0.0


class VirtualBroker:
    """가상 브로커 — 주문 실행, 포지션 관리, 잔고 추적.

    실전 RiskManager와 동일한 손절/익절/포지션사이즈 로직을 적용한다.
    수수료와 슬리피지를 반영하여 현실적인 시뮬레이션을 수행한다.
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        """가상 브로커를 초기화한다.

        Args:
            config: 백테스트 설정 (None이면 기본값)
        """

    def buy(self, stock_code: str, price: float, date: str) -> TradeRecord | None:
        """매수 주문을 실행한다.

        포지션 사이즈는 config.max_position_ratio에 따라 자동 계산.
        슬리피지: 체결가 = price * (1 + slippage_rate)
        수수료: 체결금액 * commission_rate

        Args:
            stock_code: 종목코드
            price: 주문 기준가 (종가)
            date: 거래일

        Returns:
            TradeRecord 또는 None (잔고 부족/이미 보유 시)
        """

    def sell(self, stock_code: str, price: float, date: str, reason: str = "") -> TradeRecord | None:
        """매도 주문을 실행한다.

        슬리피지: 체결가 = price * (1 - slippage_rate)
        수수료: 체결금액 * commission_rate
        실현손익 = (매도체결가 - 평균매입가) * 수량 - 수수료

        Args:
            stock_code: 종목코드
            price: 주문 기준가 (종가)
            date: 거래일
            reason: 매도 사유 (손절/익절/전략매도)

        Returns:
            TradeRecord 또는 None (미보유 시)
        """

    def check_stop_loss(self, stock_code: str, current_price: float) -> bool:
        """손절 조건을 확인한다.

        현재가가 평균매입가 대비 max_loss_rate 이상 하락 시 True.

        Args:
            stock_code: 종목코드
            current_price: 현재가

        Returns:
            손절 필요 여부
        """

    def check_take_profit(self, stock_code: str, current_price: float) -> bool:
        """익절 조건을 확인한다.

        현재가가 평균매입가 대비 take_profit_ratio 이상 상승 시 True.

        Args:
            stock_code: 종목코드
            current_price: 현재가

        Returns:
            익절 필요 여부
        """

    @property
    def cash(self) -> float:
        """현금 잔고를 반환한다."""

    @property
    def positions(self) -> dict[str, Position]:
        """보유 포지션을 반환한다. {종목코드: Position}"""

    def portfolio_value(self, current_prices: dict[str, float]) -> float:
        """총 포트폴리오 평가액을 반환한다 (현금 + 보유주식 평가액).

        Args:
            current_prices: {종목코드: 현재가}
        """

    @property
    def trade_history(self) -> list[TradeRecord]:
        """전체 거래 기록을 반환한다."""
```

**RiskManager 로직 재사용 매핑**:

| 실전 (RiskManager) | 백테스트 (VirtualBroker) | 동일 로직 |
|---------------------|-------------------------|-----------|
| `should_stop_loss(current, avg)` | `check_stop_loss(code, current)` | `(avg - current) / avg >= max_loss_rate` |
| `should_take_profit(current, avg)` | `check_take_profit(code, current)` | `(current - avg) / avg >= take_profit_ratio` |
| `calculate_position_size(balance, price)` | `buy()` 내부 자동 계산 | `int(cash * max_position_ratio / price)` |

---

### 2.3 `src/backtest/engine.py`

```python
"""백테스트 시뮬레이션 엔진."""

from __future__ import annotations

import pandas as pd

from src.backtest.broker import BacktestConfig, TradeRecord, VirtualBroker
from src.backtest.report import BacktestResult
from src.strategy.base import BaseStrategy, SignalType


class BacktestEngine:
    """과거 일봉 데이터로 전략 시뮬레이션을 실행한다.

    날짜별로 슬라이딩 윈도우를 구성하여 strategy.analyze()를 호출하고,
    VirtualBroker를 통해 가상 매매를 실행한다.
    """

    # 전략 분석에 필요한 최소 데이터 행 수 (장기 MA 20일 + 교차 확인 1일)
    MIN_WINDOW_SIZE: int = 21

    def __init__(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig | None = None,
    ) -> None:
        """백테스트 엔진을 초기화한다.

        Args:
            strategy: 매매 전략 (BaseStrategy 구현체)
            config: 백테스트 설정
        """

    def run(self, data: pd.DataFrame, stock_code: str) -> BacktestResult:
        """백테스트를 실행한다.

        Args:
            data: 일봉 DataFrame (컬럼: date, open, high, low, close, volume)
                  날짜 오름차순 정렬 필수
            stock_code: 종목코드

        Returns:
            백테스트 결과

        Raises:
            ValueError: 데이터가 MIN_WINDOW_SIZE보다 적을 때
        """

    def _process_day(
        self,
        window_df: pd.DataFrame,
        stock_code: str,
        current_price: float,
        current_date: str,
    ) -> None:
        """하루치 매매 로직을 처리한다.

        처리 순서 (실전 TradingEngine._process_held_stock과 동일):
        1. 보유 종목 → 손절 체크
        2. 보유 종목 → 익절 체크
        3. 보유 종목 + 매도 시그널 → 전략 매도
        4. 미보유 + 매수 시그널 → 매수

        Args:
            window_df: 전략 분석용 슬라이딩 윈도우 DataFrame
            stock_code: 종목코드
            current_price: 당일 종가
            current_date: 당일 날짜
        """

    def _build_result(
        self,
        data: pd.DataFrame,
        stock_code: str,
    ) -> BacktestResult:
        """시뮬레이션 완료 후 결과를 집계한다.

        equity_curve 구성:
        - 각 거래일의 portfolio_value (현금 + 보유주식 평가)
        - 데이터 시작일부터 종료일까지

        Returns:
            집계된 BacktestResult
        """
```

**시뮬레이션 루프 상세**:

```
for i in range(MIN_WINDOW_SIZE, len(data)):
    window_df = data.iloc[:i+1].copy()    # 슬라이딩 윈도우 (처음~현재일)

    # strategy.analyze()에 전달할 DataFrame 구성
    # 기존 MovingAverageStrategy는 'close' 컬럼만 사용
    analysis_df = window_df[["close"]].copy()

    current_row = data.iloc[i]
    current_price = current_row["close"]
    current_date = current_row["date"]

    _process_day(analysis_df, stock_code, current_price, current_date)

    # equity_curve 기록
    equity = broker.portfolio_value({stock_code: current_price})
    equity_curve.append(equity)
```

**전략 분석용 DataFrame 포맷 호환**:
- `MovingAverageStrategy.analyze()`는 `close` 컬럼만 필요
- `BaseStrategy`의 다른 구현체가 `open/high/low/volume`을 사용할 수 있으므로 전체 컬럼 전달
- 단, 실전 `TradingEngine._get_daily_df()`에서 `close`와 `date`만 담고 있으므로, 백테스트에서도 `close` 컬럼은 반드시 포함

---

### 2.4 `src/backtest/report.py`

```python
"""백테스트 결과 리포트."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.backtest.broker import TradeRecord


@dataclass
class BacktestResult:
    """백테스트 결과 데이터.

    Attributes:
        strategy_name: 전략 이름
        stock_code: 종목코드
        period: 백테스트 기간 (시작일~종료일)
        initial_capital: 초기 자본금
        final_capital: 최종 자본금
        total_return: 총수익률 (%)
        max_drawdown: 최대낙폭 MDD (%)
        win_rate: 승률 (%)
        sharpe_ratio: 샤프비율 (연환산, 무위험이자율 3.5%)
        total_trades: 총 거래 횟수 (매수+매도)
        profit_trades: 수익 거래 수
        loss_trades: 손실 거래 수
        avg_profit_rate: 수익 거래 평균 수익률 (%)
        avg_loss_rate: 손실 거래 평균 손실률 (%)
        profit_factor: 손익비 (총이익 / 총손실)
        equity_curve: 일별 총자산 곡선
        trade_log: 거래 기록 리스트
    """
    strategy_name: str = ""
    stock_code: str = ""
    period: str = ""
    initial_capital: int = 0
    final_capital: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    total_trades: int = 0
    profit_trades: int = 0
    loss_trades: int = 0
    avg_profit_rate: float = 0.0
    avg_loss_rate: float = 0.0
    profit_factor: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    trade_log: list[TradeRecord] = field(default_factory=list)


class BacktestReport:
    """백테스트 결과를 리포트로 출력한다."""

    # 연환산 기준 거래일 수
    TRADING_DAYS_PER_YEAR: int = 252
    # 무위험 이자율 (한국 국고채 3년 수준)
    RISK_FREE_RATE: float = 0.035

    def calculate_metrics(self, result: BacktestResult) -> BacktestResult:
        """equity_curve와 trade_log로부터 성과 지표를 계산한다.

        계산 항목:
        - total_return: (final - initial) / initial * 100
        - max_drawdown: max(peak - trough) / peak * 100
        - win_rate: profit_trades / total_sell_trades * 100
        - sharpe_ratio: (annualized_return - risk_free) / annualized_std
        - profit_factor: sum(profits) / abs(sum(losses))

        Args:
            result: 기본값이 채워진 BacktestResult (equity_curve, trade_log 필수)

        Returns:
            지표가 계산된 BacktestResult
        """

    def print_summary(self, result: BacktestResult) -> None:
        """터미널에 성과 요약을 출력한다.

        출력 형식:
        ══════════════════════════════════════════
        백테스트 결과: 이동평균교차(5/20)
        종목: 005930 | 기간: 20260101~20260401
        ══════════════════════════════════════════
        초기자본:     10,000,000 원
        최종자본:     11,250,000 원
        총수익률:         +12.50%
        최대낙폭(MDD):     -4.20%
        ──────────────────────────────────────────
        총거래:        24건 (매수 12 / 매도 12)
        승률:          58.3%
        수익거래:      7건 (평균 +3.2%)
        손실거래:      5건 (평균 -1.8%)
        손익비:        2.48
        샤프비율:      1.35
        ══════════════════════════════════════════
        """

    def to_dataframe(self, result: BacktestResult) -> pd.DataFrame:
        """거래 기록을 DataFrame으로 변환한다.

        Returns:
            컬럼: date, stock_code, side, price, quantity, commission, profit_loss, profit_rate
        """
```

**MDD 계산 로직**:
```python
# equity_curve에서 MDD 계산
peak = equity_curve[0]
max_dd = 0.0
for equity in equity_curve:
    if equity > peak:
        peak = equity
    drawdown = (peak - equity) / peak
    if drawdown > max_dd:
        max_dd = drawdown
max_drawdown = max_dd * 100  # 퍼센트
```

**샤프비율 계산 로직**:
```python
# 일별 수익률로 연환산 샤프비율 계산
daily_returns = [(eq[i] - eq[i-1]) / eq[i-1] for i in range(1, len(eq))]
avg_daily = mean(daily_returns)
std_daily = stdev(daily_returns)
annualized_return = avg_daily * 252
annualized_std = std_daily * sqrt(252)
sharpe = (annualized_return - risk_free_rate) / annualized_std
```

---

### 2.5 `src/backtest/__init__.py`

```python
"""백테스팅 프레임워크 패키지."""

from src.backtest.broker import BacktestConfig, Position, TradeRecord, VirtualBroker
from src.backtest.data_loader import DataLoader
from src.backtest.engine import BacktestEngine
from src.backtest.report import BacktestReport, BacktestResult

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestReport",
    "BacktestResult",
    "DataLoader",
    "Position",
    "TradeRecord",
    "VirtualBroker",
]
```

---

### 2.6 `scripts/run_backtest.py`

```python
"""백테스트 CLI 실행 스크립트.

사용법:
    python scripts/run_backtest.py --csv data/005930.csv --code 005930
    python scripts/run_backtest.py --code 005930 --api  (KIS API에서 로드)
    python scripts/run_backtest.py --csv data/005930.csv --code 005930 --capital 50000000
"""

import argparse
import asyncio

from src.backtest import BacktestConfig, BacktestEngine, BacktestReport, DataLoader
from src.strategy.moving_average import MovingAverageStrategy


def parse_args() -> argparse.Namespace:
    """CLI 인수를 파싱한다."""
    parser = argparse.ArgumentParser(description="백테스트 실행")
    parser.add_argument("--code", required=True, help="종목코드 (예: 005930)")
    parser.add_argument("--csv", help="CSV 파일 경로")
    parser.add_argument("--api", action="store_true", help="KIS API에서 데이터 로드")
    parser.add_argument("--capital", type=int, default=10_000_000, help="초기자본금")
    parser.add_argument("--short-ma", type=int, default=5, help="단기 이동평균 기간")
    parser.add_argument("--long-ma", type=int, default=20, help="장기 이동평균 기간")
    return parser.parse_args()


async def main() -> None:
    """백테스트를 실행한다."""
    args = parse_args()

    loader = DataLoader()
    if args.csv:
        data = loader.from_csv(args.csv)
    elif args.api:
        data = await loader.from_api(args.code)
    else:
        parser.error("--csv 또는 --api 중 하나를 지정하세요.")

    strategy = MovingAverageStrategy(
        short_period=args.short_ma,
        long_period=args.long_ma,
    )
    config = BacktestConfig(initial_capital=args.capital)
    engine = BacktestEngine(strategy=strategy, config=config)
    result = engine.run(data, stock_code=args.code)

    report = BacktestReport()
    report.print_summary(result)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 3. 데이터 흐름 상세

```
┌─────────────┐
│  CSV / API   │
└──────┬──────┘
       │ from_csv() / from_api()
       ▼
┌─────────────────────────────────────────────────┐
│  DataFrame                                       │
│  date    | open  | high  | low   | close | volume│
│  20260301| 70000 | 71500 | 69500 | 71000 | 1523  │
│  20260302| 71000 | 72000 | 70500 | 71800 | 1892  │
│  ...     | ...   | ...   | ...   | ...   | ...   │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│  BacktestEngine.run()                            │
│                                                  │
│  for i in range(21, len(data)):                  │
│    window = data.iloc[:i+1]   ← 슬라이딩 윈도우  │
│    signal = strategy.analyze(window[["close"]])  │
│                                                  │
│    ┌─ 보유 중? ─────────────────────────┐        │
│    │  1. 손절 체크 → sell(reason="손절") │        │
│    │  2. 익절 체크 → sell(reason="익절") │        │
│    │  3. SELL 시그널 → sell(reason="전략")│       │
│    └────────────────────────────────────┘        │
│    ┌─ 미보유? ──────────────────────────┐        │
│    │  BUY 시그널 → buy()               │        │
│    └────────────────────────────────────┘        │
│                                                  │
│    equity_curve.append(portfolio_value)           │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│  BacktestReport.calculate_metrics()              │
│                                                  │
│  입력: equity_curve + trade_log                  │
│  출력: BacktestResult (지표 계산 완료)           │
│    - total_return, max_drawdown, win_rate        │
│    - sharpe_ratio, profit_factor                 │
└──────┬──────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│  BacktestReport.print_summary()                  │
│  터미널 텍스트 출력                              │
└─────────────────────────────────────────────────┘
```

---

## 4. 실전 코드와의 매핑

| 실전 (TradingEngine) | 백테스트 (BacktestEngine) | 비고 |
|----------------------|--------------------------|------|
| `_get_daily_df()` → API 호출 | `DataLoader.from_csv()` | API 미호출 |
| `_strategy.analyze(df)` | 동일: `strategy.analyze(window_df)` | 인터페이스 동일 |
| `_risk.should_stop_loss()` | `broker.check_stop_loss()` | 동일 로직 |
| `_risk.should_take_profit()` | `broker.check_take_profit()` | 동일 로직 |
| `_risk.calculate_position_size()` | `broker.buy()` 내부 | 동일 공식 |
| `_risk.validate_order()` | `broker.buy()` 내부 신뢰도 체크 | confidence >= 0.1 |
| `_execute_buy()` → KIS API 주문 | `broker.buy()` → 가상 체결 | 수수료/슬리피지 추가 |
| `_execute_sell()` → KIS API 주문 | `broker.sell()` → 가상 체결 | 실현손익 계산 |
| `_process_held_stock()` 순서: 손절→익절→전략매도 | `_process_day()` 동일 순서 | 우선순위 동일 |

---

## 5. 에러 처리

| 상황 | 처리 |
|------|------|
| CSV 파일 미존재 | `FileNotFoundError` raise |
| CSV 필수 컬럼 누락 | `ValueError("필수 컬럼 누락: {missing}")` |
| 데이터 행 수 < MIN_WINDOW_SIZE | `ValueError("데이터 부족")` |
| 매수 시 잔고 부족 | `buy()` → `None` 반환 (skip) |
| 매도 시 미보유 종목 | `sell()` → `None` 반환 (skip) |
| 이미 보유 중 매수 시도 | `buy()` → `None` 반환 (단일 포지션 제한) |
| 종가 0원 데이터 | 해당 날짜 skip |

---

## 6. 구현 순서 (Do 단계 가이드)

| 순서 | 파일 | 의존성 | 테스트 |
|------|------|--------|--------|
| 1 | `src/backtest/__init__.py` | - | - |
| 2 | `src/backtest/broker.py` | - | `test_broker.py` |
| 3 | `src/backtest/data_loader.py` | - | `test_data_loader.py` |
| 4 | `src/backtest/report.py` | broker.TradeRecord | `test_report.py` |
| 5 | `src/backtest/engine.py` | broker, report, strategy.base | `test_engine.py` |
| 6 | `scripts/run_backtest.py` | 전체 | 수동 실행 |

---

## 7. 테스트 설계

### 7.1 `test_broker.py`

| 테스트 케이스 | 검증 |
|--------------|------|
| `test_buy_basic` | 매수 후 cash 감소, position 생성, 수수료/슬리피지 반영 |
| `test_buy_insufficient_cash` | 잔고 부족 시 None 반환 |
| `test_buy_already_held` | 이미 보유 시 None 반환 |
| `test_sell_basic` | 매도 후 cash 증가, position 제거, 실현손익 계산 |
| `test_sell_not_held` | 미보유 시 None 반환 |
| `test_stop_loss` | 손절 조건 정확히 판정 |
| `test_take_profit` | 익절 조건 정확히 판정 |
| `test_position_size` | max_position_ratio 적용 수량 검증 |
| `test_commission_calculation` | 수수료 = 체결금액 * commission_rate |
| `test_slippage_buy` | 매수 체결가 = price * (1 + slippage_rate) |
| `test_slippage_sell` | 매도 체결가 = price * (1 - slippage_rate) |

### 7.2 `test_data_loader.py`

| 테스트 케이스 | 검증 |
|--------------|------|
| `test_from_csv_basic` | CSV 로드 후 DataFrame 컬럼/정렬 검증 |
| `test_from_csv_missing_column` | 필수 컬럼 누락 시 ValueError |
| `test_from_csv_not_found` | 파일 미존재 시 FileNotFoundError |
| `test_from_csv_date_sort` | 날짜 역순 CSV도 오름차순 정렬 |

### 7.3 `test_engine.py`

| 테스트 케이스 | 검증 |
|--------------|------|
| `test_run_basic` | BacktestResult 반환, equity_curve 길이 검증 |
| `test_run_insufficient_data` | 데이터 부족 시 ValueError |
| `test_golden_cross_buy` | 골든크로스 발생 시 매수 실행 |
| `test_dead_cross_sell` | 데드크로스 발생 시 매도 실행 |
| `test_stop_loss_trigger` | 손절 조건 도달 시 자동 매도 |
| `test_take_profit_trigger` | 익절 조건 도달 시 자동 매도 |
| `test_process_priority` | 손절 > 익절 > 전략매도 우선순위 |

### 7.4 `test_report.py`

| 테스트 케이스 | 검증 |
|--------------|------|
| `test_total_return` | (final - initial) / initial * 100 |
| `test_max_drawdown` | 알려진 equity_curve로 MDD 검증 |
| `test_win_rate` | profit_trades / total_sell_trades * 100 |
| `test_sharpe_ratio` | 알려진 수익률 배열로 샤프비율 검증 |
| `test_profit_factor` | sum(profits) / abs(sum(losses)) |
| `test_print_summary` | 출력 형식 검증 (capsys) |

---

## 8. CSV 샘플 데이터 형식

```csv
date,open,high,low,close,volume
20260301,70000,71500,69500,71000,15234567
20260302,71000,72000,70500,71800,18923456
20260303,71800,73000,71000,72500,22345678
...
```

테스트용 fixture로 `conftest.py`에 30~50일치 가상 데이터를 생성하는 helper 함수를 제공한다.
