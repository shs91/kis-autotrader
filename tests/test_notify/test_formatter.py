"""메시지 포맷팅 테스트."""

from __future__ import annotations

from src.notify.formatter import (
    format_buy,
    format_daily_summary,
    format_error,
    format_sell,
    format_system,
)


class TestFormatBuy:
    """매수 포맷 테스트."""

    def test_contains_tag_and_price(self) -> None:
        result = format_buy("삼성전자", "005930", 10, 72000)
        assert "[매수]" in result
        assert "삼성전자" in result
        assert "005930" in result
        assert "72,000" in result
        assert "10주" in result


class TestFormatSell:
    """매도 포맷 테스트."""

    def test_stop_loss(self) -> None:
        result = format_sell("SK하이닉스", "000660", 5, 185000, "손절")
        assert "[손절]" in result
        assert "185,000" in result

    def test_take_profit(self) -> None:
        result = format_sell("NAVER", "035420", 3, 400000, "익절")
        assert "[매도]" in result
        assert "익절" in result

    def test_strategy_sell(self) -> None:
        result = format_sell("카카오", "035720", 2, 50000, "전략매도")
        assert "[매도]" in result
        assert "전략매도" in result


class TestFormatDailySummary:
    """일일 결산 포맷 테스트."""

    def test_positive_profit(self) -> None:
        result = format_daily_summary("2026-04-03", 3, 15200, 0.3)
        assert "[결산]" in result
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
        # 에러 메시지가 200자로 잘림
        assert "x" * 200 in result
        assert "x" * 201 not in result


class TestFormatSystem:
    """시스템 포맷 테스트."""

    def test_contains_message(self) -> None:
        result = format_system("자동매매 시스템 가동")
        assert "[시스템]" in result
        assert "자동매매 시스템 가동" in result
