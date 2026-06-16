"""MarketProfile 단위 테스트."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.market.profile import (
    KRX_PROFILE,
    US_PROFILE,
    MarketProfile,
    active_market_profile,
    get_market_profile,
)


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
