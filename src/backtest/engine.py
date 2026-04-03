"""백테스트 시뮬레이션 엔진."""

from __future__ import annotations

import pandas as pd

from src.backtest.broker import BacktestConfig, VirtualBroker
from src.backtest.report import BacktestReport, BacktestResult
from src.strategy.base import BaseStrategy, SignalType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 전략 분석에 필요한 최소 데이터 행 수 (장기 MA 20일 + 교차 확인 1일)
MIN_WINDOW_SIZE: int = 21

# 매수 시그널 최소 신뢰도 (실전 RiskManager.validate_order와 동일)
MIN_CONFIDENCE: float = 0.1


class BacktestEngine:
    """과거 일봉 데이터로 전략 시뮬레이션을 실행한다.

    날짜별 슬라이딩 윈도우를 구성하여 strategy.analyze()를 호출하고,
    VirtualBroker를 통해 가상 매매를 실행한다.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig | None = None,
    ) -> None:
        """백테스트 엔진을 초기화한다.

        Args:
            strategy: 매매 전략 (BaseStrategy 구현체)
            config: 백테스트 설정 (None이면 기본값)
        """
        self._strategy = strategy
        self._config = config or BacktestConfig()
        self._broker = VirtualBroker(self._config)

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
        if len(data) < MIN_WINDOW_SIZE:
            raise ValueError(
                f"데이터 부족: 최소 {MIN_WINDOW_SIZE}행 필요, 현재 {len(data)}행"
            )

        self._broker = VirtualBroker(self._config)
        equity_curve: list[float] = []

        logger.info(
            "백테스트 시작: 전략=%s, 종목=%s, 데이터=%d일",
            self._strategy.name,
            stock_code,
            len(data),
        )

        for i in range(MIN_WINDOW_SIZE, len(data)):
            # 슬라이딩 윈도우: 처음~현재일
            window_df = data.iloc[: i + 1].copy()
            current_row = data.iloc[i]
            current_price = int(current_row["close"])
            current_date = str(current_row["date"])

            # 종가 0원 데이터 스킵
            if current_price <= 0:
                equity = self._broker.portfolio_value({stock_code: current_price})
                equity_curve.append(equity)
                continue

            self._process_day(window_df, stock_code, current_price, current_date)

            # equity curve 기록
            equity = self._broker.portfolio_value({stock_code: current_price})
            equity_curve.append(equity)

        # 결과 집계
        return self._build_result(data, stock_code, equity_curve)

    def _process_day(
        self,
        window_df: pd.DataFrame,
        stock_code: str,
        current_price: int,
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
        is_held = stock_code in self._broker.positions

        # 전략 분석 (보유/미보유 모두 실행)
        signal = self._strategy.analyze(window_df[["close"]].copy())

        # 보유 종목 처리
        if is_held:
            # 1. 손절
            if self._broker.check_stop_loss(stock_code, float(current_price)):
                self._broker.sell(stock_code, float(current_price), current_date, reason="손절")
                return

            # 2. 익절
            if self._broker.check_take_profit(stock_code, float(current_price)):
                self._broker.sell(stock_code, float(current_price), current_date, reason="익절")
                return

            # 3. 전략 매도 시그널
            if signal.signal_type == SignalType.SELL and signal.confidence >= MIN_CONFIDENCE:
                self._broker.sell(stock_code, float(current_price), current_date, reason="전략매도")
            return

        # 미보유 — 매수 시그널
        if signal.signal_type == SignalType.BUY and signal.confidence >= MIN_CONFIDENCE:
            self._broker.buy(stock_code, float(current_price), current_date)

    def _build_result(
        self,
        data: pd.DataFrame,
        stock_code: str,
        equity_curve: list[float],
    ) -> BacktestResult:
        """시뮬레이션 완료 후 결과를 집계한다.

        Args:
            data: 원본 일봉 DataFrame
            stock_code: 종목코드
            equity_curve: 일별 자산 곡선

        Returns:
            집계된 BacktestResult
        """
        # 미청산 포지션이 있으면 마지막 종가로 강제 청산
        last_price = float(data.iloc[-1]["close"])
        if stock_code in self._broker.positions:
            last_date = str(data.iloc[-1]["date"])
            self._broker.sell(stock_code, last_price, last_date, reason="백테스트종료")
            if equity_curve:
                equity_curve[-1] = self._broker.portfolio_value({stock_code: last_price})

        start_date = str(data.iloc[MIN_WINDOW_SIZE]["date"])
        end_date = str(data.iloc[-1]["date"])

        result = BacktestResult(
            strategy_name=self._strategy.name,
            stock_code=stock_code,
            period=f"{start_date}~{end_date}",
            initial_capital=self._config.initial_capital,
            final_capital=self._broker.cash,
            equity_curve=equity_curve,
            trade_log=self._broker.trade_history,
        )

        report = BacktestReport()
        result = report.calculate_metrics(result)

        logger.info(
            "백테스트 완료: 수익률=%.2f%%, MDD=%.2f%%, 거래=%d건",
            result.total_return,
            result.max_drawdown,
            result.total_trades,
        )

        return result
