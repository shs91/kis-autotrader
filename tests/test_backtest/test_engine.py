"""BacktestEngine 테스트."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.backtest.broker import BacktestConfig, TradeSide
from src.backtest.engine import BacktestEngine
from src.strategy.moving_average import MovingAverageStrategy


def _make_ohlcv(
    prices: list[float],
    start_date: date = date(2026, 1, 1),
) -> pd.DataFrame:
    """종가 리스트로부터 합성 OHLCV DataFrame을 생성한다.

    open/high/low는 close 기반으로 단순 산출한다.
    """
    rows: list[dict[str, object]] = []
    for i, close in enumerate(prices):
        d = start_date + timedelta(days=i)
        rows.append(
            {
                "date": d.isoformat(),
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 100_000,
            }
        )
    return pd.DataFrame(rows)


def _make_strategy() -> MovingAverageStrategy:
    return MovingAverageStrategy(short_period=5, long_period=20)


def _make_config() -> BacktestConfig:
    return BacktestConfig(initial_capital=10_000_000)


class TestRunBasic:
    """test_run_basic — 50일 합성 데이터로 기본 실행을 검증한다."""

    def test_run_basic(self) -> None:
        # 50일간 10000원에서 완만하게 상승하는 데이터
        prices = [10_000 + i * 50 for i in range(50)]
        data = _make_ohlcv(prices)

        engine = BacktestEngine(strategy=_make_strategy(), config=_make_config())
        result = engine.run(data, stock_code="005930")

        # BacktestResult에 equity_curve와 trade_log가 존재해야 한다
        assert result.equity_curve is not None
        assert isinstance(result.equity_curve, list)
        assert len(result.equity_curve) > 0

        assert result.trade_log is not None
        assert isinstance(result.trade_log, list)

        # 기본 메타 필드 검증
        assert result.strategy_name == _make_strategy().name
        assert result.stock_code == "005930"
        assert result.initial_capital == 10_000_000


class TestRunInsufficientData:
    """test_run_insufficient_data — 데이터가 부족하면 ValueError."""

    def test_run_insufficient_data(self) -> None:
        prices = [10_000 + i * 10 for i in range(10)]
        data = _make_ohlcv(prices)

        engine = BacktestEngine(strategy=_make_strategy(), config=_make_config())

        with pytest.raises(ValueError, match="데이터 부족"):
            engine.run(data, stock_code="005930")


class TestGoldenCrossTriggersBuy:
    """test_golden_cross_triggers_buy — 골든크로스 시 매수가 발생한다."""

    def test_golden_cross_triggers_buy(self) -> None:
        # 20일 하락 → 15일 급상승 (총 35일)
        # 하락 구간: 장기 MA가 단기 MA 위에 위치하도록
        declining = [10_000 - i * 100 for i in range(20)]  # 10000 → 8100
        # 상승 구간: 단기 MA가 장기 MA를 빠르게 돌파하도록 급상승
        last_declining = declining[-1]  # 8100
        rising = [last_declining + (i + 1) * 300 for i in range(15)]  # 8400 → 12600

        prices = declining + rising
        data = _make_ohlcv(prices)

        engine = BacktestEngine(strategy=_make_strategy(), config=_make_config())
        result = engine.run(data, stock_code="005930")

        # 매수(BUY) 거래가 최소 1건 존재해야 한다
        buy_trades = [t for t in result.trade_log if t.side == TradeSide.BUY]
        assert len(buy_trades) >= 1, (
            f"골든크로스 구간에서 매수가 발생해야 합니다. trade_log={result.trade_log}"
        )


class TestStopLossTriggersSell:
    """test_stop_loss_triggers_sell — 매수 후 5% 하락 시 손절 매도."""

    def test_stop_loss_triggers_sell(self) -> None:
        # Phase 1: 20일 하락 → 장기 MA > 단기 MA 확립
        declining = [10_000 - i * 100 for i in range(20)]  # 10000 → 8100

        # Phase 2: 급상승으로 골든크로스 유도, 하지만 짧게 유지
        base = declining[-1]  # 8100
        rising = [base + (i + 1) * 300 for i in range(5)]  # 8400 → 9600

        # Phase 3: 골든크로스 후 매수 발생, 바로 다음 날부터 급락
        # 매수가 ≈ 마지막 상승 가격 * 1.001 (슬리피지)
        # 급락: 한번에 크게 떨어뜨려 익절(5% 상승) 전에 손절(3% 하락)이 먼저 발동
        peak = rising[-1]  # 9600
        # 매수가 약 9610. 손절선 = 9610 * 0.97 = 9322
        # 첫날부터 크게 떨어뜨림
        sharp_decline = [int(peak * 0.90)] * 10  # 8640 — 즉시 10%+ 하락

        prices = declining + rising + sharp_decline
        data = _make_ohlcv(prices)

        config = _make_config()
        # max_loss_rate 기본값 0.03 사용
        engine = BacktestEngine(strategy=_make_strategy(), config=config)
        result = engine.run(data, stock_code="005930")

        # 매수가 발생했는지 확인
        buy_trades = [t for t in result.trade_log if t.side == TradeSide.BUY]
        assert len(buy_trades) >= 1, "골든크로스에서 매수가 발생해야 합니다."

        # 손절 매도가 발생했는지 확인
        # 브로커의 sell에 reason이 전달되지만 TradeRecord에는 reason 필드가 없으므로,
        # 매도가 발생했고 손실(profit_loss < 0)인 거래를 확인한다.
        sell_trades = [t for t in result.trade_log if t.side == TradeSide.SELL]
        assert len(sell_trades) >= 1, "손절 매도가 발생해야 합니다."

        # 손절 매도는 손실이 발생한 거래여야 한다
        loss_sells = [t for t in sell_trades if t.profit_loss < 0]
        assert len(loss_sells) >= 1, (
            f"손절로 인한 손실 매도가 있어야 합니다. sells={sell_trades}"
        )
