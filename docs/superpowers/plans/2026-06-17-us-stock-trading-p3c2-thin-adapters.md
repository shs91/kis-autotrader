# P3c-2: 얇은 어댑터 (시세/주문/잔고 시장분기 집약) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 사이클이 `self._quote/_order/_account`를 직접 호출하던 지점을 **엔진 private 어댑터**로 치환하고, 각 어댑터 **안에서만** `if self._market.is_overseas` 분기한다. KRX는 완전 passthrough(**바이트 불변**), US는 Overseas* provider로 실제 구동된다(시세→전략→리스크→매수가능→지정가 주문→잔고). 전략·리스크·사이클 로직은 시장 무관 유지(§14-3).

**확정 결정 (사용자 승인):**
1. **지정가 = 현재가 그대로** (슬리피지 버퍼는 P4).
2. **기능 완결 시드** — 시세+주문+잔고정규화+매수가능+거래소resolve+최소 US watchlist 파싱을 한 PR로. main/scheduler 배선만 P3c-6.
3. **엔진 핫패스 float 통일** — 정밀도-aware 포맷헬퍼(`_fmt_price`)+profile기반 DB경계 변환(`_norm_price`)으로 KRX 로그/메트릭/DB 바이트 불변. Numeric 컬럼 전환은 P3c-3.

**의도적 비범위(이번 단계 미변경, 후속 단계 소관):**
- `trades.price`/`total_amount` **Numeric 컬럼** 전환 → **P3c-3**(운영자 액션, 별도 PR). US 가격은 컬럼이 Integer인 동안 DB에서 절단(엔진은 float 보존). US 카나리는 P5라 무방.
- DB payload `market`/`currency` 부착 + `"KOSPI"` 하드코딩(2748·2826) → **P3c-4**(일관 처리). 
- 잔고/결산 로그의 `"원"`/`%.0f` 통화기호화 → **notify/formatter 단계**. KRX 로그 텍스트 보존 위해 이번 단계 미변경.
- `profit_loss_amount=int(...)`·`RiskManager.record_trade_result(int)` 손익누적 타입 → **P3c-3/risk 범위**. 이번 단계 `int()` 유지(KRX 리스크 게이트 불변).
- 해외 체결조회(`get_executions`)·슬리피지 실측 → US는 no-op(빈 리스트). 결산은 KRX 주간 프로세스 소관.

**Architecture:**
```
사이클 로직(시장무관) ── 호출 ──▶ 어댑터(엔진 private) ──┬─ is_overseas=False ─▶ self._quote/_order/_account (국내, passthrough)
                                                      └─ is_overseas=True  ─▶ self._overseas_quote/_order/_account (Decimal·EXCD·지정가)
거래소 resolve: self._exchanges[code]=OVRS_EXCG_CD(4자리)  ← US watchlist 파싱 + 잔고 holdings 시드
가격: _Quote/_Bar(float) DTO ─ _fmt_price(로그)·_norm_price(DB경계) 로 KRX 바이트 불변
```

**검증 환경:** worktree, 메인 `.venv`. 기존 엔진 테스트(`tests/test_engine_db_integration.py`, `tests/test_engine_market.py`)가 **KRX 행동불변 회귀 검출기**.

