"""리스크 관리 모듈 테스트."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.strategy.base import Signal, SignalType
from src.strategy.risk import RiskManager
from src.utils.exceptions import RiskLimitError


class TestMarketCloseGuardTimezone:
    """마감 임박 판정이 시장 타임존을 쓰는지 — US 개장 직후 매수 차단 버그 회귀."""

    def test_tz_stored(self) -> None:
        assert RiskManager(tz="America/New_York")._mkt_tz == ZoneInfo("America/New_York")
        assert RiskManager()._mkt_tz is None  # 기본(KRX 하위호환)

    def test_explicit_now_cutoff_in_market_tz(self) -> None:
        rm = RiskManager(tz="America/New_York")  # 컷오프 14:30
        # ET 09:54 개장 직후 → 컷오프 전 → 차단 아님
        et_open = datetime(2026, 6, 18, 9, 54, tzinfo=ZoneInfo("America/New_York"))
        assert rm.is_near_market_close(et_open) is False
        # ET 15:00 → 컷오프 후 → 마감 임박
        et_late = datetime(2026, 6, 18, 15, 0, tzinfo=ZoneInfo("America/New_York"))
        assert rm.is_near_market_close(et_late) is True

    def test_default_now_uses_market_tz_not_system(self) -> None:
        """now 미지정 시 datetime.now(market_tz) 호출 — 시스템 KST 아닌 ET 기준."""
        rm = RiskManager(tz="America/New_York")
        et_open = datetime(2026, 6, 18, 9, 54, tzinfo=ZoneInfo("America/New_York"))
        with patch("src.strategy.risk.datetime") as mock_dt:
            mock_dt.now.return_value = et_open
            assert rm.is_near_market_close() is False
            mock_dt.now.assert_called_once_with(ZoneInfo("America/New_York"))


class TestCheckMaxLoss:
    """RiskManager.check_max_loss 테스트."""

    def setup_method(self) -> None:
        """테스트 설정."""
        self.rm = RiskManager(max_loss_rate=0.03)

    def test_within_limit(self) -> None:
        """손실률이 제한 이내이면 False를 반환한다."""
        # 2% 손실
        assert self.rm.check_max_loss(current_price=9800.0, avg_price=10000.0) is False

    def test_exceeds_limit(self) -> None:
        """손실률이 제한을 초과하면 True를 반환한다."""
        # 5% 손실
        assert self.rm.check_max_loss(current_price=9500.0, avg_price=10000.0) is True

    def test_exact_boundary(self) -> None:
        """정확히 3% 손실은 제한을 초과하지 않는다."""
        assert self.rm.check_max_loss(current_price=9700.0, avg_price=10000.0) is False

    def test_just_above_limit(self) -> None:
        """3%를 약간 초과하면 True를 반환한다."""
        assert self.rm.check_max_loss(current_price=9699.0, avg_price=10000.0) is True

    def test_profit_is_within_limit(self) -> None:
        """수익 상태이면 False를 반환한다."""
        assert self.rm.check_max_loss(current_price=10500.0, avg_price=10000.0) is False

    def test_zero_avg_price_raises(self) -> None:
        """평균 매입가가 0이면 RiskLimitError가 발생한다."""
        with pytest.raises(RiskLimitError, match="0보다 커야"):
            self.rm.check_max_loss(current_price=100.0, avg_price=0.0)


class TestCalculatePositionSize:
    """RiskManager.calculate_position_size 테스트."""

    def setup_method(self) -> None:
        """테스트 설정."""
        self.rm = RiskManager(max_position_ratio=0.2)

    def test_basic_calculation(self) -> None:
        """기본 포지션 사이징을 계산한다."""
        # 잔고 1,000,000 * 20% = 200,000 / 가격 10,000 = 20주
        quantity = self.rm.calculate_position_size(
            total_balance=1_000_000.0, price=10_000.0
        )
        assert quantity == 20

    def test_fractional_truncated(self) -> None:
        """소수점은 버림한다."""
        # 200,000 / 30,000 = 6.67 -> 6주
        quantity = self.rm.calculate_position_size(
            total_balance=1_000_000.0, price=30_000.0
        )
        assert quantity == 6

    def test_price_exceeds_max_investment(self) -> None:
        """주가가 최대 투자금보다 크면 0을 반환한다."""
        # 200,000 / 300,000 = 0.67 -> 0주
        quantity = self.rm.calculate_position_size(
            total_balance=1_000_000.0, price=300_000.0
        )
        assert quantity == 0

    def test_zero_balance_raises(self) -> None:
        """잔고가 0이면 RiskLimitError가 발생한다."""
        with pytest.raises(RiskLimitError, match="잔고"):
            self.rm.calculate_position_size(total_balance=0.0, price=10_000.0)

    def test_zero_price_raises(self) -> None:
        """주가가 0이면 RiskLimitError가 발생한다."""
        with pytest.raises(RiskLimitError, match="주가"):
            self.rm.calculate_position_size(total_balance=1_000_000.0, price=0.0)

    def test_min_quantity_floor_overseas(self) -> None:
        """min_quantity=1이면 예산×비율<주가인 고가주도 0 대신 최소 1주를 반환한다.

        US: 예산$1000×0.1=$100 < AAPL $200 → int(100/200)=0이지만 1주 플로어로
        BUY 신호의 영구 차단(false-block)을 막는다. 실제 상한은 호출부 buyable이 캡.
        """
        rm = RiskManager(max_position_ratio=0.1)
        qty = rm.calculate_position_size(
            total_balance=1000.0, price=200.0, min_quantity=1
        )
        assert qty == 1

    def test_min_quantity_default_zero_unchanged(self) -> None:
        """min_quantity 기본값(0)이면 고가주는 기존대로 0을 반환한다(KRX 불변)."""
        rm = RiskManager(max_position_ratio=0.1)
        qty = rm.calculate_position_size(total_balance=1000.0, price=200.0)
        assert qty == 0

    def test_min_quantity_floor_does_not_cap_larger_qty(self) -> None:
        """저가주는 플로어보다 큰 비율 기반 수량을 그대로 반환한다."""
        rm = RiskManager(max_position_ratio=0.1)
        # 1000*0.1=100 / 5 = 20주 (플로어 1보다 큼)
        qty = rm.calculate_position_size(
            total_balance=1000.0, price=5.0, min_quantity=1
        )
        assert qty == 20


class TestRecordTradeResultPrecision:
    """record_trade_result의 손익 정밀도(US 센트) 회귀 — int 절단 제거(H4)."""

    def test_sub_dollar_loss_counts_as_consecutive_loss(self) -> None:
        """1달러 미만 USD 손실도 연패 카운터를 증가시킨다.

        과거 int() 절단 시 int(-0.50)=0이라 ``< 0`` 분기가 거짓 → 연패 미집계로
        MAX_CONSECUTIVE_LOSSES 서킷이 US에서 약화됐다.
        """
        rm = RiskManager()
        rm.record_trade_result(-0.50)
        assert rm.consecutive_losses == 1

    def test_sub_dollar_pnl_accumulates(self) -> None:
        """센트 단위 손익이 누적PnL에 보존된다(절단 없음)."""
        rm = RiskManager()
        rm.record_trade_result(-0.50)
        rm.record_trade_result(-0.25)
        assert rm.daily_cumulative_pnl == pytest.approx(-0.75)

    def test_sub_dollar_profit_resets_consecutive(self) -> None:
        """1달러 미만 USD 이익도 연패를 리셋한다(>0 분기 정상 동작)."""
        rm = RiskManager()
        rm.record_trade_result(-1.0)
        rm.record_trade_result(0.30)
        assert rm.consecutive_losses == 0

    def test_integer_input_unchanged_for_krx(self) -> None:
        """정수 손익(KRX)은 정수 타입으로 누적된다(바이트 불변).

        프로덕션 경로처럼 reset_daily_risk()(int 0 시드)가 첫 기록 전에 돌면 KRX
        누적기가 int로 유지됨을 타입까지 검증(==만으로는 float -10000.0도 통과).
        """
        rm = RiskManager()
        rm.reset_daily_risk()
        rm.record_trade_result(-10_000)
        assert rm.daily_cumulative_pnl == -10_000
        assert isinstance(rm.daily_cumulative_pnl, int)
        assert rm.consecutive_losses == 1


class TestCheckDailyTradeLimit:
    """RiskManager.check_daily_trade_limit 테스트."""

    def setup_method(self) -> None:
        """테스트 설정."""
        self.rm = RiskManager(daily_trade_limit=10)

    def test_within_limit(self) -> None:
        """매매 횟수가 제한 이내이면 False를 반환한다."""
        assert self.rm.check_daily_trade_limit(trade_count=5) is False

    def test_at_limit(self) -> None:
        """매매 횟수가 제한과 같으면 True를 반환한다."""
        assert self.rm.check_daily_trade_limit(trade_count=10) is True

    def test_exceeds_limit(self) -> None:
        """매매 횟수가 제한을 초과하면 True를 반환한다."""
        assert self.rm.check_daily_trade_limit(trade_count=15) is True

    def test_zero_trades(self) -> None:
        """매매 횟수가 0이면 False를 반환한다."""
        assert self.rm.check_daily_trade_limit(trade_count=0) is False


class TestShouldStopLoss:
    """RiskManager.should_stop_loss 테스트."""

    def setup_method(self) -> None:
        """테스트 설정."""
        self.rm = RiskManager(max_loss_rate=0.03)

    def test_should_stop_loss(self) -> None:
        """손실률이 최대 손실률 이상이면 True를 반환한다."""
        # 5% 손실
        assert self.rm.should_stop_loss(current_price=9500.0, avg_price=10000.0) is True

    def test_should_not_stop_loss(self) -> None:
        """손실률이 최대 손실률 미만이면 False를 반환한다."""
        # 1% 손실
        assert self.rm.should_stop_loss(current_price=9900.0, avg_price=10000.0) is False

    def test_exact_boundary_stop_loss(self) -> None:
        """정확히 3% 손실이면 손절한다."""
        assert self.rm.should_stop_loss(current_price=9700.0, avg_price=10000.0) is True

    def test_zero_avg_price(self) -> None:
        """평균 매입가가 0이면 False를 반환한다."""
        assert self.rm.should_stop_loss(current_price=100.0, avg_price=0.0) is False


class TestShouldTakeProfit:
    """RiskManager.should_take_profit 테스트."""

    def setup_method(self) -> None:
        """테스트 설정 — 시간 의존성 격리(마감임박 조정 기본 False)."""
        self.rm = RiskManager(take_profit_ratio=0.05)
        self.rm.is_near_market_close = lambda *a, **kw: False  # type: ignore[method-assign]

    def test_should_take_profit(self) -> None:
        """수익률이 목표 이상이면 True를 반환한다."""
        # 10% 수익
        assert self.rm.should_take_profit(current_price=11000.0, avg_price=10000.0) is True

    def test_should_not_take_profit(self) -> None:
        """수익률이 목표 미만이면 False를 반환한다."""
        # 2% 수익
        assert self.rm.should_take_profit(current_price=10200.0, avg_price=10000.0) is False

    def test_exact_boundary_take_profit(self) -> None:
        """정확히 5% 수익이면 익절한다."""
        assert self.rm.should_take_profit(current_price=10500.0, avg_price=10000.0) is True

    def test_custom_profit_ratio(self) -> None:
        """사용자 지정 익절 비율을 사용한다."""
        # 10% 수익, 목표 15%
        assert self.rm.should_take_profit(
            current_price=11000.0, avg_price=10000.0, profit_ratio=0.15
        ) is False

    def test_zero_avg_price(self) -> None:
        """평균 매입가가 0이면 False를 반환한다."""
        assert self.rm.should_take_profit(current_price=100.0, avg_price=0.0) is False


class TestShouldBreakevenStop:
    """RiskManager.should_breakeven_stop 테스트 (본전 스톱)."""

    def setup_method(self) -> None:
        self.rm = RiskManager(breakeven_activation_ratio=0.02)

    def test_armed_and_returned_to_entry_sells(self) -> None:
        # 고점 +3%(무장) 후 진입가 이하 회귀 → True
        assert self.rm.should_breakeven_stop(9990.0, 10000.0, 10300.0) is True

    def test_above_entry_no_sell(self) -> None:
        # 아직 진입가 위 → False
        assert self.rm.should_breakeven_stop(10100.0, 10000.0, 10300.0) is False

    def test_never_armed_no_sell(self) -> None:
        # 고점 +1.5%(무장<2%) → False
        assert self.rm.should_breakeven_stop(9990.0, 10000.0, 10150.0) is False

    def test_disabled(self) -> None:
        rm = RiskManager(breakeven_activation_ratio=0.0)
        assert rm.should_breakeven_stop(9990.0, 10000.0, 10300.0) is False


class TestShouldStagnationExit:
    """RiskManager.should_stagnation_exit 테스트 (정체 청산)."""

    def setup_method(self) -> None:
        self.rm = RiskManager(stagnation_hours=3.0, trailing_activation_ratio=0.05)

    def test_long_held_no_progress_sells(self) -> None:
        # 200분 보유 + 고점 +2%(무장<5%) → True
        assert self.rm.should_stagnation_exit(10000.0, 10200.0, 200.0) is True

    def test_not_long_enough_no_sell(self) -> None:
        assert self.rm.should_stagnation_exit(10000.0, 10200.0, 60.0) is False

    def test_armed_position_not_stagnant(self) -> None:
        # 고점 +6%(무장)면 트레일링이 관리 → 정체 제외
        assert self.rm.should_stagnation_exit(10000.0, 10600.0, 200.0) is False

    def test_disabled(self) -> None:
        rm = RiskManager(stagnation_hours=0.0, trailing_activation_ratio=0.05)
        assert rm.should_stagnation_exit(10000.0, 10200.0, 999.0) is False


class TestValidateOrder:
    """RiskManager.validate_order 테스트."""

    def setup_method(self) -> None:
        """테스트 설정 — 시간 의존성 격리(MARKET_CLOSE_GUARD 기본 False)."""
        self.rm = RiskManager(min_confidence=0.1)
        self.rm.is_near_market_close = lambda *a, **kw: False  # type: ignore[method-assign]

    def test_hold_signal_returns_false(self) -> None:
        """HOLD 시그널은 False를 반환한다."""
        signal = Signal(signal_type=SignalType.HOLD, confidence=0.0)
        assert self.rm.validate_order(signal, balance=1_000_000.0, current_positions=0) is False

    def test_buy_with_sufficient_balance(self) -> None:
        """잔고가 충분한 매수 시그널은 True를 반환한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50000.0,
        )
        assert self.rm.validate_order(signal, balance=1_000_000.0, current_positions=0) is True

    def test_buy_with_zero_balance_raises(self) -> None:
        """잔고가 0인 매수 시그널은 RiskLimitError가 발생한다."""
        signal = Signal(signal_type=SignalType.BUY, confidence=0.8, target_price=50000.0)
        with pytest.raises(RiskLimitError, match="잔고"):
            self.rm.validate_order(signal, balance=0.0, current_positions=0)

    def test_buy_with_insufficient_balance_raises(self) -> None:
        """잔고가 부족한 매수 시그널은 RiskLimitError가 발생한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=100_000.0,
        )
        with pytest.raises(RiskLimitError, match="잔고 부족"):
            self.rm.validate_order(signal, balance=50_000.0, current_positions=0)

    def test_low_confidence_returns_false(self) -> None:
        """신뢰도가 낮은 시그널은 False를 반환한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.05,
            target_price=50000.0,
        )
        assert self.rm.validate_order(signal, balance=1_000_000.0, current_positions=0) is False

    def test_sell_signal_validated(self) -> None:
        """매도 시그널도 검증된다."""
        signal = Signal(
            signal_type=SignalType.SELL,
            confidence=0.7,
            target_price=50000.0,
        )
        assert self.rm.validate_order(signal, balance=1_000_000.0, current_positions=1) is True


