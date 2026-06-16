# P1: 멀티마켓 추상화 골격 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 미국 주식 확장을 위한 멀티마켓 추상화의 "골격"을 도입한다 — 시장별 메타데이터를 담는 `MarketProfile`(KRX/US)과 시세/주문/계좌 `Provider` Protocol을 신설하되, **기존 코드 동작은 전혀 바꾸지 않는다**(순수 추가).

**Architecture:** `MarketProfile`(frozen dataclass)에 시장 식별·통화·소수점·거래소코드 매핑·자격증명 prefix·기본 KIS_ENV를 선언적으로 집약한다. 국내/해외 API의 파라미터·응답 체계가 완전히 다르므로 `if market:` 분기 대신 `Protocol`(QuoteProvider/OrderProvider/AccountProvider)을 정의하고, 기존 `QuoteAPI`/`OrderAPI`/`AccountAPI`가 이를 **구조적으로 만족**함을 테스트로 고정한다. 해외 구현체(`Overseas*`)와 엔진 배선은 P2/P3에서 추가한다.

**Tech Stack:** Python 3.12, `@dataclass(frozen=True)`, `typing.Protocol` + `runtime_checkable`, pytest, mypy(strict), ruff.

**기준 spec:** `docs/superpowers/specs/2026-06-14-us-stock-trading-design.md` (§3 아키텍처)

**검증 환경 주의:** 이 작업은 worktree `.claude/worktrees/us-stock-trading-impl`에서 수행한다. worktree 로컬 `.venv`가 없으므로 메인 repo의 venv를 사용한다: 모든 `pytest`/`mypy`/`ruff` 명령은 `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python -m pytest ...` 형태로 실행하거나 해당 venv를 활성화한 뒤 실행한다. 본 plan의 명령은 `python -m pytest ...`로 표기하며 위 venv 기준이다.

---

## 파일 구조

| 파일 | 책임 | 종류 |
|------|------|------|
| `src/market/__init__.py` | market 패키지 마커 | Create |
| `src/market/profile.py` | `MarketProfile` dataclass + KRX/US 인스턴스 + 레지스트리/선택자 | Create |
| `src/api/protocols.py` | `QuoteProvider`/`OrderProvider`/`AccountProvider` Protocol | Create |
| `tests/test_market/__init__.py` | 테스트 패키지 마커 | Create |
| `tests/test_market/test_profile.py` | `MarketProfile` 단위 테스트 | Create |
| `tests/test_api/test_protocols.py` | 기존 Domestic API의 Protocol 부합 테스트 | Create |

> **결합 방향**: `src/market/profile.py`는 `src/config`를 import하지 않는다(순환 방지). `MARKET` 환경변수는 `os.getenv`로 직접 읽는다. `src/api/protocols.py`는 기존 `src/api/{order,quote,account}`의 dataclass(반환 타입)만 import한다. 엔진/스케줄러/config 수정은 P3에서 다룬다.

---

### Task 1: MarketProfile 도입 (KRX/US 메타데이터)

**Files:**
- Create: `src/market/__init__.py`
- Create: `src/market/profile.py`
- Create: `tests/test_market/__init__.py`
- Test: `tests/test_market/test_profile.py`

- [ ] **Step 1: 빈 패키지 마커 생성**

Create `src/market/__init__.py`:

```python
"""멀티마켓 추상화 패키지."""
```

Create `tests/test_market/__init__.py`:

```python
```

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/test_market/test_profile.py`:

```python
"""MarketProfile 단위 테스트."""

from __future__ import annotations

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
    with pytest.raises(Exception):  # FrozenInstanceError (dataclasses)
        US_PROFILE.market_code = "KRX"  # type: ignore[misc]


def test_profile_type() -> None:
    assert isinstance(KRX_PROFILE, MarketProfile)
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/test_market/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.market.profile'`

- [ ] **Step 4: MarketProfile 구현**

Create `src/market/profile.py`:

```python
"""시장별 메타데이터(MarketProfile)와 레지스트리.

멀티마켓(KRX/US) 분기를 선언적으로 집약한다. 국내/해외 API의 엔드포인트·
파라미터·응답 체계가 완전히 다르므로, 시장 종속 값을 코드 곳곳의 ``if`` 분기
대신 이 프로파일 한 곳에 모은다. 신규 시장 추가 시 프로파일 인스턴스만 추가한다.

순환 import를 피하기 위해 이 모듈은 ``src.config``를 import하지 않으며,
``MARKET`` 환경변수는 ``os.getenv``로 직접 읽는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketProfile:
    """한 시장(KRX/US 등)의 매매에 필요한 메타데이터 묶음."""

    market_code: str
    """시장 식별 코드 ("KRX" | "US")."""

    currency: str
    """결제 통화 ISO 코드 ("KRW" | "USD")."""

    currency_symbol: str
    """통화 기호 ("₩" | "$")."""

    price_precision: int
    """가격 소수점 자릿수. KRX=0(정수 원), US=2(0.01달러)."""

    timezone: str
    """시장 IANA 타임존 ("Asia/Seoul" | "America/New_York")."""

    kis_env: str
    """시장별 기본 KIS_ENV ("virtual" | "real"). 프로세스 env로 override 가능."""

    credentials_env_prefix: str
    """자격증명 환경변수 prefix ("KIS" | "KIS_US")."""

    exchanges: tuple[str, ...]
    """주문용 거래소코드(OVRS_EXCG_CD) 목록. KRX는 빈 튜플."""

    quote_exchange_map: dict[str, str] = field(default_factory=dict)
    """주문 거래소코드(4자리) → 시세 거래소코드(3자리) 매핑. KRX는 빈 dict."""

    @property
    def is_overseas(self) -> bool:
        """해외 시장이면 True (국내 KRX는 False)."""
        return self.market_code != "KRX"


KRX_PROFILE = MarketProfile(
    market_code="KRX",
    currency="KRW",
    currency_symbol="₩",
    price_precision=0,
    timezone="Asia/Seoul",
    kis_env="virtual",
    credentials_env_prefix="KIS",
    exchanges=(),
    quote_exchange_map={},
)

US_PROFILE = MarketProfile(
    market_code="US",
    currency="USD",
    currency_symbol="$",
    price_precision=2,
    timezone="America/New_York",
    kis_env="real",
    credentials_env_prefix="KIS_US",
    exchanges=("NASD", "NYSE", "AMEX"),
    quote_exchange_map={"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"},
)

_PROFILES: dict[str, MarketProfile] = {
    KRX_PROFILE.market_code: KRX_PROFILE,
    US_PROFILE.market_code: US_PROFILE,
}


def get_market_profile(market_code: str) -> MarketProfile:
    """시장 코드로 MarketProfile을 조회한다(대소문자 무관).

    Args:
        market_code: "KRX" 또는 "US" (대소문자 무관)

    Returns:
        해당 시장의 프로파일

    Raises:
        ValueError: 지원하지 않는 시장 코드인 경우
    """
    try:
        return _PROFILES[market_code.upper()]
    except KeyError:
        raise ValueError(f"지원하지 않는 시장: {market_code}") from None


def active_market_profile() -> MarketProfile:
    """``MARKET`` 환경변수로 활성 시장 프로파일을 반환한다(기본 "KRX").

    분리 프로세스 운영에서 주간 프로세스는 ``MARKET=KRX``, 야간 프로세스는
    ``MARKET=US``로 기동한다. 미설정 시 기존 동작(KRX)을 보존한다.
    """
    return get_market_profile(os.getenv("MARKET", "KRX"))
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_market/test_profile.py -v`
Expected: PASS (10 passed)

- [ ] **Step 6: 타입/린트 확인**

Run: `python -m mypy src/market/profile.py`
Expected: `Success: no issues found`

Run: `ruff check src/market/ tests/test_market/`
Expected: `All checks passed!`

