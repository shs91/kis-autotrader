# P3c-1: 엔진 생성 구조 (팩토리+주입+시간대) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** `TradingEngine`을 `MarketProfile`/provider 주입 가능하게 만들고 시간대를 시장별로 주입한다. **KRX 행동 불변**(기존 `TradingEngine()`은 KRX 그대로). 해외 provider 실제 연결/어댑터는 P3c-2.

**Architecture:** `__init__`에 `market_profile`/`quote`/`order`/`account` 키워드 파라미터(기본 None→KRX 기본 생성) 추가. `self._market`(MarketProfile)·`self._tz`(ZoneInfo) 보관. 전역 `_KST` 제거 → `self._tz`. `create_for_market(market_code)` 팩토리(P3c-1은 KRX 완전, US는 프로파일/시간대만 — 실제 매매는 P3c-2 어댑터 후).

**검증 환경:** worktree, 메인 `.venv`. 기존 엔진 테스트가 행동불변 회귀 검출기.

---

## 파일 구조
| 파일 | 변경 |
|------|------|
| `src/engine.py` | import 추가 + `__init__` 주입 + `self._market`/`self._tz` + `create_for_market` + `_KST`→`self._tz` | Modify |
| `tests/test_engine_market.py` | 엔진 생성/시장/시간대 테스트 | Create |

---

### Task 1: __init__ 주입 + 시장/시간대 + 팩토리

- [ ] **Step 1: 실패 테스트** — `tests/test_engine_market.py`:

```python
"""TradingEngine 멀티마켓 생성 구조 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.engine import TradingEngine


def test_default_engine_is_krx() -> None:
    e = TradingEngine()
    assert e._market.market_code == "KRX"
    assert str(e._tz) == "Asia/Seoul"


def test_create_for_market_krx() -> None:
    e = TradingEngine.create_for_market("KRX")
    assert e._market.market_code == "KRX"
    assert str(e._tz) == "Asia/Seoul"


def test_create_for_market_us_profile_and_tz() -> None:
    e = TradingEngine.create_for_market("US")
    assert e._market.market_code == "US"
    assert str(e._tz) == "America/New_York"


def test_injected_providers_used() -> None:
    q = MagicMock()
    e = TradingEngine(quote=q)
    assert e._quote is q
```

- [ ] **Step 2: RED** — `python -m pytest tests/test_engine_market.py -q` → AttributeError(`_market`/`_tz` 없음) 또는 TypeError(`quote` 키워드 없음).

- [ ] **Step 3: import 추가** — `src/engine.py` 상단 import 블록에:

```python
from src.api.protocols import AccountProvider, OrderProvider, QuoteProvider
from src.market.profile import KRX_PROFILE, MarketProfile, get_market_profile
```

(`ZoneInfo`는 이미 import됨 — `_KST`에서 사용 중.)

- [ ] **Step 4: __init__ 시그니처 + body 수정**

시그니처를 다음으로 교체(기존 watchlist/strategy/selector 뒤에 키워드 전용 추가):

```python
    def __init__(
        self,
        watchlist: list[str] | None = None,
        strategy: BaseStrategy | None = None,
        selector: StrategySelector | None = None,
        *,
        market_profile: MarketProfile | None = None,
        quote: QuoteProvider | None = None,
        order: OrderProvider | None = None,
        account: AccountProvider | None = None,
    ) -> None:
```

body의 API 생성부(현재 라인 104-107)를 교체:

```python
        self._market = market_profile or KRX_PROFILE
        self._tz = ZoneInfo(self._market.timezone)
        self._client = KISClient()
        self._quote: QuoteProvider = quote or QuoteAPI(client=self._client)
        self._order: OrderProvider = order or OrderAPI(client=self._client)
        self._account: AccountProvider = account or AccountAPI(client=self._client)
```

- [ ] **Step 5: create_for_market 팩토리 추가** — `__init__` 다음에 클래스 메서드 추가:

```python
    @classmethod
    def create_for_market(cls, market_code: str = "KRX") -> TradingEngine:
        """MARKET 코드로 시장별 엔진을 생성한다.

        P3c-1은 프로파일/시간대만 시장별로 설정한다. 해외(US) provider 주입과
        주문/시세 어댑터는 P3c-2에서 추가한다(현재 US는 KRX API로 생성됨).
        """
        profile = get_market_profile(market_code)
        return cls(market_profile=profile)
```

- [ ] **Step 6: 통과 확인** — `python -m pytest tests/test_engine_market.py -q` → PASS.

---

### Task 2: _KST → self._tz 치환

- [ ] **Step 1:** `src/engine.py`의 `datetime.now(_KST)` 5곳(라인 322·363·974·1172·1543)을 `datetime.now(self._tz)`로 치환. 모두 `TradingEngine` 인스턴스 메서드 내부이므로 `self` 접근 가능.

- [ ] **Step 2:** 전역 상수 정의 `_KST = ZoneInfo("Asia/Seoul")`(라인 55) 제거(주석 포함). 다른 모듈이 `engine._KST`를 import하지 않음(grep 확인 완료, engine.py 내부 전용).

- [ ] **Step 3: 검증** — `python -m pytest tests/test_engine_market.py -q` PASS, `grep -n "_KST" src/engine.py` → 결과 없음.

---

### Task 3: 회귀 + 검증 + 커밋

- [ ] **Step 1: 엔진 회귀** — `python -m pytest tests/test_engine_market.py tests/test_engine_db_integration.py -q` → PASS(기존 엔진 테스트 green = 행동불변).
- [ ] **Step 2:** `python -m mypy src/engine.py` → Success(또는 사전존재 무관, 신규 라인 클린).
- [ ] **Step 3:** `ruff check src/engine.py tests/test_engine_market.py` → 변경/신규 클린.
- [ ] **Step 4: 커밋**

```bash
git add src/engine.py tests/test_engine_market.py
git commit -m "feat(engine): MarketProfile/provider 주입 + 시간대 주입 + create_for_market (P3c-1, KRX 행동불변)"
```

---

## Self-Review
**1. Spec coverage:** §14-1 팩토리+주입 ✓, §14-2 시간대 주입(`_KST`→`self._tz`) ✓. 해외 provider 실제 연결/어댑터(§14-3)는 P3c-2 — 의도적 분리.
**2. Placeholder:** 모든 step 실제 코드/명령. US 팩토리는 "프로파일/시간대만, 매매는 P3c-2"로 명시(미완 아님, 점진).
**3. Type consistency:** `__init__` 키워드 파라미터(`market_profile: MarketProfile|None`, `quote: QuoteProvider|None` 등)와 `self._quote: QuoteProvider` 일치. `KRX_PROFILE`/`get_market_profile`/`MarketProfile`은 P1 profile.py 심볼. `QuoteProvider`/`OrderProvider`/`AccountProvider`는 P1 protocols.py. 기존 `QuoteAPI`/`OrderAPI`/`AccountAPI`가 해당 Protocol 만족(P1에서 고정).
**4. 행동불변:** 주입 없으면 `KRX_PROFILE`+국내 API+Asia/Seoul → 기존과 동일. 기존 엔진 테스트가 검출.

## Execution Handoff
P3c-2(주문/시세 얇은 어댑터 + US provider 실제 연결)로 이어감.