> **어댑버설 리뷰 반영(2026-06-17, 구현 전 확정):**
> - **import(BLOCKER)**: engine.py에 `from decimal import Decimal, ROUND_HALF_UP` 추가, `src.api.account` import에 `StockHolding`, `src.api.order` import에 `OrderResult` 추가. `OverseasBalance`는 미사용이므로 import 안 함(ruff F401 회피).
> - **frozen config 테스트(BLOCKER)**: config dataclass는 `frozen=True`라 `monkeypatch.setattr(settings.trading, ...)` 불가(`FrozenInstanceError`). 테스트는 `e._exchanges` 직접 시드로 `_exchange_of` 검증 + env 파싱은 `monkeypatch.setenv`+`TradingConfig()` 신규 인스턴스로 분리.
> - **로그 바이트 불변 규칙(정정)**: `%d`/`%.0f` 가격 로그는 float에도 KRX 바이트 동일(`"%d" % 70000.0 == "70000"`)이라 **미변경**. **콤마 f-string `f"{x:,}"`만** `_fmt_price`로(현재가 사이트 888·1135). `%s` 가격 사이트(1171·1304 price)는 float화로 `"0.0"`/`"5.0"` 회귀하므로 **`%s`→`%d`** 로(값만, min_price 등 다른 인자 미변경). `fill_price`는 `_norm_price`라 KRX int → 기존 `f"{fill_price:,}"`(1434·1549·1823) **그대로 안전**(미변경).
> - **이름 프리페치 2656·2769(MAJOR)**: `_get_current` 치환 **철회**(US에서 한글명 미반환+EXCD fallback 경고스팸). `_prefetch_stock_names`/`_seed_watchlist_from_env` 상단에 `if self._market.is_overseas: return` 가드. KRX는 가드 미진입 → 불변.
> - **가격 정규화 정밀(개선)**: `_norm_price`(DB/fill, KRX int·US round)와 `_order_price`(주문 Decimal)를 **Decimal `ROUND_HALF_UP`** 로 구현(float round의 banker's rounding/.xx5 경계 회피).
> - **잔고 dedup(개선)**: `_fetch_overseas_balance`는 거래소 순회 중 동일 symbol 중복을 dict last-wins로 합쳐 보유 이중계산 방지.
> - **config 컨벤션**: `_env_float` 헬퍼 사용. `_Quote`는 소비 필드만(`stock_code, stock_name, current_price`) — `raw_data` 제거(미소비).
> - **deposit(문서화)**: US `deposit=us_cash_budget` 상수는 사이징 상류 입력이나, 매수 수량은 `min(position_size, _get_buyable_qty(=브로커 orderable_qty))`로 캡되어 **과대주문 불가**(과소면 매수 보류 — 안전). 실예수금 연동은 P4.

---

## 파일 구조
| 파일 | 변경 | 종류 |
|------|------|------|
| `src/config.py` | `trading.watchlist_us`(WATCHLIST_CODES_US 파싱), `trading.us_cash_budget`(US_CASH_BUDGET), `screening.min_price_us` 추가 | Modify |
| `src/engine.py` | overseas import + provider 주입 + `_exchanges`/`_exchange_of`/`_quote_excd` + 어댑터 7종 + `_Quote`/`_Bar` DTO + `_fmt_price`/`_norm_price` + 호출부 치환 + PendingOrder(float price + exchange) | Modify |
| `tests/test_engine_us_adapters.py` | US 어댑터 분기·거래소resolve·float정규화·지정가주문 + KRX 불변 테스트 | Create |

---

### Task 1: provider 주입 + 거래소 resolve + config (구조 골격)

- [ ] **Step 1: 실패 테스트** — `tests/test_engine_us_adapters.py` 신설:

```python
"""TradingEngine 멀티마켓 얇은 어댑터(P3c-2) 테스트."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine import TradingEngine
from src.market.profile import US_PROFILE


def _us_engine(**kw):
    return TradingEngine(
        watchlist=["AAPL"],
        market_profile=US_PROFILE,
        overseas_quote=kw.get("oq", MagicMock()),
        overseas_order=kw.get("oo", MagicMock()),
        overseas_account=kw.get("oa", MagicMock()),
    )


def test_us_engine_has_overseas_providers() -> None:
    oq, oo, oa = MagicMock(), MagicMock(), MagicMock()
    e = _us_engine(oq=oq, oo=oo, oa=oa)
    assert e._overseas_quote is oq
    assert e._overseas_order is oo
    assert e._overseas_account is oa


def test_krx_engine_overseas_providers_none() -> None:
    e = TradingEngine()
    assert e._overseas_quote is None
    assert e._overseas_order is None
    assert e._overseas_account is None


def test_exchange_of_krx_is_empty() -> None:
    e = TradingEngine(watchlist=["005930"])
    assert e._exchange_of("005930") == ""


def test_exchange_of_us_from_watchlist(monkeypatch) -> None:
    import src.config as cfg
    monkeypatch.setattr(
        cfg.settings.trading, "watchlist_us", [("AAPL", "NASD"), ("KO", "NYSE")]
    )
    e = TradingEngine(market_profile=US_PROFILE)
    assert e._exchange_of("AAPL") == "NASD"
    assert e._exchange_of("KO") == "NYSE"


def test_quote_excd_converts_to_3digit() -> None:
    e = TradingEngine(
        market_profile=US_PROFILE,
        overseas_quote=MagicMock(),
    )
    e._exchanges["AAPL"] = "NASD"
    assert e._quote_excd("AAPL") == "NAS"  # OVRS_EXCG_CD(4) → EXCD(3)
```

- [ ] **Step 2: RED** — `python -m pytest tests/test_engine_us_adapters.py -q` → AttributeError(`_overseas_quote`/`_exchanges`/`_exchange_of`/`_quote_excd` 없음).

- [ ] **Step 3: config 확장** — `src/config.py` `TradingConfig`(또는 해당 dataclass)에 추가:

```python
    # 미국 관심종목: "AAPL:NASD,MSFT:NASD" 형식 (symbol:OVRS_EXCG_CD)
    watchlist_us: list[tuple[str, str]] = field(
        default_factory=lambda: [
            (s.split(":")[0].strip(), s.split(":")[1].strip())
            for s in _env("WATCHLIST_CODES_US", "").split(",")
            if ":" in s
        ]
    )
    # 미국 사이클 매수 예산(USD) — P3c-2 functional seed용. 실예수금 연동은 P4.
    us_cash_budget: float = field(
        default_factory=lambda: float(_env("US_CASH_BUDGET", "1000"))
    )
```
`ScreeningConfig`에 추가:
```python
    # 미국 매수 하드 가격 플로어(USD). 국내 min_price(KRW)는 통화 단위 불일치.
    min_price_us: float = field(
        default_factory=lambda: float(_env("SCREENING_MIN_PRICE_US", "1"))
    )
```

- [ ] **Step 4: engine import** — `src/engine.py` 상단:
```python
from typing import Any  # 이미 있으면 생략
from src.api.overseas_account import OverseasAccountAPI, OverseasBalance
from src.api.overseas_order import OverseasOrderAPI
from src.api.overseas_quote import OverseasQuoteAPI
from src.api.protocols import (
    OverseasAccountProvider,
    OverseasOrderProvider,
    OverseasQuoteProvider,
)
```

- [ ] **Step 5: `__init__` overseas 주입 + `_exchanges` 시드** — 키워드 파라미터 추가:
```python
        overseas_quote: OverseasQuoteProvider | None = None,
        overseas_order: OverseasOrderProvider | None = None,
        overseas_account: OverseasAccountProvider | None = None,
```
body의 provider 생성부(현 109-114) 다음에:
```python
        self._overseas_quote: OverseasQuoteProvider | None = overseas_quote
        self._overseas_order: OverseasOrderProvider | None = overseas_order
        self._overseas_account: OverseasAccountProvider | None = overseas_account
        if self._market.is_overseas:
            self._overseas_quote = overseas_quote or OverseasQuoteAPI(client=self._client)
            self._overseas_order = overseas_order or OverseasOrderAPI(client=self._client)
            self._overseas_account = (
                overseas_account or OverseasAccountAPI(client=self._client)
            )
        # code → 주문 거래소코드(OVRS_EXCG_CD, 4자리) 매핑. KRX는 빈 dict(no-op).
        self._exchanges: dict[str, str] = {}
        if self._market.is_overseas:
            self._exchanges = {
                sym: exc for sym, exc in settings.trading.watchlist_us
            }
```
`_fixed_watchlist` 설정부: US이고 watchlist 미지정이면 US watchlist 심볼로 시드:
```python
        if watchlist is None and self._market.is_overseas:
            self._fixed_watchlist = [s for s, _ in settings.trading.watchlist_us]
        else:
            self._fixed_watchlist = watchlist
```
(기존 `self._fixed_watchlist = watchlist` 라인 교체.)

- [ ] **Step 6: resolve 헬퍼 추가** — 클래스 메서드로:
```python
    def _exchange_of(self, code: str) -> str:
        """종목코드의 주문 거래소코드(OVRS_EXCG_CD, 4자리)를 반환한다. KRX는 빈 문자열."""
        if not self._market.is_overseas:
            return ""
        exc = self._exchanges.get(code)
        if exc:
            return exc
        default = self._market.exchanges[0] if self._market.exchanges else ""
        logger.warning("[거래소 미해결] %s — 기본 거래소 %s 사용", code, default)
        return default

    def _quote_excd(self, code: str) -> str:
        """시세 조회용 거래소코드(EXCD, 3자리)를 반환한다(OVRS_EXCG_CD→EXCD 변환)."""
        exc = self._exchange_of(code)
        return self._market.quote_exchange_map.get(exc, exc)
```

- [ ] **Step 7: `create_for_market` 갱신** — P3c-1 docstring 갱신(US도 어댑터로 실제 구동), 본문은 그대로(`__init__`이 is_overseas 분기 처리). docstring의 "주문/시세 어댑터는 P3c-2에서 추가" 문구를 "P3c-2 완료: 어댑터로 시장별 구동" 으로.

- [ ] **Step 8: GREEN** — `python -m pytest tests/test_engine_us_adapters.py -q` (Task1 테스트) PASS.

---

### Task 2: 시세 어댑터 + float DTO + 포맷/정규화 헬퍼

- [ ] **Step 1: 실패 테스트 추가** (`tests/test_engine_us_adapters.py`):
```python
@pytest.mark.asyncio
async def test_get_current_us_decimal_to_float() -> None:
    from src.api.overseas_quote import OverseasCurrentPrice
    oq = MagicMock()
    oq.get_current_price = AsyncMock(return_value=OverseasCurrentPrice(
        symbol="AAPL", exchange="NAS", last=Decimal("150.25"),
        base=Decimal("149"), change_rate=0.8, volume=100,
        high=Decimal("151"), low=Decimal("149"), open=Decimal("150"), raw_data={},
    ))
    e = _us_engine(oq=oq)
    e._exchanges["AAPL"] = "NASD"
    q = await e._get_current("AAPL")
    assert q.current_price == 150.25          # float, 센트 보존
    assert isinstance(q.current_price, float)
    oq.get_current_price.assert_awaited_with("AAPL", "NAS")  # EXCD 3자리

@pytest.mark.asyncio
async def test_get_current_krx_passthrough() -> None:
    from src.api.quote import CurrentPrice
    q_api = MagicMock()
    q_api.get_current_price = AsyncMock(return_value=CurrentPrice(
        stock_code="005930", stock_name="삼성전자", current_price=70000,
        change_price=100, change_rate=0.1, volume=10, high_price=70100,
        low_price=69900, open_price=70000, raw_data={},
    ))
    e = TradingEngine(watchlist=["005930"], quote=q_api)
    q = await e._get_current("005930")
    assert q.current_price == 70000.0
    assert q.stock_name == "삼성전자"
    q_api.get_current_price.assert_awaited_with("005930")  # 인자 1개(국내)

def test_fmt_price_integer_valued_no_decimal() -> None:
    e = TradingEngine()
    assert e._fmt_price(70000.0) == "70,000"     # KRX 바이트 불변
    assert e._fmt_price(150.25) == "150.25"      # US 센트

def test_norm_price_krx_int_us_round() -> None:
    assert TradingEngine()._norm_price(70000.0) == 70000   # precision 0 → int
    e = TradingEngine(market_profile=US_PROFILE, overseas_quote=MagicMock())
    assert e._norm_price(150.256) == 150.26                # precision 2 → round
```

- [ ] **Step 2: RED** 확인.

- [ ] **Step 3: DTO + 헬퍼 추가** — `TradingEngine` 위(모듈 레벨)에 DTO:
```python
@dataclass
class _Quote:
    """어댑터 정규화 현재가 — 시장 무관 float 가격."""
    stock_code: str
    stock_name: str
    current_price: float
    raw_data: dict[str, Any]


@dataclass
class _Bar:
    """어댑터 정규화 일봉 — 종가 float."""
    date: str
    close: float
```
헬퍼(메서드):
```python
    def _fmt_price(self, value: float) -> str:
        """가격 로그 포맷. 정수값은 천단위(소수점 없음), 소수는 2자리. KRX 정수가 → 바이트 불변."""
        return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"

    def _norm_price(self, value: float) -> float:
        """DB/주문 경계 가격 정규화. KRX(precision 0)는 int, US(2)는 round(2). KRX 바이트 불변."""
        if self._market.price_precision == 0:
            return int(value)
        return round(value, self._market.price_precision)
```

- [ ] **Step 4: `_get_current` 어댑터 추가**:
```python
    async def _get_current(self, code: str) -> _Quote:
        """현재가를 시장 무관 _Quote(float)로 조회한다."""
        if self._market.is_overseas:
            assert self._overseas_quote is not None
            oc = await self._overseas_quote.get_current_price(code, self._quote_excd(code))
            return _Quote(code, code, float(oc.last), oc.raw_data)
        cp = await self._quote.get_current_price(code)
        return _Quote(cp.stock_code, cp.stock_name, float(cp.current_price), cp.raw_data)
```

- [ ] **Step 5: `_fetch_daily` 어댑터 + `_get_daily_df` 치환**:
```python
    async def _fetch_daily(self, code: str) -> list[_Bar]:
        """일봉을 시장 무관 _Bar(float close, 최신→과거) 리스트로 조회한다."""
        if self._market.is_overseas:
            assert self._overseas_quote is not None
            rows = await self._overseas_quote.get_daily_price(code, self._quote_excd(code))
            return [_Bar(r.date, float(r.close)) for r in rows]
        items = await self._quote.get_daily_price(code)
        return [_Bar(it.date, float(it.close_price)) for it in items]
```
`_get_daily_df`(현 262): `daily_prices = await self._quote.get_daily_price(stock_code)` → `daily_prices = await self._fetch_daily(stock_code)`. DataFrame build(276)의 `item.close_price` → `item.close` (date는 `item.date` 동일). 나머지(min_daily_count·metric·cache) 불변.

- [ ] **Step 6: 현재가 소비부 4곳 치환 + 타입 완화** —
  - 872, 1124: `current = await self._quote.get_current_price(stock_code)` → `await self._get_current(stock_code)`.
  - 2656, 2769: 동일 치환(이름 해결 경로 — US도 EXCD 주입돼 동작).
  - `_resolve_current_stock_name(self, current: CurrentPrice, ...)`(1085) 시그니처 → `current: _Quote`. body가 `current.stock_name`/`current.raw_data`만 읽는지 확인 후 그대로(읽는 필드 동일).
  - `_process_held_stock(self, ..., current_price: int, ...)`(1148) → `current_price: float`. `<= 0` 가드·`float(current_price)` 산술 그대로(float 무해). 로그 `%d`(1193 등) → `%s` + `self._fmt_price(current_price)`. 메트릭 `int(current_price)`(1175) 유지(KRX int 불변, US 관측 절단 허용).
  - `_evaluate_held_without_daily`(1124~): `int(current.current_price)` 메트릭 유지, 로그 `f"{current.current_price:,}"` → `self._fmt_price(current.current_price)`.
  - 현재가 로그 `f"{current.current_price:,}"`(888) → `self._fmt_price(current.current_price)`.

- [ ] **Step 7: GREEN** — Task2 테스트 PASS. **회귀**: `python -m pytest tests/test_engine_db_integration.py tests/test_engine_market.py -q` PASS(KRX 시세 경로 불변).

---

### Task 3: 잔고 어댑터 (정규화 + 매수가능 + 체결조회 가드)

- [ ] **Step 1: 실패 테스트 추가**:
```python
@pytest.mark.asyncio
async def test_get_balance_us_normalizes_and_seeds_exchange() -> None:
    from src.api.overseas_account import OverseasBalance, OverseasHolding
    oa = MagicMock()
    oa.get_balance = AsyncMock(side_effect=lambda exchange, currency="USD": OverseasBalance(
        holdings=[OverseasHolding(
            symbol="AAPL", exchange=exchange, quantity=3, avg_price=Decimal("100.50"),
            current_price=Decimal("150.25"), eval_amount=Decimal("450.75"),
            profit_loss=Decimal("149.25"), profit_rate=49.5, currency="USD",
        )] if exchange == "NASD" else [],
        currency="USD", raw_response={},
    ))
    e = _us_engine(oa=oa)
    bal = await e._get_balance(force=True)
    assert bal.deposit == 1000              # us_cash_budget (default)
    h = next(x for x in bal.holdings if x.stock_code == "AAPL")
    assert h.quantity == 3
    assert h.avg_price == 100.50            # 센트 보존(float)
    assert e._exchange_of("AAPL") == "NASD"  # 잔고에서 거래소 시드됨

@pytest.mark.asyncio
async def test_get_buyable_qty_us() -> None:
    from src.api.overseas_account import OverseasBuyable
    oa = MagicMock()
    oa.get_buyable_amount = AsyncMock(return_value=OverseasBuyable(
        orderable_cash=Decimal("1000"), orderable_qty=6, raw={}))
    e = _us_engine(oa=oa)
    e._exchanges["AAPL"] = "NASD"
    qty = await e._get_buyable_qty("AAPL", 150.25)
    assert qty == 6
    oa.get_buyable_amount.assert_awaited_with("AAPL", "NASD", Decimal("150.25"))

@pytest.mark.asyncio
async def test_get_executions_us_noop() -> None:
    e = _us_engine()
    assert await e._get_executions() == []
```

- [ ] **Step 2: RED** 확인.

- [ ] **Step 3: `_get_balance` 분기** — 현 297-315 본문에서 `balance = await self._account.get_balance()`를 어댑터 분기로:
```python
        if self._market.is_overseas:
            balance = await self._fetch_overseas_balance()
        else:
            balance = await self._account.get_balance()
```
신규 메서드:
```python
    async def _fetch_overseas_balance(self) -> Balance:
        """해외 거래소별 잔고를 합산해 국내 Balance 형태로 정규화한다.

        deposit은 us_cash_budget(설정 예산)로 둔다(실예수금 연동은 P4). 실제 주문
        한도는 _get_buyable_qty(브로커 orderable_qty)가 캡한다. total_*는 0(결산은
        KRX 주간 프로세스 소관). holdings의 거래소는 self._exchanges에 시드한다.
        """
        assert self._overseas_account is not None
        holdings: list[StockHolding] = []
        for exch in self._market.exchanges:
            ob = await self._overseas_account.get_balance(exch, self._market.currency)
            for oh in ob.holdings:
                self._exchanges[oh.symbol] = oh.exchange or exch
                holdings.append(StockHolding(
                    stock_code=oh.symbol,
                    stock_name=oh.symbol,
                    quantity=oh.quantity,
                    avg_price=float(oh.avg_price),
                    current_price=int(round(oh.current_price)),
                    eval_amount=int(round(oh.eval_amount)),
                    profit_loss=int(round(oh.profit_loss)),
                    profit_rate=oh.profit_rate,
                ))
        return Balance(
            deposit=int(settings.trading.us_cash_budget),
            total_eval_amount=0,
            total_profit_loss=0,
            total_profit_rate=0.0,
            holdings=holdings,
            raw_response={},
        )
```
> 주: `StockHolding.current_price`(int)는 매매판단 경로가 쓰지 않음(판단은 라이브 `_get_current` + `holding["avg_price"]` float). 정밀 current_price 보존은 P3c-4 portfolio sync에서.

- [ ] **Step 4: `_get_buyable_qty` 분기**(현 321-332):
```python
    async def _get_buyable_qty(self, stock_code: str, price: float) -> int | None:
        try:
            if self._market.is_overseas:
                assert self._overseas_account is not None
                b = await self._overseas_account.get_buyable_amount(
                    stock_code, self._exchange_of(stock_code),
                    Decimal(str(self._norm_price(price))),
                )
                return b.orderable_qty
            buyable = await self._account.get_buyable(stock_code, int(price))
            return buyable.nrcvb_buy_qty
        except Exception:
            logger.debug("매수가능조회 실패: %s", stock_code)
            return None
```
(시그니처 `price: float`로 — 호출부 1052가 이미 `float(current.current_price)` 전달.)

- [ ] **Step 5: `_get_executions` 가드** — 현재 직접 `self._account.get_executions()` 호출 2곳(679·1628)을 어댑터로:
```python
    async def _get_executions(self) -> list[Execution]:
        """당일 체결 내역. 해외는 미지원 → 빈 리스트(결산/슬리피지 no-op)."""
        if self._market.is_overseas:
            return []
        return await self._account.get_executions()
```
679·1628의 `await self._account.get_executions()` → `await self._get_executions()`.

- [ ] **Step 6: GREEN** — Task3 테스트 PASS. **회귀**: 엔진 통합/마켓 테스트 green(KRX 잔고 경로: `is_overseas=False`라 기존 `self._account.get_balance()` 그대로).

---

### Task 4: 주문 어댑터 (매수/매도/취소) + PendingOrder + 가격 정규화

- [ ] **Step 1: 실패 테스트 추가**:
```python
@pytest.mark.asyncio
async def test_place_buy_us_limit_order() -> None:
    from src.api.order import OrderResult
    oo = MagicMock()
    oo.buy = AsyncMock(return_value=OrderResult("ODNO1", "0930", "ok", {}))
    e = _us_engine(oo=oo)
    e._exchanges["AAPL"] = "NASD"
    await e._place_buy("AAPL", 2, 150.25)
    oo.buy.assert_awaited_with(
        symbol="AAPL", exchange="NASD", quantity=2,
        price=Decimal("150.25"), order_type="00",   # 지정가, 현재가 그대로
    )

@pytest.mark.asyncio
async def test_place_buy_krx_market_order_passthrough() -> None:
    from src.api.order import OrderResult
    o_api = MagicMock()
    o_api.buy = AsyncMock(return_value=OrderResult("O1", "t", "ok", {}))
    e = TradingEngine(watchlist=["005930"], order=o_api)
    await e._place_buy("005930", 5, 70000.0)
    o_api.buy.assert_awaited_with(stock_code="005930", quantity=5)  # 시장가, price 미전달

@pytest.mark.asyncio
async def test_cancel_order_us_uses_exchange() -> None:
    oo = MagicMock(); oo.cancel = AsyncMock()
    e = _us_engine(oo=oo)
    e._exchanges["AAPL"] = "NASD"
    await e._cancel_order("AAPL", "ODNO1", 2)
    oo.cancel.assert_awaited_with(order_no="ODNO1", symbol="AAPL", exchange="NASD", quantity=2)
```

- [ ] **Step 2: RED** 확인.

- [ ] **Step 3: 주문 어댑터 3종 추가**:
```python
    async def _place_buy(self, code: str, quantity: int, ref_price: float) -> OrderResult:
        """매수 발행. KRX 시장가(수량만), US 지정가(ref_price 한도)."""
        if self._market.is_overseas:
            assert self._overseas_order is not None
            return await self._overseas_order.buy(
                symbol=code, exchange=self._exchange_of(code), quantity=quantity,
                price=Decimal(str(self._norm_price(ref_price))), order_type="00",
            )
        return await self._order.buy(stock_code=code, quantity=quantity)

    async def _place_sell(self, code: str, quantity: int, ref_price: float) -> OrderResult:
        """매도 발행. KRX 시장가(수량만), US 지정가(ref_price 한도)."""
        if self._market.is_overseas:
            assert self._overseas_order is not None
            return await self._overseas_order.sell(
                symbol=code, exchange=self._exchange_of(code), quantity=quantity,
                price=Decimal(str(self._norm_price(ref_price))), order_type="00",
            )
        return await self._order.sell(stock_code=code, quantity=quantity)

    async def _cancel_order(self, code: str, order_no: str, quantity: int) -> OrderResult:
        """미체결 취소. KRX (order_no,stock_code,qty), US (order_no,symbol,exchange,qty)."""
        if self._market.is_overseas:
            assert self._overseas_order is not None
            return await self._overseas_order.cancel(
                order_no=order_no, symbol=code,
                exchange=self._exchange_of(code), quantity=quantity,
            )
        return await self._order.cancel(
            order_no=order_no, stock_code=code, quantity=quantity,
        )
```

- [ ] **Step 4: 호출부 치환 + 타입 완화** —
  - `_execute_buy`(1287): 시그니처 `price: int` → `price: float`. 가격 플로어(1301-1302) `min_price = settings.screening.min_price` → `min_price = settings.screening.min_price_us if self._market.is_overseas else settings.screening.min_price`. 발행(1363) `result = await self._order.buy(stock_code=stock_code, quantity=quantity)` → `result = await self._place_buy(stock_code, quantity, price)`. `fill_price = int(price)`(1419) → `fill_price = self._norm_price(price)`. PendingOrder(1409-1413) `price=int(price)` → `price=self._norm_price(price)`, `exchange=self._exchange_of(stock_code)` 추가. 로그 `f"{fill_price:,}원"`(1434) → `f"{self._fmt_price(fill_price)}원"`. `_record_trade_to_db`/`_record_order_to_db` 호출은 그대로(price=float 전달, 내부에서 정규화 — Step 6).
  - `_execute_sell`(1468): `price: int` → `price: float`. 발행(1502) `self._order.sell(...)` → `self._place_sell(stock_code, quantity, price)`. `fill_price = int(price)`(1539) → `self._norm_price(price)`. PendingOrder(1529-1534) `price=int(price)` → `self._norm_price(price)`, `exchange=...` 추가. 로그 `f"{fill_price:,}원"`(1549) → `f"{self._fmt_price(fill_price)}원"`.
  - `_process_held_stock`의 `_execute_sell(... current_price ...)` 호출들(1196·1233·1245·1258·1268): `current_price`가 이제 float — 그대로 전달.
  - `_execute_buy` 호출(1080-1082): `current.current_price`가 이제 float — 그대로.
  - `_cancel_pending_order`(1770): `self._order.cancel(order_no=..., stock_code=stock_code, quantity=...)` → `self._cancel_order(stock_code, pending.order_no, pending.quantity)`.
  - `_reconcile_orphan_fill`(1806~): `fill_price = int(pending.price)` → `self._norm_price(pending.price)`. 로그 `:,원` → `_fmt_price`.

- [ ] **Step 5: PendingOrder 필드 추가** — dataclass(60-83)에 `price: int = 0` → `price: float = 0.0`, 끝에 `exchange: str = ""` 추가(기본값 → 기존 KRX 등록 호출 불변).

- [ ] **Step 6: DB 경계 가격 정규화** — `_record_trade_to_db`(1944) 시그니처 `price: int` → `price: float`. body 진입부에서 `price = self._norm_price(price)`로 정규화(KRX int·US round2). `profit_loss_amount = int((price - avg_price) * quantity)` **유지**(KRX 손익·RiskManager 입력 불변; US 절단은 P3c-3). payload `"price": price`/`"total_amount": price * quantity`는 정규화된 값(KRX int → 바이트 불변). `_record_order_to_db`(2731)는 이미 `price: float` — 호출부 `float(price)` 그대로(orders.price는 Float 컬럼).

- [ ] **Step 7: GREEN** — Task4 테스트 PASS. **회귀**: 엔진 통합/마켓 테스트 green.

---

### Task 5: 전체 회귀 + 정적검증 + 커밋

- [ ] **Step 1: 신규 테스트 전체** — `python -m pytest tests/test_engine_us_adapters.py -q` PASS.
- [ ] **Step 2: KRX 행동불변 회귀** — `python -m pytest tests/test_engine_db_integration.py tests/test_engine_market.py tests/test_config.py -q` PASS. (실패 시 KRX 회귀 — 어댑터 KRX 분기 또는 _fmt_price/_norm_price/포맷 치환 점검.)
- [ ] **Step 3: 시장 전체 회귀** — `python -m pytest tests/ -q` (사전존재 실패는 메모리 `project_real_env_pytest_preexisting_failures` 대조 — 신규 회귀만 차단).
- [ ] **Step 4: 타입** — `python -m mypy src/engine.py src/config.py` → Success(또는 신규 라인 클린, 사전존재 무관).
- [ ] **Step 5: 린트** — `ruff check src/engine.py src/config.py tests/test_engine_us_adapters.py` → 변경/신규 클린(베이스라인 부채는 메모리 `project_ruff_baseline_dirty` 대조).
- [ ] **Step 6: 구현 이력 + 커밋**
```bash
python scripts/record_implementation.py ...   # DB 기록 + CHANGELOG rolling
git add src/engine.py src/config.py tests/test_engine_us_adapters.py docs/superpowers/plans/2026-06-17-us-stock-trading-p3c2-thin-adapters.md
git commit -m "feat(engine): 얇은 어댑터 — 시세/주문/잔고 시장분기 집약 + US 구동 (P3c-2, KRX 행동불변)"
```

---

## Self-Review
**1. Spec coverage:** §14-3 얇은 어댑터(주문/시세/잔고, is_overseas 분기 집약) ✓. §14-7 종목→거래소 resolve(`_exchanges` + watchlist 파싱 + 잔고 시드) ✓. 지정가=현재가 ✓. float 핫패스 ✓. Numeric(P3c-3)·DB payload market/currency·"KOSPI"(P3c-4)는 의도적 비범위.
**2. Placeholder 없음:** 모든 step 실제 코드/명령. deposit=예산(P4 실예수금 연동)·current_price int 보존(P3c-4)은 미완이 아니라 점진(명시).
**3. Type consistency:** 어댑터 반환은 `_Quote`/`_Bar`(float)·`Balance`·`OrderResult`·`int`로 사이클 소비와 일치. `_overseas_*`는 P1 `Overseas*Provider` Protocol, 구현체는 P2 `Overseas*API`. `_norm_price`/`_fmt_price`는 `self._market.price_precision` 기반.
**4. KRX 행동불변:** 모든 어댑터의 `is_overseas=False` 분기가 기존 호출과 인자까지 동일(시장가 price 미전달, get_balance 무인자, cancel 3인자, int(price) buyable). `_fmt_price`는 정수값을 ".0" 없이 → 로그 바이트 불변. `_norm_price`는 precision 0에서 int → DB/payload 바이트 불변. `profit_loss_amount`/risk 입력 int 유지. 기존 엔진 테스트가 검출기.
**5. 위험·완화:** (a) `_resolve_current_stock_name` 시그니처 `CurrentPrice`→`_Quote` — 읽는 필드(stock_name/raw_data) 동일 확인 후 변경. (b) US 잔고 N거래소 호출 = API 3배 → 야간·분리앱키라 초당 한도 독립(§9), 사이클 간격은 P3c-6에서 조정. (c) 거래소 미해결 fallback은 경고+첫 거래소 — watchlist/잔고 미시드 종목 방어.

## Execution Handoff
P3c-3(price Numeric 마이그, 운영자 액션·별도 PR) 또는 P3c-4(DB payload market/currency + "KOSPI"→market_code)로 이어감.
