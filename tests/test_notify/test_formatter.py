"""메시지 포맷팅 테스트."""

from __future__ import annotations

from dataclasses import dataclass

from src.notify.formatter import (
    BuyDetail,
    SellDetail,
    format_buy,
    format_daily_summary,
    format_error,
    format_sell,
    format_system,
)

# ── 테스트용 더미 데이터 ──────────────────────────────────


@dataclass
class _FakeHolding:
    stock_code: str = "005930"
    stock_name: str = "삼성전자"
    quantity: int = 10
    avg_price: float = 70000.0
    current_price: int = 72000
    eval_amount: int = 720000
    profit_loss: int = 20000
    profit_rate: float = 2.86


@dataclass
class _FakeBalance:
    deposit: int = 5000000
    total_eval_amount: int = 12350000
    total_profit_loss: int = 350000
    total_profit_rate: float = 2.92
    holdings: list[_FakeHolding] | None = None
    raw_response: dict | None = None

    def __post_init__(self) -> None:
        if self.holdings is None:
            self.holdings = [_FakeHolding()]
        if self.raw_response is None:
            self.raw_response = {}


@dataclass
class _FakeExecution:
    order_date: str = "20260403"
    order_time: str = "100000"
    stock_code: str = "005930"
    stock_name: str = "삼성전자"
    side: str = "매수"
    quantity: int = 10
    price: int = 72000
    amount: int = 720000
    order_no: str = "0001"


# ── format_buy ────────────────────────────────────────────


class TestFormatBuy:
    """매수 포맷 테스트."""

    def test_basic_info(self) -> None:
        result = format_buy("삼성전자", "005930", 10, 72000)
        assert "[매수]" in result
        assert "삼성전자" in result
        assert "005930" in result
        assert "72,000" in result
        assert "10주" in result

    def test_total_amount(self) -> None:
        result = format_buy("삼성전자", "005930", 10, 72000)
        assert "720,000" in result

    def test_with_detail(self) -> None:
        detail = BuyDetail(
            total_amount=720000,
            strategy="이동평균교차(5/20)",
            reason="골든크로스",
            confidence=0.75,
        )
        result = format_buy("삼성전자", "005930", 10, 72000, detail)
        assert "이동평균교차" in result
        assert "골든크로스" in result
        assert "75%" in result

    def test_without_detail(self) -> None:
        """detail 없이도 기본 정보가 포함된다."""
        result = format_buy("삼성전자", "005930", 10, 72000)
        assert "전략" not in result
        assert "근거" not in result


# ── format_sell ───────────────────────────────────────────


class TestFormatSell:
    """매도 포맷 테스트."""

    def test_stop_loss(self) -> None:
        result = format_sell("SK하이닉스", "000660", 5, 185000, "손절")
        assert "[손절]" in result
        assert "185,000" in result

    def test_take_profit(self) -> None:
        result = format_sell("NAVER", "035420", 3, 400000, "익절")
        assert "[익절]" in result

    def test_strategy_sell(self) -> None:
        result = format_sell("카카오", "035720", 2, 50000, "전략매도")
        assert "[매도]" in result
        assert "전략매도" in result

    def test_with_detail(self) -> None:
        detail = SellDetail(
            total_amount=925000,
            avg_price=170000.0,
            profit_loss=75000,
            profit_rate=8.82,
        )
        result = format_sell("SK하이닉스", "000660", 5, 185000, "익절", detail)
        assert "170,000" in result
        assert "+75,000" in result
        assert "+8.82%" in result

    def test_negative_profit(self) -> None:
        detail = SellDetail(
            total_amount=850000,
            avg_price=190000.0,
            profit_loss=-25000,
            profit_rate=-2.63,
        )
        result = format_sell("SK하이닉스", "000660", 5, 170000, "손절", detail)
        assert "-25,000" in result
        assert "-2.63%" in result


# ── format_daily_summary ──────────────────────────────────


