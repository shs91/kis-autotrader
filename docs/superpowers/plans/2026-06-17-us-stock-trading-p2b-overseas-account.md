# P2b: 해외 잔고(Account) API 구현 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 해외 잔고/매수가능금액 조회용 `OverseasAccountAPI`(`get_balance`, `get_buyable_amount`)를 구현한다. 가격/금액은 `Decimal`, 통화는 명시 필드. **국내 코드 0 변경.**

**Architecture:** P2a와 동형 — 해외 전용 dataclass(`OverseasHolding`/`OverseasBalance`/`OverseasBuyable`, 금액 `Decimal`) + `OverseasAccountProvider` Protocol. `_get`/`_decimal`은 `src/api/overseas_quote`에서 재사용(DRY). 계좌 자격증명(CANO/ACNT_PRDT_CD)은 기존 `AccountAPI` 패턴대로 `settings.kis`에서 읽되, 시장별 주입은 P3에서 배선한다.

**Tech Stack:** P2a와 동일.

**확정 사실(spec §2.1):** 잔고 `inquire-balance` TTTS3012R/VTTS3012R(params: CANO/ACNT_PRDT_CD/OVRS_EXCG_CD/TR_CRCY_CD/CTX_AREA_FK200/NK200; output1 보유종목). 매수가능금액 `inquire-psamount` TTTS3007R/VTTS3007R. **거래소코드는 주문체계 OVRS_EXCG_CD(NASD/NYSE/AMEX)** — 시세 EXCD(NAS)와 다름. 응답 필드는 confidence=medium → 실측 재확인.

**검증 환경:** worktree, `/Users/.../.venv/bin/python -m pytest|mypy|ruff`.

---

## 파일 구조

| 파일 | 책임 | 종류 |
|------|------|------|
| `src/api/overseas_account.py` | 해외 잔고 dataclass + `OverseasAccountAPI` | Create |
| `src/api/protocols.py` | `OverseasAccountProvider` Protocol 추가 | Modify |
| `tests/test_api/test_overseas_account.py` | 단위 테스트(AsyncMock) | Create |

---

### Task 1: 해외 잔고 dataclass + OverseasAccountAPI.get_balance + Protocol

**Files:** Create `src/api/overseas_account.py`; Modify `src/api/protocols.py`; Test `tests/test_api/test_overseas_account.py`.

- [ ] **Step 1: 실패 테스트** — `tests/test_api/test_overseas_account.py`:

```python
"""해외 잔고 API(OverseasAccountAPI) 테스트."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

from src.api.overseas_account import (
    OVERSEAS_BALANCE_PATH,
    OverseasAccountAPI,
    OverseasBalance,
    OverseasBuyable,
    OverseasHolding,
)
from src.api.protocols import OverseasAccountProvider


def test_satisfies_protocol() -> None:
    assert issubclass(OverseasAccountAPI, OverseasAccountProvider)


def test_dataclass_shapes() -> None:
    h = OverseasHolding(
        symbol="AAPL", exchange="NASD", quantity=10,
        avg_price=Decimal("149.00"), current_price=Decimal("150.25"),
        eval_amount=Decimal("1502.50"), profit_loss=Decimal("12.50"),
        profit_rate=0.84, currency="USD",
    )
    assert h.eval_amount == Decimal("1502.50")
    b = OverseasBalance(holdings=[h], currency="USD", raw_response={})
    assert b.holdings[0].symbol == "AAPL"


class TestGetBalance:
    def _api(self, response: dict[str, object]) -> OverseasAccountAPI:
        c = AsyncMock()
        c.get.return_value = response
        return OverseasAccountAPI(client=c)

    async def test_parses_holdings_decimal(self) -> None:
        response = {
            "output1": [
                {
                    "ovrs_pdno": "AAPL",
                    "ovrs_excg_cd": "NASD",
                    "ovrs_cblc_qty": "10",
                    "pchs_avg_pric": "149.00",
                    "now_pric2": "150.25",
                    "ovrs_stck_evlu_amt": "1502.50",
                    "frcr_evlu_pfls_amt": "12.50",
                    "evlu_pfls_rt": "0.84",
                    "tr_crcy_cd": "USD",
                },
                {"ovrs_pdno": "ZERO", "ovrs_cblc_qty": "0"},
            ],
        }
        api = self._api(response)
        bal = await api.get_balance("NASD")
        assert len(bal.holdings) == 1  # qty<=0 제외
        h = bal.holdings[0]
        assert h.symbol == "AAPL"
        assert h.quantity == 10
        assert h.avg_price == Decimal("149.00")
        assert h.eval_amount == Decimal("1502.50")
        assert h.currency == "USD"

    async def test_sends_excg_and_currency(self) -> None:
        c = AsyncMock()
        c.get.return_value = {"output1": []}
        api = OverseasAccountAPI(client=c)
        await api.get_balance("NASD", currency="USD")
        call = c.get.call_args
        assert call.args[0] == OVERSEAS_BALANCE_PATH
        params = call.kwargs.get("params")
        assert params["OVRS_EXCG_CD"] == "NASD"
        assert params["TR_CRCY_CD"] == "USD"
```

