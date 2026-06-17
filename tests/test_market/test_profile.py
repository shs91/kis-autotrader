"""MarketProfile 단위 테스트."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.market.profile import (
    KRX_PROFILE,
    US_PROFILE,
    MarketProfile,
    active_market_profile,
    format_money,
    get_market_profile,
)


class TestFormatMoney:
    """통화 인지 금액 포맷 — KRW는 기존 로그와 바이트 동일, USD는 '$'."""

    def test_krw_byte_invariant_with_legacy_int_format(self) -> None:
        # 기존 로그는 정수 KRW에 f"{x:,}원" 사용 — format_money(KRW)가 동일해야 함.
        for v in (0, 5, 1000, 70000, 1234567, -2800):
            assert format_money(v, "KRW") == f"{v:,}원"

    def test_krw_rounds_float_to_int(self) -> None:
        # 부동소수 KRW도 정수로 표기(".0" 오염 방지).
        assert format_money(70000.0, "KRW") == "70,000원"
        assert format_money(70000.4, "KRW") == "70,000원"

    def test_usd_two_decimals_with_symbol(self) -> None:
        assert format_money(298.53, "USD") == "$298.53"
        assert format_money(1000, "USD") == "$1,000.00"
        assert format_money(0, "USD") == "$0.00"

    def test_usd_negative_sign_before_symbol(self) -> None:
        assert format_money(-12.34, "USD") == "-$12.34"

    def test_unknown_currency_suffix(self) -> None:
        assert format_money(12.5, "JPY") == "12.50 JPY"

    def test_default_currency_is_krw(self) -> None:
        assert format_money(1000) == "1,000원"


def test_krx_profile_fields() -> None:
    assert KRX_PROFILE.market_code == "KRX"
    assert KRX_PROFILE.currency == "KRW"
    assert KRX_PROFILE.currency_symbol == "₩"
    assert KRX_PROFILE.price_precision == 0
    assert KRX_PROFILE.timezone == "Asia/Seoul"
    assert KRX_PROFILE.kis_env == "virtual"
    assert KRX_PROFILE.credentials_env_prefix == "KIS"
    assert KRX_PROFILE.exchanges == ()
    assert KRX_PROFILE.is_overseas is False


def test_us_profile_fields() -> None:
    assert US_PROFILE.market_code == "US"
    assert US_PROFILE.currency == "USD"
    assert US_PROFILE.currency_symbol == "$"
    assert US_PROFILE.price_precision == 2
    assert US_PROFILE.timezone == "America/New_York"
    assert US_PROFILE.kis_env == "real"
    assert US_PROFILE.credentials_env_prefix == "KIS_US"
    assert US_PROFILE.exchanges == ("NASD", "NYSE", "AMEX")
    assert US_PROFILE.is_overseas is True


def test_us_exchange_code_mapping_order_to_quote() -> None:
    # 주문 거래소코드(4자리) → 시세 거래소코드(3자리)
    assert US_PROFILE.quote_exchange_map == {
        "NASD": "NAS",
        "NYSE": "NYS",
        "AMEX": "AMS",
    }


def test_get_market_profile_is_case_insensitive() -> None:
    assert get_market_profile("krx") is KRX_PROFILE
    assert get_market_profile("US") is US_PROFILE


def test_get_market_profile_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="지원하지 않는 시장"):
        get_market_profile("JP")


def test_active_market_profile_defaults_to_krx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET", raising=False)
    assert active_market_profile() is KRX_PROFILE


def test_active_market_profile_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET", "US")
    assert active_market_profile() is US_PROFILE


def test_profile_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        US_PROFILE.market_code = "KRX"  # type: ignore[misc]


def test_profile_type() -> None:
    assert isinstance(KRX_PROFILE, MarketProfile)
