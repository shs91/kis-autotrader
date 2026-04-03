"""VirtualBroker 단위 테스트."""

from __future__ import annotations

import pytest

from src.backtest.broker import (
    BacktestConfig,
    TradeSide,
    VirtualBroker,
)

# 계산이 쉽도록 고정 설정
CONFIG = BacktestConfig(
    initial_capital=10_000_000,
    commission_rate=0.001,       # 0.1% — 계산 편의
    slippage_rate=0.01,          # 1%   — 계산 편의
    max_position_ratio=0.2,      # 20%
    max_loss_rate=0.03,          # 3%
    take_profit_ratio=0.05,      # 5%
)


@pytest.fixture()
def broker() -> VirtualBroker:
    """고정 설정의 VirtualBroker를 반환한다."""
    return VirtualBroker(config=CONFIG)


# ------------------------------------------------------------------
# 1. test_buy_basic
# ------------------------------------------------------------------

class TestBuyBasic:
    """매수 기본 동작을 검증한다."""

    def test_buy_creates_position_and_deducts_cash(
        self, broker: VirtualBroker
    ) -> None:
        """매수 시 포지션 생성, 현금 차감, 거래 기록 추가."""
        price = 10_000.0
        record = broker.buy("005930", price, "2026-04-01")

        assert record is not None
        assert record.side == TradeSide.BUY
        assert record.stock_code == "005930"

        # 슬리피지 반영 체결가: 10_000 * 1.01 = 10_100
        adjusted = price * (1 + CONFIG.slippage_rate)
        assert record.price == pytest.approx(adjusted)

        # 투자가능 = 10_000_000 * 0.2 = 2_000_000
        # 수량 = int(2_000_000 / 10_100) = 198
        expected_qty = int(10_000_000 * 0.2 / adjusted)
        assert record.quantity == expected_qty

        # 수수료 = 10_100 * 198 * 0.001
        expected_commission = adjusted * expected_qty * CONFIG.commission_rate
        assert record.commission == pytest.approx(expected_commission)

        # 현금 차감 확인
        total_cost = adjusted * expected_qty + expected_commission
        assert broker.cash == pytest.approx(10_000_000 - total_cost)

        # 포지션 존재 확인
        assert "005930" in broker.positions
        pos = broker.positions["005930"]
        assert pos.quantity == expected_qty
        assert pos.avg_price == pytest.approx(adjusted)
        assert pos.entry_date == "2026-04-01"


# ------------------------------------------------------------------
# 2. test_buy_insufficient_cash
# ------------------------------------------------------------------

class TestBuyInsufficientCash:
    """자본금이 극히 적어 매수 불가인 경우 None을 반환한다."""

    def test_tiny_capital_returns_none(self) -> None:
        tiny_config = BacktestConfig(
            initial_capital=100,          # 100원
            commission_rate=0.001,
            slippage_rate=0.01,
            max_position_ratio=0.2,
            max_loss_rate=0.03,
            take_profit_ratio=0.05,
        )
        broker = VirtualBroker(config=tiny_config)
        result = broker.buy("005930", 50_000.0, "2026-04-01")

        assert result is None
        assert broker.cash == pytest.approx(100.0)
        assert len(broker.positions) == 0


# ------------------------------------------------------------------
# 3. test_buy_already_held
# ------------------------------------------------------------------

class TestBuyAlreadyHeld:
    """이미 보유 중인 종목을 재매수하면 None을 반환한다."""

    def test_second_buy_same_stock_returns_none(
        self, broker: VirtualBroker
    ) -> None:
        first = broker.buy("005930", 10_000.0, "2026-04-01")
        assert first is not None

        second = broker.buy("005930", 11_000.0, "2026-04-02")
        assert second is None

        # 포지션은 첫 매수 그대로
        assert broker.positions["005930"].quantity == first.quantity


# ------------------------------------------------------------------
# 4. test_sell_basic
# ------------------------------------------------------------------

