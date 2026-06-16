# P3a: config MARKET 배선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** `config.py`가 `MARKET` 환경변수로 시장별 자격증명/env/rate_limit을 로드하게 한다. **MARKET 미설정 시 기존 KRX 동작과 100% 동일**(미국만 추가).

**Architecture:** 헬퍼 `_market_cred(suffix)`(활성 시장 `credentials_env_prefix`로 env 조회: KRX→`KIS_*`, US→`KIS_US_*`)와 `_market_env()`(KIS_ENV 명시 우선, 없으면 `MarketProfile.kis_env`). `KISConfig`·`RateLimitConfig.per_second`가 사용. `base_url`(env property)·DB URL은 자동/후속(P3b).

**검증 환경:** worktree, `/Users/.../.venv/bin/python -m pytest|mypy|ruff`. base: 최신 main(P1+P2 머지 포함).

**호환성 핵심:** KRX(MARKET 미설정)는 `prefix="KIS"`→`KIS_APP_KEY` 등 기존 키, `_market_env()`=KIS_ENV/virtual → 기존과 동일. 테스트로 회귀 고정.

---

## 파일 구조

| 파일 | 변경 |
|------|------|
| `src/config.py` | `active_market_profile` import + `_market_cred`/`_market_env` 헬퍼 + `KISConfig`/`RateLimitConfig.per_second` 배선 | Modify |
| `tests/test_config_market.py` | 시장별 배선 테스트 | Create |

---

### Task 1: 헬퍼 + KISConfig/RateLimit 배선

- [ ] **Step 1: 실패 테스트** — `tests/test_config_market.py`:

```python
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
```

- [ ] **Step 2: RED** — `python -m pytest tests/test_config_market.py -q` → `ImportError: cannot import name '_market_cred'`.

- [ ] **Step 3: config.py 수정**

(a) import 추가 (상단 import 블록, `from dotenv import load_dotenv` 다음 줄들 근처 — 정확히는 `load_dotenv()` 호출 위의 import 그룹에):

```python
from src.market.profile import active_market_profile
```

> 순환 없음: `src.market.profile`은 `src.config`를 import하지 않음(os.getenv 직접).

(b) `_env_float` 정의 다음에 헬퍼 2개 추가:

```python
def _market_cred(suffix: str, default: str = "") -> str:
    """활성 시장의 자격증명 prefix로 환경변수를 읽는다(KRX→KIS_, US→KIS_US_)."""
    prefix = active_market_profile().credentials_env_prefix
    return _env(f"{prefix}_{suffix}", default)


def _market_env() -> str:
    """시장별 KIS_ENV. KIS_ENV 명시값 우선, 없으면 활성 시장 기본(KRX=virtual/US=real)."""
    override = _env("KIS_ENV", "")
    if override:
        return override
    return active_market_profile().kis_env
```

(c) `KISConfig`의 필드 5개를 교체:

```python
    app_key: str = field(default_factory=lambda: _market_cred("APP_KEY"))
    app_secret: str = field(default_factory=lambda: _market_cred("APP_SECRET"))
    account_no: str = field(default_factory=lambda: _market_cred("ACCOUNT_NO"))
    account_product_code: str = field(
        default_factory=lambda: _market_cred("ACCOUNT_PRODUCT_CODE", "01")
    )
    env: str = field(default_factory=_market_env)
```

(d) `RateLimitConfig.per_second`의 default를 `_market_env()` 기반으로:

```python
    per_second: int = field(
        default_factory=lambda: _env_int(
            "API_RATE_LIMIT_PER_SECOND",
            20 if _market_env() == "real" else 5,
        )
    )
```

> `_default_db_url`은 P3b에서 다룬다(공유DB 전략과 함께). P3a 미변경.

- [ ] **Step 4: GREEN + 회귀 + 커밋**

```
python -m pytest tests/test_config_market.py tests/test_config.py -q   # PASS
python -m pytest tests/test_market/ tests/test_api/test_overseas_quote.py -q   # 회귀 PASS
python -m mypy src/config.py   # Success
ruff check src/config.py tests/test_config_market.py   # passed
git add src/config.py tests/test_config_market.py
git commit -m "feat(config): MARKET 배선 — 시장별 자격증명/env/rate_limit (P3a, KRX 동작 보존)"
```

---

## Self-Review

**1. Spec coverage:** §6 시장별 환경/자격증명(`KIS_US_*`, MARKET→MarketProfile, env 내장+override) ✓. base_url은 env property로 자동(US real→실전) ✓. DB URL은 P3b(공유DB 전략과 함께) — 의도적 분리.
**2. Placeholder:** 모든 step 실제 코드/명령.
**3. Type consistency:** `_market_cred(suffix: str, default: str="") -> str`, `_market_env() -> str`. `KISConfig.env`/`RateLimitConfig.per_second` default가 헬퍼와 일치. `active_market_profile().credentials_env_prefix`/`.kis_env`는 P1 MarketProfile 필드와 일치.
**4. 호환성:** KRX(MARKET 미설정): prefix=KIS→KIS_APP_KEY(기존), _market_env=KIS_ENV/virtual(기존). RateLimit virtual=5(기존). → test_krx_* 4건이 회귀 고정. test_config.py(기존) 무변경 통과.
**5. 순환 import:** config → market.profile 단방향(market.profile은 config 미import). ✓

## Execution Handoff
P3b(DB 마이그+공유DB 전략), P3c(엔진 멀티마켓)로 이어감.