- [ ] **Step 7: 커밋**

```bash
git add src/market/__init__.py src/market/profile.py tests/test_market/
git commit -m "feat(market): MarketProfile 도입 — KRX/US 시장 메타데이터 골격 (P1)"
```

---

### Task 2: Provider Protocol 정의 + Domestic API 부합 고정

**Files:**
- Create: `src/api/protocols.py`
- Test: `tests/test_api/test_protocols.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_api/test_protocols.py`:

```python
"""기존 Domestic API가 Provider Protocol을 구조적으로 만족하는지 고정한다.

P1에서는 행동을 바꾸지 않고, 해외 구현체(P2)가 따라야 할 인터페이스 계약만
정의한다. runtime_checkable Protocol의 issubclass는 메서드 존재만 검사하며,
정확한 시그니처는 mypy가 정적으로 보장한다.
"""

from __future__ import annotations

from src.api.account import AccountAPI
from src.api.order import OrderAPI
from src.api.protocols import AccountProvider, OrderProvider, QuoteProvider
from src.api.quote import QuoteAPI


def test_order_api_satisfies_order_provider() -> None:
    assert issubclass(OrderAPI, OrderProvider)


def test_quote_api_satisfies_quote_provider() -> None:
    assert issubclass(QuoteAPI, QuoteProvider)


def test_account_api_satisfies_account_provider() -> None:
    assert issubclass(AccountAPI, AccountProvider)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_api/test_protocols.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.protocols'`

- [ ] **Step 3: Protocol 구현**

Create `src/api/protocols.py`:

```python
"""시세/주문/계좌 Provider 인터페이스(Protocol).

국내(Domestic*)와 해외(Overseas*, P2 예정) 구현체가 공유하는 계약이다.
엔진/스케줄러는 구체 클래스가 아니라 이 Protocol에만 의존한다.

``runtime_checkable``은 메서드 이름 존재 여부만 런타임 검사한다. 인자/반환
타입의 정확한 일치는 mypy(strict)가 정적으로 보장한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.api.account import Balance, Execution
from src.api.order import OrderResult
from src.api.quote import CurrentPrice, DailyPriceItem


@runtime_checkable
class QuoteProvider(Protocol):
    """시세 조회 인터페이스."""

    async def get_current_price(self, stock_code: str) -> CurrentPrice:
        """종목 현재가를 조회한다."""
        ...

    async def get_daily_price(
        self,
        stock_code: str,
        period: str = "D",
        adjusted: bool = True,
        lookback_days: int = 60,
    ) -> list[DailyPriceItem]:
        """종목 일봉을 조회한다(최신→과거 순)."""
        ...


@runtime_checkable
class OrderProvider(Protocol):
    """주문(매수/매도/정정/취소) 인터페이스."""

    async def buy(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0,
        order_type: str = "01",
    ) -> OrderResult:
        """매수 주문을 실행한다."""
        ...

    async def sell(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0,
        order_type: str = "01",
    ) -> OrderResult:
        """매도 주문을 실행한다."""
        ...

    async def modify(
        self,
        order_no: str,
        stock_code: str,
        quantity: int,
        price: int,
    ) -> OrderResult:
        """주문을 정정한다."""
        ...

    async def cancel(
        self,
        order_no: str,
        stock_code: str,
        quantity: int,
    ) -> OrderResult:
        """주문을 취소한다."""
        ...


@runtime_checkable
class AccountProvider(Protocol):
    """잔고/체결 조회 인터페이스."""

    async def get_balance(self) -> Balance:
        """잔고(보유종목+예수금)를 조회한다."""
        ...

    async def get_executions(self) -> list[Execution]:
        """당일 체결 내역을 조회한다."""
        ...
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_api/test_protocols.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 타입/린트 확인**

Run: `python -m mypy src/api/protocols.py`
Expected: `Success: no issues found`

Run: `ruff check src/api/protocols.py tests/test_api/test_protocols.py`
Expected: `All checks passed!`

- [ ] **Step 6: 커밋**

```bash
git add src/api/protocols.py tests/test_api/test_protocols.py
git commit -m "feat(api): 시세/주문/계좌 Provider Protocol 정의 + Domestic 부합 고정 (P1)"
```

---

### Task 3: 회귀 검출 — 전체 테스트 green 확인

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 변경 모듈 인접 테스트 실행**

Run: `python -m pytest tests/test_api/ tests/test_market/ tests/test_strategy/ -q`
Expected: PASS (기존 + 신규, 0 failures)

- [ ] **Step 2: src 전체 타입 체크(회귀 없음 확인)**

Run: `python -m mypy src/market/ src/api/protocols.py`
Expected: `Success: no issues found`

> 참고: `ruff check src/` 전체는 사전 존재 위반 13건(E501/UP035/I001)을 뱉을 수 있다(메모리 `project_ruff_baseline_dirty`). 이는 본 작업의 회귀가 아니므로, 신규/변경 파일만 클린이면 통과로 간주한다.

- [ ] **Step 3: 신규 파일 한정 린트 최종 확인**

Run: `ruff check src/market/ src/api/protocols.py tests/test_market/ tests/test_api/test_protocols.py`
Expected: `All checks passed!`

- [ ] **Step 4: P1 완료 태그 커밋(선택)**

```bash
git commit --allow-empty -m "chore(market): P1 멀티마켓 추상화 골격 완료 — MarketProfile + Provider Protocol"
```

---

## Self-Review (작성자 점검 완료)

**1. Spec coverage (§3 아키텍처 대비):**
- §3.1 `MarketProfile`(market_code/currency/symbol/precision/tz/exchanges/credentials prefix) → Task 1 ✓. (trading_hours/risk_params/screening_params 필드는 엔진 배선이 필요한 P3에서 확장 — P1 골격 범위 밖, YAGNI.)
- §3.2 Provider Protocol(QuoteProvider/OrderProvider/AccountProvider) → Task 2 ✓.
- §2.4 거래소코드 이중 체계(NASD↔NAS 등) → `MarketProfile.quote_exchange_map` Task 1 ✓.
- §6 `MARKET` env 기반 시장 선택 → `active_market_profile()` Task 1 ✓. (config.py 배선은 P3.)
- 해외 구현체(`Overseas*`)·DB 마이그레이션·엔진 배선·안전장치는 P2~P5 (본 plan 범위 밖, 의도적).

**2. Placeholder scan:** 모든 step에 실제 코드/명령/기대출력 포함. "TBD/적절히/handle edge cases" 없음. ✓

**3. Type consistency:** `MarketProfile` 필드명(market_code/currency/currency_symbol/price_precision/timezone/kis_env/credentials_env_prefix/exchanges/quote_exchange_map)이 Task 1 구현·테스트에서 일치. Protocol 메서드 시그니처가 기존 `OrderAPI.buy(stock_code, quantity, price=0, order_type="01")` 등 실제 시그니처와 일치(order_type 기본값은 `OrderAPI`의 `ORDER_TYPE_MARKET="01"`과 동일 리터럴 "01"). 반환 타입 import(`CurrentPrice`/`DailyPriceItem`/`OrderResult`/`Balance`/`Execution`)는 실제 dataclass명과 일치. ✓

---

## Execution Handoff

P1은 행동 불변·순수 추가라 위험이 낮다. 다음 Phase 미리보기:
- **P2**: 해외 API 구현체(`OverseasQuoteAPI`/`OverseasAccountAPI`/`OverseasOrderAPI`) + respx mock + 실전키 5분 실측.
- **P3**: DB 마이그레이션(market/currency/Decimal) + config `MARKET` 배선 + 엔진 멀티마켓 구동.
- **P4**: 야간 안전장치(Phase 0 통합) + 보수적 한도.
- **P5**: launchd/watchdog 야간 배포 + 소액 카나리.