class TestSellBasic:
    """매도 기본 동작 — 포지션 제거, 현금 증가, 손익 기록."""

    def test_sell_removes_position_and_adds_cash(
        self, broker: VirtualBroker
    ) -> None:
        buy_record = broker.buy("005930", 10_000.0, "2026-04-01")
        assert buy_record is not None
        cash_after_buy = broker.cash

        sell_record = broker.sell("005930", 12_000.0, "2026-04-03")
        assert sell_record is not None
        assert sell_record.side == TradeSide.SELL
        assert sell_record.stock_code == "005930"

        # 매도 슬리피지: 12_000 * (1 - 0.01) = 11_880
        sell_adjusted = 12_000.0 * (1 - CONFIG.slippage_rate)
        assert sell_record.price == pytest.approx(sell_adjusted)

        # 포지션 제거 확인
        assert "005930" not in broker.positions

        # 현금 증가 확인
        qty = buy_record.quantity
        commission = sell_adjusted * qty * CONFIG.commission_rate
        proceeds = sell_adjusted * qty - commission
        assert broker.cash == pytest.approx(cash_after_buy + proceeds)

        # 손익 확인
        expected_pl = (sell_adjusted - buy_record.price) * qty - commission
        assert sell_record.profit_loss == pytest.approx(expected_pl)

        # 수익률 확인 (매수 단가 기준)
        expected_rate = (sell_adjusted - buy_record.price) / buy_record.price * 100
        assert sell_record.profit_rate == pytest.approx(expected_rate)


# ------------------------------------------------------------------
# 5. test_sell_not_held
# ------------------------------------------------------------------

class TestSellNotHeld:
    """미보유 종목 매도 시 None을 반환한다."""

    def test_sell_nonexistent_returns_none(
        self, broker: VirtualBroker
    ) -> None:
        result = broker.sell("999999", 10_000.0, "2026-04-01")
        assert result is None
        assert broker.cash == pytest.approx(10_000_000.0)


# ------------------------------------------------------------------
# 6. test_stop_loss_trigger
# ------------------------------------------------------------------

class TestStopLossTrigger:
    """손절 기준(3%) 이상 하락 시 True를 반환한다."""

    def test_loss_at_threshold_returns_true(
        self, broker: VirtualBroker
    ) -> None:
        broker.buy("005930", 10_000.0, "2026-04-01")
        avg = broker.positions["005930"].avg_price  # 10_100

        # 정확히 3% 하락: avg * 0.97
        trigger_price = avg * (1 - CONFIG.max_loss_rate)
        assert broker.check_stop_loss("005930", trigger_price) is True

    def test_loss_beyond_threshold_returns_true(
        self, broker: VirtualBroker
    ) -> None:
        broker.buy("005930", 10_000.0, "2026-04-01")
        avg = broker.positions["005930"].avg_price

        # 5% 하락 — 3% 초과
        assert broker.check_stop_loss("005930", avg * 0.95) is True


# ------------------------------------------------------------------
# 7. test_stop_loss_below_threshold
# ------------------------------------------------------------------

class TestStopLossBelowThreshold:
    """손절 기준 미만 하락 시 False를 반환한다."""

    def test_small_loss_returns_false(
        self, broker: VirtualBroker
    ) -> None:
        broker.buy("005930", 10_000.0, "2026-04-01")
        avg = broker.positions["005930"].avg_price

        # 2% 하락 — 기준(3%) 미달
        assert broker.check_stop_loss("005930", avg * 0.98) is False

    def test_no_position_returns_false(
        self, broker: VirtualBroker
    ) -> None:
        assert broker.check_stop_loss("999999", 5_000.0) is False


# ------------------------------------------------------------------
# 8. test_take_profit_trigger
# ------------------------------------------------------------------

class TestTakeProfitTrigger:
    """익절 기준(5%) 이상 상승 시 True를 반환한다."""

    def test_gain_at_threshold_returns_true(
        self, broker: VirtualBroker
    ) -> None:
        broker.buy("005930", 10_000.0, "2026-04-01")
        avg = broker.positions["005930"].avg_price

        # 정확히 5% 상승
        trigger_price = avg * (1 + CONFIG.take_profit_ratio)
        assert broker.check_take_profit("005930", trigger_price) is True

    def test_gain_beyond_threshold_returns_true(
        self, broker: VirtualBroker
    ) -> None:
        broker.buy("005930", 10_000.0, "2026-04-01")
        avg = broker.positions["005930"].avg_price

        assert broker.check_take_profit("005930", avg * 1.10) is True


# ------------------------------------------------------------------
# 9. test_take_profit_below_threshold
# ------------------------------------------------------------------

class TestTakeProfitBelowThreshold:
    """익절 기준 미만 상승 시 False를 반환한다."""

    def test_small_gain_returns_false(
        self, broker: VirtualBroker
    ) -> None:
        broker.buy("005930", 10_000.0, "2026-04-01")
        avg = broker.positions["005930"].avg_price

        # 3% 상승 — 기준(5%) 미달
        assert broker.check_take_profit("005930", avg * 1.03) is False

    def test_no_position_returns_false(
        self, broker: VirtualBroker
    ) -> None:
        assert broker.check_take_profit("999999", 50_000.0) is False