- [ ] **Step 2: RED** — `python -m pytest tests/test_api/test_overseas_account.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: 구현** — `src/api/overseas_account.py`:

```python
"""해외(미국) 잔고/매수가능금액 조회 API 모듈.

응답 금액은 Decimal, 통화는 명시 필드. _get/_decimal은 overseas_quote에서 재사용.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.api.client import KISClient
from src.api.overseas_quote import _decimal, _get
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

OVERSEAS_BALANCE_PATH: str = "/uapi/overseas-stock/v1/trading/inquire-balance"
OVERSEAS_PSAMOUNT_PATH: str = "/uapi/overseas-stock/v1/trading/inquire-psamount"

TR_ID_OVERSEAS_BALANCE_MAP: dict[str, str] = {"virtual": "VTTS3012R", "real": "TTTS3012R"}
TR_ID_OVERSEAS_PSAMOUNT_MAP: dict[str, str] = {"virtual": "VTTS3007R", "real": "TTTS3007R"}


@dataclass
class OverseasHolding:
    """해외 보유종목 (외화 기준)."""

    symbol: str
    exchange: str
    quantity: int
    avg_price: Decimal
    current_price: Decimal
    eval_amount: Decimal
    profit_loss: Decimal
    profit_rate: float
    currency: str


@dataclass
class OverseasBalance:
    """해외 잔고."""

    holdings: list[OverseasHolding]
    currency: str
    raw_response: dict[str, Any]


@dataclass
class OverseasBuyable:
    """해외 매수가능 정보."""

    orderable_cash: Decimal  # 외화 주문가능금액
    orderable_qty: int  # 주문가능수량
    raw: dict[str, Any]


class OverseasAccountAPI:
    """KIS 해외주식 잔고/매수가능금액 조회 API."""

    def __init__(self, client: KISClient | None = None) -> None:
        self._client = client or KISClient()
        self._env = settings.kis.env
        self._account_no = settings.kis.account_no
        self._product_code = settings.kis.account_product_code

    async def get_balance(
        self, exchange: str, currency: str = "USD"
    ) -> OverseasBalance:
        """해외 잔고를 조회한다.

        Args:
            exchange: 주문 거래소코드 OVRS_EXCG_CD ("NASD"/"NYSE"/"AMEX")
            currency: 거래통화코드 ("USD")
        """
        logger.info("[해외 잔고] EXCG=%s CRCY=%s", exchange, currency)
        tr_id = TR_ID_OVERSEAS_BALANCE_MAP.get(self._env, "TTTS3012R")
        params = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "TR_CRCY_CD": currency,
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        response = await self._client.get(
            OVERSEAS_BALANCE_PATH, params=params, tr_id=tr_id
        )
        output1 = response.get("output1", []) or []
        holdings: list[OverseasHolding] = []
        for item in output1:
            qty = int(_get(item, "ovrs_cblc_qty", "0") or "0")
            if qty <= 0:
                continue
            holdings.append(
                OverseasHolding(
                    symbol=_get(item, "ovrs_pdno"),
                    exchange=_get(item, "ovrs_excg_cd") or exchange,
                    quantity=qty,
                    avg_price=_decimal(_get(item, "pchs_avg_pric")),
                    current_price=_decimal(_get(item, "now_pric2")),
                    eval_amount=_decimal(_get(item, "ovrs_stck_evlu_amt")),
                    profit_loss=_decimal(_get(item, "frcr_evlu_pfls_amt")),
                    profit_rate=float(_get(item, "evlu_pfls_rt", "0") or "0"),
                    currency=_get(item, "tr_crcy_cd") or currency,
                )
            )
        return OverseasBalance(
            holdings=holdings, currency=currency, raw_response=response
        )

    async def get_buyable_amount(
        self, symbol: str, exchange: str, price: Decimal
    ) -> OverseasBuyable:
        """해외 매수가능금액을 조회한다(통합증거금 적용분 포함).

        Args:
            symbol: 종목 심볼
            exchange: 주문 거래소코드 OVRS_EXCG_CD
            price: 주문 예정 단가(외화)
        """
        logger.debug("[해외 매수가능] %s.%s @%s", exchange, symbol, price)
        tr_id = TR_ID_OVERSEAS_PSAMOUNT_MAP.get(self._env, "TTTS3007R")
        params = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "OVRS_ORD_UNPR": str(price),
            "ITEM_CD": symbol,
        }
        response = await self._client.get(
            OVERSEAS_PSAMOUNT_PATH, params=params, tr_id=tr_id
        )
        output = response.get("output", {}) or {}
        return OverseasBuyable(
            orderable_cash=_decimal(_get(output, "ord_psbl_frcr_amt")),
            orderable_qty=int(_get(output, "ord_psbl_qty", "0") or "0"),
            raw=output,
        )
```

- [ ] **Step 4: Protocol 추가** — `src/api/protocols.py` import에 `from src.api.overseas_account import OverseasBalance, OverseasBuyable` 추가, 파일 끝에:

```python
@runtime_checkable
class OverseasAccountProvider(Protocol):
    """해외 잔고/매수가능금액 조회 인터페이스."""

    async def get_balance(
        self, exchange: str, currency: str = "USD"
    ) -> OverseasBalance:
        """해외 잔고를 조회한다."""
        ...

    async def get_buyable_amount(
        self, symbol: str, exchange: str, price: Decimal
    ) -> OverseasBuyable:
        """해외 매수가능금액을 조회한다."""
        ...
```

`protocols.py` 상단에 `from decimal import Decimal` 추가(아직 없으면).

- [ ] **Step 5: GREEN + 검증 + 커밋**

```
python -m pytest tests/test_api/test_overseas_account.py -q   # PASS
python -m mypy src/api/overseas_account.py src/api/protocols.py  # Success
ruff check src/api/overseas_account.py src/api/protocols.py tests/test_api/test_overseas_account.py  # passed
git add src/api/overseas_account.py src/api/protocols.py tests/test_api/test_overseas_account.py
git commit -m "feat(api): 해외 잔고 OverseasAccountAPI — 잔고/매수가능금액 + Decimal (P2b)"
```

---

### Task 2: 회귀 + 실측 재확인 표시

- [ ] **Step 1:** `python -m pytest tests/test_api/ tests/test_market/ -q` → PASS.
- [ ] **Step 2:** `python -m mypy src/api/overseas_account.py src/api/overseas_quote.py src/api/protocols.py` → Success.
- [ ] **Step 3(메모, 코드변경 없음):** 실전키 실측에서 잔고 output1 필드명(`ovrs_pdno`/`ovrs_cblc_qty`/`pchs_avg_pric`/`now_pric2`/`ovrs_stck_evlu_amt`/`frcr_evlu_pfls_amt`/`evlu_pfls_rt`/`tr_crcy_cd`)과 매수가능 필드(`ord_psbl_frcr_amt`/`ord_psbl_qty`)를 실제 응답으로 교정. confidence=medium.

---

## Self-Review (작성자 점검 완료)

**1. Spec coverage:** §2.1 잔고(inquire-balance TTTS3012R)·매수가능금액(inquire-psamount TTTS3007R) ✓. 통합잔고(inquire-present-balance CTRP6504R, 원화환산 리포팅용)는 매매 비필수 → P3 리포팅에서 필요 시(YAGNI).
**2. Placeholder scan:** 모든 step 실제 코드/명령. 응답 필드 confidence=medium은 명시적 실측 표시(동작 가정값 + 안전 degrade).
**3. Type consistency:** dataclass 필드(`avg_price/current_price/eval_amount/profit_loss/orderable_cash: Decimal`, `quantity/orderable_qty: int`, `profit_rate: float`), 메서드 시그니처(`get_balance(exchange, currency="USD")`, `get_buyable_amount(symbol, exchange, price: Decimal)`)가 Protocol과 일치. TR_ID 맵 키 virtual/real. `_get`/`_decimal`은 overseas_quote 재사용(동일 시그니처).
**4. 순환 import:** protocols → overseas_account(dataclass) 단방향. overseas_account → overseas_quote(_get/_decimal), client, config. overseas_account는 protocols 미import. ✓

## Execution Handoff
완료 후 P2c(해외 주문)로. P2a~P2c 누적 후 묶어서 PR(순수 코드).
