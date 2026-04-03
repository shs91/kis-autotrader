"""BacktestReport 테스트."""

from __future__ import annotations

import math

import pytest

from src.backtest.broker import TradeRecord, TradeSide
from src.backtest.report import BacktestReport, BacktestResult


@pytest.fixture()
def report() -> BacktestReport:
    """BacktestReport 인스턴스를 반환한다."""
    return BacktestReport()


# ------------------------------------------------------------------
# 총수익률
# ------------------------------------------------------------------

def test_total_return(report: BacktestReport) -> None:
    """총수익률: (final - initial) / initial * 100."""
    result = BacktestResult(
        initial_capital=1_000_000,
        final_capital=1_200_000.0,
        equity_curve=[1_000_000.0, 1_200_000.0],
    )
    calculated = report.calculate_metrics(result)
    assert calculated.total_return == pytest.approx(20.0)


# ------------------------------------------------------------------
# 최대낙폭 (MDD)
# ------------------------------------------------------------------

def test_max_drawdown(report: BacktestReport) -> None:
    """알려진 equity curve [100, 110, 90, 105] -> MDD = (110-90)/110 * 100."""
    result = BacktestResult(
        initial_capital=100,
        final_capital=105.0,
        equity_curve=[100.0, 110.0, 90.0, 105.0],
    )
    calculated = report.calculate_metrics(result)
    expected_mdd = (110.0 - 90.0) / 110.0 * 100
    assert calculated.max_drawdown == pytest.approx(expected_mdd)


def test_max_drawdown_empty(report: BacktestReport) -> None:
    """빈 equity curve -> MDD = 0.0."""
    result = BacktestResult(
        initial_capital=100,
        final_capital=100.0,
        equity_curve=[],
    )
    calculated = report.calculate_metrics(result)
    assert calculated.max_drawdown == 0.0


# ------------------------------------------------------------------
# 승률
# ------------------------------------------------------------------

def test_win_rate(report: BacktestReport) -> None:
    """매도 3건 중 수익 2건 -> 승률 66.67%."""
    trade_log = [
        TradeRecord(
            date="2026-01-01", stock_code="005930", side=TradeSide.BUY,
            price=50000.0, quantity=10, commission=75.0,
        ),
        TradeRecord(
            date="2026-01-02", stock_code="005930", side=TradeSide.SELL,
            price=55000.0, quantity=10, commission=82.5,
            profit_loss=49842.5, profit_rate=10.0,
        ),
        TradeRecord(
            date="2026-01-03", stock_code="005930", side=TradeSide.BUY,
            price=50000.0, quantity=10, commission=75.0,
        ),
        TradeRecord(
            date="2026-01-04", stock_code="005930", side=TradeSide.SELL,
            price=52000.0, quantity=10, commission=78.0,
            profit_loss=19922.0, profit_rate=4.0,
        ),
        TradeRecord(
            date="2026-01-05", stock_code="005930", side=TradeSide.BUY,
            price=50000.0, quantity=10, commission=75.0,
        ),
        TradeRecord(
            date="2026-01-06", stock_code="005930", side=TradeSide.SELL,
            price=48000.0, quantity=10, commission=72.0,
            profit_loss=-20072.0, profit_rate=-4.0,
        ),
    ]
    result = BacktestResult(
        initial_capital=1_000_000,
        final_capital=1_049_692.5,
        equity_curve=[1_000_000.0, 1_049_692.5],
        trade_log=trade_log,
    )
    calculated = report.calculate_metrics(result)
    assert calculated.win_rate == pytest.approx(2 / 3 * 100, rel=1e-2)


# ------------------------------------------------------------------
# 샤프 비율 — 표준편차 0
# ------------------------------------------------------------------

def test_sharpe_ratio_zero_std(report: BacktestReport) -> None:
    """일정한 equity curve -> 표준편차 0 -> 샤프비율 0.0."""
    result = BacktestResult(
        initial_capital=100,
        final_capital=100.0,
        equity_curve=[100.0, 100.0, 100.0, 100.0],
    )
    calculated = report.calculate_metrics(result)
    assert calculated.sharpe_ratio == 0.0


# ------------------------------------------------------------------
# Profit Factor
# ------------------------------------------------------------------

