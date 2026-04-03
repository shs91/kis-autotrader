"""백테스트 결과 리포트."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from src.backtest.broker import TradeRecord, TradeSide


@dataclass
class BacktestResult:
    """백테스트 실행 결과를 저장하는 데이터 클래스."""

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
    """백테스트 결과 지표 계산 및 리포트 출력 클래스."""

    TRADING_DAYS_PER_YEAR: int = 252
    RISK_FREE_RATE: float = 0.035

    def calculate_metrics(self, result: BacktestResult) -> BacktestResult:
        """백테스트 결과의 주요 성과 지표를 계산한다.

        Args:
            result: 기본 데이터가 채워진 BacktestResult 객체.

        Returns:
            성과 지표가 계산된 BacktestResult 객체.
        """
        # 총수익률
        if result.initial_capital > 0:
            result.total_return = (
                (result.final_capital - result.initial_capital)
                / result.initial_capital
                * 100
            )

        # 최대낙폭 (MDD)
        result.max_drawdown = self._calculate_max_drawdown(result.equity_curve)

        # 매도 거래 분류
        sell_trades = [
            t for t in result.trade_log if t.side == TradeSide.SELL
        ]
        profit_sells = [t for t in sell_trades if t.profit_loss > 0]
        loss_sells = [t for t in sell_trades if t.profit_loss <= 0]

        result.total_trades = len(result.trade_log)
        result.profit_trades = len(profit_sells)
        result.loss_trades = len(loss_sells)

        # 승률
        if sell_trades:
            result.win_rate = len(profit_sells) / len(sell_trades) * 100
        else:
            result.win_rate = 0.0

        # 평균 수익률 / 평균 손실률
        if profit_sells:
            result.avg_profit_rate = sum(
                t.profit_rate for t in profit_sells
            ) / len(profit_sells)
        else:
            result.avg_profit_rate = 0.0

        if loss_sells:
            result.avg_loss_rate = sum(
                t.profit_rate for t in loss_sells
            ) / len(loss_sells)
        else:
            result.avg_loss_rate = 0.0

        # Profit Factor
        total_profit = sum(t.profit_loss for t in profit_sells)
        total_loss = sum(t.profit_loss for t in loss_sells)

        if total_loss < 0:
            result.profit_factor = total_profit / abs(total_loss)
        elif total_profit > 0:
            result.profit_factor = float("inf")
        else:
            result.profit_factor = 0.0

        # 샤프 비율
        result.sharpe_ratio = self._calculate_sharpe_ratio(result.equity_curve)

        return result

    def print_summary(self, result: BacktestResult) -> None:
        """백테스트 결과 요약을 출력한다.

        Args:
            result: 지표가 계산된 BacktestResult 객체.
        """
        buy_count = sum(
            1 for t in result.trade_log if t.side == TradeSide.BUY
        )
        sell_count = sum(
            1 for t in result.trade_log if t.side == TradeSide.SELL
        )

        separator_double = "═" * 42
        separator_single = "─" * 42

        print(separator_double)
        print(f"백테스트 결과: {result.strategy_name}")
        print(f"종목: {result.stock_code} | 기간: {result.period}")
        print(separator_double)
        print(f"초기자본:     {result.initial_capital:>15,} 원")
        print(f"최종자본:     {result.final_capital:>15,.0f} 원")
        print(f"총수익률:     {result.total_return:>+14.2f}%")
        print(f"최대낙폭(MDD):{result.max_drawdown:>14.2f}%")
        print(separator_single)
        print(
            f"총거래:  {result.total_trades}건 "
            f"(매수 {buy_count} / 매도 {sell_count})"
        )
        print(f"승률:    {result.win_rate:.1f}%")
        print(f"수익거래: {result.profit_trades}건 | 손실거래: {result.loss_trades}건")
        print(f"평균수익률: {result.avg_profit_rate:+.2f}%")
        print(f"평균손실률: {result.avg_loss_rate:+.2f}%")
        print(f"Profit Factor: {result.profit_factor:.2f}")
        print(f"샤프비율: {result.sharpe_ratio:.4f}")
        print(separator_double)

    def to_dataframe(self, result: BacktestResult) -> pd.DataFrame:
        """거래 내역을 DataFrame으로 변환한다.

        Args:
            result: BacktestResult 객체.

        Returns:
            거래 내역이 담긴 pandas DataFrame.
        """
        rows: list[dict[str, object]] = []
        for trade in result.trade_log:
            rows.append(
                {
                    "date": trade.date,
                    "stock_code": trade.stock_code,
                    "side": trade.side.value,
                    "price": trade.price,
                    "quantity": trade.quantity,
                    "commission": trade.commission,
                    "profit_loss": trade.profit_loss,
                    "profit_rate": trade.profit_rate,
                }
            )
        return pd.DataFrame(
            rows,
            columns=[
                "date",
                "stock_code",
                "side",
                "price",
                "quantity",
                "commission",
                "profit_loss",
                "profit_rate",
            ],
        )

    def _calculate_max_drawdown(self, equity_curve: list[float]) -> float:
        """자본 곡선으로부터 최대낙폭(MDD)을 계산한다.

        Args:
            equity_curve: 자본 변화 리스트.

        Returns:
            최대낙폭 비율 (%).
        """
        if not equity_curve:
            return 0.0

        peak = equity_curve[0]
        max_dd = 0.0

        for equity in equity_curve:
            if equity > peak:
                peak = equity
            if peak > 0:
                drawdown = (peak - equity) / peak * 100
                if drawdown > max_dd:
                    max_dd = drawdown

        return max_dd

    def _calculate_sharpe_ratio(self, equity_curve: list[float]) -> float:
        """자본 곡선으로부터 연환산 샤프 비율을 계산한다.

        Args:
            equity_curve: 자본 변화 리스트.

        Returns:
            연환산 샤프 비율. 표준편차가 0이면 0을 반환한다.
        """
        if len(equity_curve) < 2:
            return 0.0

        daily_returns: list[float] = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]
            if prev != 0:
                daily_returns.append(
                    (equity_curve[i] - prev) / prev
                )

        if not daily_returns:
            return 0.0

        avg_daily = sum(daily_returns) / len(daily_returns)
        variance = sum(
            (r - avg_daily) ** 2 for r in daily_returns
        ) / len(daily_returns)
        std_daily = math.sqrt(variance)

        annualized_return = avg_daily * self.TRADING_DAYS_PER_YEAR
        annualized_std = std_daily * math.sqrt(self.TRADING_DAYS_PER_YEAR)

        if annualized_std == 0:
            return 0.0

        return (annualized_return - self.RISK_FREE_RATE) / annualized_std