class TestFormatDailySummary:
    """일일 결산 포맷 테스트."""

    def test_positive_profit(self) -> None:
        result = format_daily_summary("2026-04-03", 3, 15200, 0.3)
        assert "[일일 결산]" in result
        assert "+15,200" in result
        assert "+0.30%" in result
        assert "3건" in result

    def test_negative_profit(self) -> None:
        result = format_daily_summary("2026-04-03", 1, -5000, -0.1)
        assert "-5,000" in result
        assert "-0.10%" in result

    def test_zero_profit(self) -> None:
        result = format_daily_summary("2026-04-03", 0, 0, 0.0)
        assert "+0" in result

    def test_with_buy_sell_counts(self) -> None:
        result = format_daily_summary("2026-04-03", 5, 10000, 0.5, buy_count=3, sell_count=2)
        assert "매수 3" in result
        assert "매도 2" in result

    def test_with_executions(self) -> None:
        execs = [
            _FakeExecution(stock_name="삼성전자", side="매수", quantity=10, price=72000),
            _FakeExecution(stock_name="SK하이닉스", side="매도", quantity=5, price=185000),
        ]
        result = format_daily_summary("2026-04-03", 2, 15000, 0.3, executions=execs)
        assert "체결 내역" in result
        assert "삼성전자" in result
        assert "SK하이닉스" in result

    def test_with_balance(self) -> None:
        bal = _FakeBalance()
        result = format_daily_summary("2026-04-03", 1, 5000, 0.1, balance=bal)
        assert "계좌 현황" in result
        assert "5,000,000" in result
        assert "12,350,000" in result
        assert "1종목" in result

    def test_executions_truncated_at_10(self) -> None:
        execs = [
            _FakeExecution(stock_name=f"종목{i}", side="매수", quantity=1, price=1000)
            for i in range(15)
        ]
        result = format_daily_summary("2026-04-03", 15, 0, 0.0, executions=execs)
        assert "외 5건" in result

    def test_with_version_shows_in_header(self) -> None:
        result = format_daily_summary("2026-04-03", 0, 0, 0.0, version="0.1.5")
        assert "[v0.1.5]" in result
        # 헤더에 한 번만 등장
        assert result.count("[v0.1.5]") == 1

    def test_without_version_omits_prefix(self) -> None:
        result = format_daily_summary("2026-04-03", 0, 0, 0.0)
        # v로 시작하는 버전 토큰이 없어야 함
        assert "[v" not in result

    def test_with_today_bumps_lists_changes(self) -> None:
        bumps = [
            ("0.1.4", "bug_fix", "종목명 누락 보정"),
            ("0.1.5", "param_tuning", "MIN_CONFIDENCE 0.20 상향"),
        ]
        result = format_daily_summary(
            "2026-04-03", 0, 0, 0.0, version="0.1.5", today_bumps=bumps,
        )
        assert "오늘 적용된 변경" in result
        assert "v0.1.4 (bug_fix)" in result
        assert "v0.1.5 (param_tuning)" in result

    def test_today_bumps_truncated_at_5(self) -> None:
        bumps = [(f"0.1.{i}", "bug_fix", f"변경 {i}") for i in range(8)]
        result = format_daily_summary(
            "2026-04-03", 0, 0, 0.0, today_bumps=bumps,
        )
        assert "외 3건" in result


# ── format_error ──────────────────────────────────────────


class TestFormatError:
    """에러 포맷 테스트."""

    def test_contains_context(self) -> None:
        result = format_error("토큰 갱신", "ConnectionError")
        assert "[에러]" in result
        assert "토큰 갱신" in result
        assert "ConnectionError" in result

    def test_truncates_long_error(self) -> None:
        long_error = "x" * 500
        result = format_error("테스트", long_error)
        assert "x" * 200 in result
        assert "x" * 201 not in result


# ── format_system ─────────────────────────────────────────


class TestFormatSystem:
    """시스템 포맷 테스트."""

    def test_contains_message(self) -> None:
        result = format_system("자동매매 시스템 가동")
        assert "[시스템]" in result
        assert "자동매매 시스템 가동" in result


# ── eval_profit_rate: 평가손익률(매입금액 기준) ──────────────

from src.api.account import Balance, StockHolding  # noqa: E402
from src.notify.formatter import eval_profit_rate  # noqa: E402


def _holding(code: str, qty: int, avg: float, pl: int) -> StockHolding:
    return StockHolding(
        stock_code=code, stock_name=code, quantity=qty, avg_price=avg,
        current_price=int(avg), eval_amount=int(avg * qty) + pl,
        profit_loss=pl, profit_rate=0.0,
    )


def _balance(holdings: list[StockHolding], total_pl: int) -> Balance:
    return Balance(
        deposit=0, total_eval_amount=0, total_profit_loss=total_pl,
        total_profit_rate=-1.83, holdings=holdings, raw_response={},
    )


def test_eval_profit_rate_matches_amount_sign() -> None:
    """평가손익률은 매입금액 기준 — 금액과 부호가 일치한다(자산증감률과 무관)."""
    bal = _balance([_holding("035420", 5, 196_400.0, 33_000)], total_pl=33_000)
    # 33,000 / (196,400*5=982,000) * 100 ≈ +3.36% (KIS 자산증감률 -1.83%와 별개)
    assert round(eval_profit_rate(bal), 2) == 3.36


def test_eval_profit_rate_negative() -> None:
    bal = _balance([_holding("000660", 10, 100_000.0, -50_000)], total_pl=-50_000)
    assert eval_profit_rate(bal) < 0


def test_eval_profit_rate_no_holdings_is_zero() -> None:
    assert eval_profit_rate(_balance([], total_pl=0)) == 0.0


def test_eval_profit_rate_ignores_zero_qty() -> None:
    bal = _balance([_holding("035420", 0, 196_400.0, 0)], total_pl=0)
    assert eval_profit_rate(bal) == 0.0
