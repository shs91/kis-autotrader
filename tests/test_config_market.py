"""config.py 시장별(MARKET) 자격증명/env 배선 테스트."""

from __future__ import annotations

import pytest

from src.config import KISConfig, RateLimitConfig, _market_cred, _market_env


class TestMarketEnv:
    def test_krx_default_virtual(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MARKET", raising=False)
        monkeypatch.delenv("KIS_ENV", raising=False)
        assert _market_env() == "virtual"

    def test_us_default_real(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARKET", "US")
        monkeypatch.delenv("KIS_ENV", raising=False)
        assert _market_env() == "real"

    def test_explicit_kis_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARKET", "US")
        monkeypatch.setenv("KIS_ENV", "virtual")
        assert _market_env() == "virtual"


class TestMarketCred:
    def test_krx_uses_kis_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MARKET", raising=False)
        monkeypatch.setenv("KIS_APP_KEY", "krx-key")
        assert _market_cred("APP_KEY") == "krx-key"

    def test_us_uses_kis_us_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARKET", "US")
        monkeypatch.setenv("KIS_US_APP_KEY", "us-key")
        assert _market_cred("APP_KEY") == "us-key"

    def test_default_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARKET", "US")
        monkeypatch.delenv("KIS_US_ACCOUNT_PRODUCT_CODE", raising=False)
        assert _market_cred("ACCOUNT_PRODUCT_CODE", "01") == "01"


class TestKISConfigMarket:
    def test_krx_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MARKET", raising=False)
        monkeypatch.delenv("KIS_ENV", raising=False)
        monkeypatch.setenv("KIS_APP_KEY", "krx-key")
        monkeypatch.setenv("KIS_ACCOUNT_NO", "111")
        cfg = KISConfig()
        assert cfg.app_key == "krx-key"
        assert cfg.account_no == "111"
        assert cfg.env == "virtual"
        assert cfg.base_url == "https://openapivts.koreainvestment.com:29443"

    def test_us_credentials_real(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARKET", "US")
        monkeypatch.delenv("KIS_ENV", raising=False)
        monkeypatch.setenv("KIS_US_APP_KEY", "us-key")
        monkeypatch.setenv("KIS_US_ACCOUNT_NO", "999")
        cfg = KISConfig()
        assert cfg.app_key == "us-key"
        assert cfg.account_no == "999"
        assert cfg.env == "real"
        assert cfg.base_url == "https://openapi.koreainvestment.com:9443"

    def test_rate_limit_us_is_20(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARKET", "US")
        monkeypatch.delenv("KIS_ENV", raising=False)
        monkeypatch.delenv("API_RATE_LIMIT_PER_SECOND", raising=False)
        assert RateLimitConfig().per_second == 20

    def test_rate_limit_krx_is_5(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MARKET", raising=False)
        monkeypatch.delenv("KIS_ENV", raising=False)
        monkeypatch.delenv("API_RATE_LIMIT_PER_SECOND", raising=False)
        assert RateLimitConfig().per_second == 5