def test_profit_factor(report: BacktestReport) -> None:
    """총이익 / |총손실| 계산 확인."""
    trade_log = [
        # 수익 매도 2건: profit_loss 합계 = 300
        TradeRecord(
            date="2026-01-01", stock_code="005930", side=TradeSide.SELL,
            price=110.0, quantity=1, commission=0.0,
            profit_loss=200.0, profit_rate=5.0,
        ),
        TradeRecord(
            date="2026-01-02", stock_code="005930", side=TradeSide.SELL,
            price=105.0, quantity=1, commission=0.0,
            profit_loss=100.0, profit_rate=2.5,
        ),
        # 손실 매도 1건: profit_loss = -50
        TradeRecord(
            date="2026-01-03", stock_code="005930", side=TradeSide.SELL,
            price=95.0, quantity=1, commission=0.0,
            profit_loss=-50.0, profit_rate=-2.5,
        ),
    ]
    result = BacktestResult(
        initial_capital=1000,
        final_capital=1250.0,
        equity_curve=[1000.0, 1250.0],
        trade_log=trade_log,
    )
    calculated = report.calculate_metrics(result)
    assert calculated.profit_factor == pytest.approx(300.0 / 50.0)


def test_profit_factor_no_losses(report: BacktestReport) -> None:
    """손실 매도 없음 -> profit_factor = inf."""
    trade_log = [
        TradeRecord(
            date="2026-01-01", stock_code="005930", side=TradeSide.SELL,
            price=110.0, quantity=1, commission=0.0,
            profit_loss=200.0, profit_rate=5.0,
        ),
    ]
    result = BacktestResult(
        initial_capital=1000,
        final_capital=1200.0,
        equity_curve=[1000.0, 1200.0],
        trade_log=trade_log,
    )
    calculated = report.calculate_metrics(result)
    assert math.isinf(calculated.profit_factor)


# ------------------------------------------------------------------
# print_summary (capsys)
# ------------------------------------------------------------------

def test_print_summary(report: BacktestReport, capsys: pytest.CaptureFixture[str]) -> None:
    """print_summary 출력에 핵심 문자열이 포함되는지 확인."""
    result = BacktestResult(
        strategy_name="TestStrategy",
        stock_code="005930",
        period="2026-01-01 ~ 2026-03-31",
        initial_capital=1_000_000,
        final_capital=1_100_000.0,
        total_return=10.0,
        max_drawdown=5.0,
        win_rate=66.7,
        sharpe_ratio=1.2345,
        total_trades=6,
        profit_trades=2,
        loss_trades=1,
        avg_profit_rate=7.0,
        avg_loss_rate=-4.0,
        profit_factor=6.0,
        equity_curve=[1_000_000.0, 1_100_000.0],
        trade_log=[
            TradeRecord(
                date="2026-01-01", stock_code="005930", side=TradeSide.BUY,
                price=50000.0, quantity=10, commission=75.0,
            ),
            TradeRecord(
                date="2026-01-02", stock_code="005930", side=TradeSide.SELL,
                price=55000.0, quantity=10, commission=82.5,
                profit_loss=49842.5, profit_rate=10.0,
            ),
        ],
    )
    report.print_summary(result)
    captured = capsys.readouterr().out

    assert "TestStrategy" in captured
    assert "005930" in captured
    assert "2026-01-01 ~ 2026-03-31" in captured
    assert "1,000,000" in captured
    assert "1,100,000" in captured
    assert "+10.00%" in captured
    assert "5.00%" in captured
    assert "66.7%" in captured
    assert "1.2345" in captured
    assert "Profit Factor" in captured


# ------------------------------------------------------------------
# to_dataframe
# ------------------------------------------------------------------

def test_to_dataframe(report: BacktestReport) -> None:
    """DataFrame 컬럼 및 행 수 검증."""
    trade_log = [
        TradeRecord(
            date="2026-01-01", stock_code="005930", side=TradeSide.BUY,
            price=50000.0, quantity=10, commission=75.0,
        ),
        TradeRecord(
            date="2026-01-02", stock_code="005930", side=TradeSide.SELL,
            price=55000.0, quantity=10, commission=82.5,
            profit_loss=49842.5, profit_rate=10.0,
        ),
        TradeRecord(
            date="2026-01-03", stock_code="000660", side=TradeSide.BUY,
            price=120000.0, quantity=5, commission=90.0,
        ),
    ]
    result = BacktestResult(
        initial_capital=1_000_000,
        final_capital=1_049_692.5,
        equity_curve=[1_000_000.0, 1_049_692.5],
        trade_log=trade_log,
    )
    df = report.to_dataframe(result)

    expected_columns = [
        "date", "stock_code", "side", "price",
        "quantity", "commission", "profit_loss", "profit_rate",
    ]
    assert list(df.columns) == expected_columns
    assert len(df) == 3