class TestCheckBuyGates:
    """RiskManager.check_buy_gates 테스트 (proposal 2026-05-18)."""

    def setup_method(self) -> None:
        """테스트 설정 — 시간 의존성 격리(MARKET_CLOSE_GUARD 기본 False)."""
        self.rm = RiskManager()
        self.rm.is_near_market_close = lambda *a, **kw: False  # type: ignore[method-assign]

    def test_all_gates_pass_returns_none(self) -> None:
        """모든 게이트 통과 시 None을 반환한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50_000.0,
        )
        assert self.rm.check_buy_gates(signal, balance=1_000_000.0) is None

    def test_non_buy_signal_returns_none(self) -> None:
        """BUY 시그널이 아니면 None을 반환한다."""
        sell_signal = Signal(
            signal_type=SignalType.SELL,
            confidence=0.8,
            target_price=50_000.0,
        )
        hold_signal = Signal(signal_type=SignalType.HOLD, confidence=0.0)
        assert self.rm.check_buy_gates(sell_signal, balance=1_000_000.0) is None
        assert self.rm.check_buy_gates(hold_signal, balance=1_000_000.0) is None

    def test_low_confidence_returns_code(self) -> None:
        """저신뢰도 시 'LOW_CONFIDENCE'를 반환한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.001,  # min_confidence보다 낮음
            target_price=50_000.0,
        )
        assert self.rm.check_buy_gates(signal, balance=1_000_000.0) == "LOW_CONFIDENCE"

    def test_zero_balance_returns_insufficient_cash(self) -> None:
        """잔고 0 시 'INSUFFICIENT_CASH'를 반환한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50_000.0,
        )
        assert self.rm.check_buy_gates(signal, balance=0.0) == "INSUFFICIENT_CASH"

    def test_target_exceeds_balance_returns_insufficient_cash(self) -> None:
        """목표가가 잔고를 초과하면 'INSUFFICIENT_CASH'를 반환한다."""
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=200_000.0,
        )
        assert self.rm.check_buy_gates(signal, balance=50_000.0) == "INSUFFICIENT_CASH"

    def test_consecutive_losses_halt_returns_specific_code(self) -> None:
        """연패 누적으로 halt된 경우 'MAX_CONSECUTIVE_LOSSES'를 반환한다."""
        rm = RiskManager()
        for _ in range(rm._max_consecutive_losses):
            rm.record_trade_result(-10_000)
        assert rm.is_portfolio_halted is True
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50_000.0,
        )
        assert (
            rm.check_buy_gates(signal, balance=1_000_000.0)
            == "MAX_CONSECUTIVE_LOSSES"
        )

    def test_daily_drawdown_halt_returns_specific_code(self) -> None:
        """일일 MDD로 halt된 경우 'MAX_DAILY_DRAWDOWN'을 반환한다.

        순손실 가드(2026-05-21 proposal) 반영: 피크 대비 회수폭이 한도를 넘더라도
        당일 누적이 순손실(<0)일 때만 halt하므로, 순손실 시나리오로 검증한다."""
        rm = RiskManager()
        # 피크 만들기 → 순손실 전환 + MDD 임계치 이상 하락
        rm.record_trade_result(+100_000)  # peak +100k
        rm.record_trade_result(-150_000)  # 누적 -50k(순손실), drawdown 150% (5% 초과)
        assert rm.is_portfolio_halted is True
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50_000.0,
        )
        assert (
            rm.check_buy_gates(signal, balance=1_000_000.0)
            == "MAX_DAILY_DRAWDOWN"
        )

    def test_halt_takes_priority_over_other_gates(self) -> None:
        """포트폴리오 halt가 최우선 게이트로 반환된다."""
        rm = RiskManager()
        for _ in range(rm._max_consecutive_losses):
            rm.record_trade_result(-10_000)
        # 낮은 신뢰도 + 0 잔고이지만 halt가 먼저 트립
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.001,
            target_price=10_000.0,
        )
        assert (
            rm.check_buy_gates(signal, balance=0.0)
            == "MAX_CONSECUTIVE_LOSSES"
        )

    def test_market_close_returns_market_close_guard(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """장 마감 임박 시 'MARKET_CLOSE_GUARD'를 반환한다."""
        rm = RiskManager()
        # is_near_market_close를 True로 모킹
        monkeypatch.setattr(rm, "is_near_market_close", lambda *a, **kw: True)
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50_000.0,
        )
        assert (
            rm.check_buy_gates(signal, balance=1_000_000.0)
            == "MARKET_CLOSE_GUARD"
        )

    def test_market_close_priority_after_halt_before_cash(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """우선순위: halt > MARKET_CLOSE_GUARD > INSUFFICIENT_CASH > LOW_CONFIDENCE."""
        rm = RiskManager()
        monkeypatch.setattr(rm, "is_near_market_close", lambda *a, **kw: True)
        # 마감 임박 + 잔고 0 — MARKET_CLOSE_GUARD가 우선
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.001,
            target_price=10_000.0,
        )
        assert (
            rm.check_buy_gates(signal, balance=0.0)
            == "MARKET_CLOSE_GUARD"
        )

    def test_reset_daily_risk_clears_halt_reason(self) -> None:
        """reset_daily_risk가 halt_reason도 초기화한다."""
        for _ in range(self.rm._max_consecutive_losses):
            self.rm.record_trade_result(-10_000)
        assert self.rm.is_portfolio_halted is True
        self.rm.reset_daily_risk()
        signal = Signal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            target_price=50_000.0,
        )
        assert self.rm.check_buy_gates(signal, balance=1_000_000.0) is None


class TestShouldTrailingStop:
    """고점 대비 되돌림 청산 판정."""

    def setup_method(self) -> None:
        self.rm = RiskManager(
            trailing_activation_ratio=0.05, trailing_drawdown_ratio=0.05
        )

    def test_not_armed_returns_false(self) -> None:
        # 고점이 활성화 임계(+5%) 미만 → 미무장
        assert self.rm.should_trailing_stop(10_300, 10_000, 10_300) is False

    def test_armed_but_drawdown_insufficient(self) -> None:
        # 무장(고점 +27%), 되돌림 2%만 → 미달
        assert self.rm.should_trailing_stop(12_446, 10_000, 12_700) is False

    def test_armed_and_drawdown_triggers(self) -> None:
        # 무장(고점 +27%), 고점 대비 5% 되돌림 경계
        assert self.rm.should_trailing_stop(12_065, 10_000, 12_700) is True

    def test_zero_guard(self) -> None:
        assert self.rm.should_trailing_stop(100, 0, 100) is False
        assert self.rm.should_trailing_stop(100, 10_000, 0) is False


class TestShouldCloseForMarketEnd:
    """마감 임박 강제 청산 게이트 (이익 포지션 한정)."""

    def setup_method(self) -> None:
        self.rm = RiskManager(min_profitable_close=0.015)

    def test_not_near_close_returns_false(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: False  # type: ignore[method-assign]
        assert self.rm.should_close_for_market_end(10_200, 10_000) is False

    def test_near_close_profit_below_min(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        # +1.0% < 1.5%
        assert self.rm.should_close_for_market_end(10_100, 10_000) is False

    def test_near_close_profit_meets_min(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        # +1.5% 경계
        assert self.rm.should_close_for_market_end(10_150, 10_000) is True

    def test_near_close_loss_excluded(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        # 손실 포지션은 게이트 대상 아님
        assert self.rm.should_close_for_market_end(9_500, 10_000) is False

    def test_zero_guard(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        assert self.rm.should_close_for_market_end(100, 0) is False


class TestDailyDrawdownNetLossGuard:
    """일일 MDD halt 순손실 가드 (proposal 2026-05-21, 안 a).

    피크 대비 회수폭이 한도를 넘더라도 당일 누적이 순손실(<0)일 때만 halt한다.
    흑자 구간의 '첫 익절 → 손절' 오발동을 제거하되, 실제 순손실 구간의 손실
    한도는 보존한다."""

    def test_take_profit_then_stop_loss_no_halt_when_net_positive(self) -> None:
        """+39,440 익절 후 -24,300 손절 → 순익 +15,140 흑자이므로 halt 안 됨 (회귀 케이스)."""
        rm = RiskManager()
        rm.record_trade_result(+39_440)  # peak +39,440
        rm.record_trade_result(-24_300)  # 누적 +15,140 (흑자), 피크 대비 61.6%
        assert rm.is_portfolio_halted is False
        assert rm._halt_reason is None

    def test_drawdown_halt_triggers_when_net_negative(self) -> None:
        """순손실 상태에서 피크 대비 회수폭이 한도 초과 → MDD halt (기존 의도 보존)."""
        rm = RiskManager()
        rm.record_trade_result(+39_440)   # peak +39,440
        rm.record_trade_result(-60_000)   # 누적 -20,560 (순손실), 피크 대비 >5%
        assert rm.is_portfolio_halted is True
        assert rm._halt_reason == "MAX_DAILY_DRAWDOWN"

    def test_consecutive_loss_halt_unaffected(self) -> None:
        """연패 한도 halt 경로는 순손실 가드의 영향을 받지 않는다."""
        rm = RiskManager()
        for _ in range(rm._max_consecutive_losses):
            rm.record_trade_result(-10_000)
        assert rm.is_portfolio_halted is True
        assert rm._halt_reason == "MAX_CONSECUTIVE_LOSSES"


class TestMaxDailyLossAbs:
    """일일 절대 손실 하한 — 이익 피크 없는 straight-loss day 가드.

    MDD 가드는 ``daily_peak_pnl > 0``이 전제라 첫 매도부터 손실인 날은 영구
    비무장이었다(2026-07-03 감사: 최악일 6/16 -20,890원 9패에 halt 발동 0건).
    피크와 무관한 절대 하한(MAX_DAILY_LOSS_ABS, 0=비활성)으로 공백을 메운다.
    """

    def test_halts_on_absolute_loss_without_profit_peak(self) -> None:
        """이익 피크가 없어도 누적 손실이 절대 하한 도달 시 halt된다."""
        rm = RiskManager()
        rm._max_daily_loss_abs = 30_000
        rm.record_trade_result(-15_000)
        assert rm.is_portfolio_halted is False  # -30k 미도달
        rm.record_trade_result(-16_000)  # 누적 -31k (피크는 여전히 0)
        assert rm.is_portfolio_halted is True
        signal = Signal(
            signal_type=SignalType.BUY, confidence=0.8, target_price=50_000.0,
        )
        assert (
            rm.check_buy_gates(signal, balance=1_000_000.0) == "MAX_DAILY_LOSS_ABS"
        )

    def test_disabled_by_default_zero(self) -> None:
        """기본값 0이면 절대 하한 가드는 비활성이다(기존 동작 보존)."""
        rm = RiskManager()
        assert rm._max_daily_loss_abs == 0
        rm.record_trade_result(-1_000_000)  # 연패 1, 피크 0 → 기존 가드 미발동
        assert rm.is_portfolio_halted is False

    def test_snapshot_restore_preserves_halt(self) -> None:
        """절대 하한 halt 상태가 snapshot/restore로 복원된다(재시작 무력화 방지)."""
        rm = RiskManager()
        rm._max_daily_loss_abs = 30_000
        rm.record_trade_result(-31_000)
        assert rm.is_portfolio_halted is True

        rm2 = RiskManager()
        rm2.restore(rm.snapshot())
        assert rm2.is_portfolio_halted is True
        signal = Signal(
            signal_type=SignalType.BUY, confidence=0.8, target_price=50_000.0,
        )
        assert (
            rm2.check_buy_gates(signal, balance=1_000_000.0) == "MAX_DAILY_LOSS_ABS"
        )
