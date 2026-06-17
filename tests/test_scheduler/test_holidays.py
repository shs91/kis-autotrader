"""휴장일 판단 테스트."""

from __future__ import annotations

from datetime import date

from src.scheduler.holidays import is_market_closed


class TestIsMarketClosed:
    """is_market_closed 테스트."""

    def test_saturday(self) -> None:
        """토요일은 휴장이다."""
        saturday = date(2026, 4, 4)  # 토요일
        assert is_market_closed(saturday) is True

    def test_sunday(self) -> None:
        """일요일은 휴장이다."""
        sunday = date(2026, 4, 5)  # 일요일
        assert is_market_closed(sunday) is True

    def test_new_years_day(self) -> None:
        """1월 1일은 휴장이다 (holidays.json에 등록)."""
        assert is_market_closed(date(2026, 1, 1)) is True

    def test_lunar_new_year(self) -> None:
        """설날 연휴는 휴장이다."""
        assert is_market_closed(date(2026, 1, 27)) is True
        assert is_market_closed(date(2026, 1, 28)) is True
        assert is_market_closed(date(2026, 1, 29)) is True

    def test_chuseok(self) -> None:
        """추석 연휴는 휴장이다."""
        assert is_market_closed(date(2026, 9, 24)) is True
        assert is_market_closed(date(2026, 9, 25)) is True
        assert is_market_closed(date(2026, 9, 26)) is True

    def test_normal_weekday(self) -> None:
        """일반 평일은 개장이다."""
        # 2026-04-06 월요일, 공휴일 아님
        assert is_market_closed(date(2026, 4, 6)) is False

    def test_christmas(self) -> None:
        """크리스마스는 휴장이다."""
        assert is_market_closed(date(2026, 12, 25)) is True

    def test_local_election_day(self) -> None:
        """제9회 전국동시지방선거 임시공휴일은 휴장이다."""
        assert is_market_closed(date(2026, 6, 3)) is True


class TestUsMarketHolidays:
    """US 시장 휴장일 (P3c-6) — market_code 분기 테스트."""

    def test_us_independence_day_observed(self) -> None:
        """US 독립기념일 관측일(2026-07-03)은 US 휴장, KRX는 개장."""
        assert is_market_closed(date(2026, 7, 3), "US") is True
        assert is_market_closed(date(2026, 7, 3), "KRX") is False

    def test_krx_lunar_new_year_not_us(self) -> None:
        """설날(2026-01-27)은 KRX 휴장, US는 개장."""
        assert is_market_closed(date(2026, 1, 27), "KRX") is True
        assert is_market_closed(date(2026, 1, 27), "US") is False

    def test_us_thanksgiving(self) -> None:
        """US 추수감사절(2026-11-26)은 US 휴장."""
        assert is_market_closed(date(2026, 11, 26), "US") is True

    def test_us_normal_weekday(self) -> None:
        """US 일반 평일은 개장이다."""
        assert is_market_closed(date(2026, 4, 6), "US") is False

    def test_us_weekend(self) -> None:
        """주말은 시장 무관 휴장."""
        assert is_market_closed(date(2026, 4, 4), "US") is True