# ------------------------------------------------------------------
# 10. test_commission_and_slippage
# ------------------------------------------------------------------

class TestCommissionAndSlippage:
    """수수료와 슬리피지가 정확히 계산되는지 검증한다."""

    def test_exact_buy_math(self, broker: VirtualBroker) -> None:
        """매수 시 슬리피지/수수료 수치를 직접 계산하여 비교."""
        price = 50_000.0
        record = broker.buy("035720", price, "2026-04-01")
        assert record is not None

        adjusted = 50_000.0 * 1.01  # 50_500
        investable = 10_000_000 * 0.2  # 2_000_000
        qty = int(investable / adjusted)  # int(2_000_000 / 50_500) = 39
        commission = adjusted * qty * 0.001  # 50_500 * 39 * 0.001 = 1_969.5

        assert record.price == pytest.approx(adjusted)
        assert record.quantity == qty
        assert record.commission == pytest.approx(commission)

    def test_exact_sell_math(self, broker: VirtualBroker) -> None:
        """매도 시 슬리피지/수수료/손익 수치를 직접 계산하여 비교."""
        buy_rec = broker.buy("035720", 50_000.0, "2026-04-01")
        assert buy_rec is not None

        sell_rec = broker.sell("035720", 55_000.0, "2026-04-05")
        assert sell_rec is not None

        sell_adjusted = 55_000.0 * 0.99  # 54_450
        qty = buy_rec.quantity
        sell_commission = sell_adjusted * qty * 0.001

        assert sell_rec.price == pytest.approx(sell_adjusted)
        assert sell_rec.commission == pytest.approx(sell_commission)

        expected_pl = (sell_adjusted - buy_rec.price) * qty - sell_commission
        assert sell_rec.profit_loss == pytest.approx(expected_pl)


# ------------------------------------------------------------------
# 11. test_portfolio_value
# ------------------------------------------------------------------

class TestPortfolioValue:
    """포트폴리오 총 평가액(현금 + 주식 평가)을 검증한다."""

    def test_cash_plus_stock(self, broker: VirtualBroker) -> None:
        buy_rec = broker.buy("005930", 10_000.0, "2026-04-01")
        assert buy_rec is not None

        current_prices = {"005930": 12_000.0}
        expected = broker.cash + buy_rec.quantity * 12_000.0
        assert broker.portfolio_value(current_prices) == pytest.approx(expected)

    def test_cash_only_when_no_positions(self, broker: VirtualBroker) -> None:
        assert broker.portfolio_value({}) == pytest.approx(10_000_000.0)

    def test_missing_price_falls_back_to_avg(
        self, broker: VirtualBroker
    ) -> None:
        """현재가 딕셔너리에 종목이 없으면 avg_price로 평가."""
        buy_rec = broker.buy("005930", 10_000.0, "2026-04-01")
        assert buy_rec is not None

        # 빈 딕셔너리 — avg_price 사용
        expected = broker.cash + buy_rec.quantity * buy_rec.price
        assert broker.portfolio_value({}) == pytest.approx(expected)


# ------------------------------------------------------------------
# 12. test_trade_history
# ------------------------------------------------------------------

class TestTradeHistory:
    """매수/매도 모두 trade_history에 기록되는지 검증한다."""

    def test_records_both_buy_and_sell(
        self, broker: VirtualBroker
    ) -> None:
        broker.buy("005930", 10_000.0, "2026-04-01")
        broker.sell("005930", 11_000.0, "2026-04-03")

        history = broker.trade_history
        assert len(history) == 2
        assert history[0].side == TradeSide.BUY
        assert history[1].side == TradeSide.SELL

    def test_failed_trades_not_recorded(
        self, broker: VirtualBroker
    ) -> None:
        """실패한 매수/매도는 기록에 남지 않는다."""
        broker.sell("999999", 10_000.0, "2026-04-01")  # 미보유
        broker.buy("005930", 10_000.0, "2026-04-01")
        broker.buy("005930", 10_000.0, "2026-04-02")   # 중복

        history = broker.trade_history
        assert len(history) == 1
        assert history[0].side == TradeSide.BUY

    def test_history_is_copy(self, broker: VirtualBroker) -> None:
        """trade_history 프로퍼티는 내부 리스트의 복사본이다."""
        broker.buy("005930", 10_000.0, "2026-04-01")
        h1 = broker.trade_history
        h1.clear()
        assert len(broker.trade_history) == 1
