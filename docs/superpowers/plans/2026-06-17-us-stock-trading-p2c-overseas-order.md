# P2c: 해외 주문(Order) API 구현 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 해외 매수/매도/정정/취소용 `OverseasOrderAPI`를 구현한다. 단가는 `Decimal`, `OrderResult`(기존)는 재사용. **국내 코드 0 변경.**

**Architecture:** P2a/b와 동형. `OverseasOrderProvider` Protocol(반환 `OrderResult` 재사용). 미국 매수=지정가(ORD_DVSN "00")만, 시장가는 `OVRS_ORD_UNPR="0"`. 계좌 자격증명은 `settings.kis`(P3에서 시장별 주입).

**확정 사실(spec §2.1):** 주문 `/trading/order` 매수 TTTT1002U/VTTT1002U·매도 TTTT1006U/VTTT1006U. 정정취소 `/trading/order-rvsecncl` TTTT1004U/VTTT1004U(**confidence=medium → 실측 재확인**). 바디: CANO/ACNT_PRDT_CD/OVRS_EXCG_CD/PDNO/ORD_QTY/OVRS_ORD_UNPR/ORD_SVR_DVSN_CD/ORD_DVSN(+매도 SLL_TYPE). 거래소코드=주문체계 OVRS_EXCG_CD(NASD/NYSE/AMEX).

---

## 파일 구조

| 파일 | 책임 | 종류 |
|------|------|------|
| `src/api/overseas_order.py` | `OverseasOrderAPI`(buy/sell/modify/cancel) | Create |
| `src/api/protocols.py` | `OverseasOrderProvider` Protocol 추가 | Modify |
| `tests/test_api/test_overseas_order.py` | 단위 테스트 | Create |

---

### Task 1: OverseasOrderAPI + Protocol

**Files:** Create `src/api/overseas_order.py`; Modify `src/api/protocols.py`; Test `tests/test_api/test_overseas_order.py`.

- [ ] **Step 1: 실패 테스트** — `tests/test_api/test_overseas_order.py`:

```python
"""해외 주문 API(OverseasOrderAPI) 테스트."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.api.order import OrderResult
from src.api.overseas_order import (
    OVERSEAS_ORDER_PATH,
    OverseasOrderAPI,
)
from src.api.protocols import OverseasOrderProvider
from src.utils.exceptions import OrderError


def test_satisfies_protocol() -> None:
    assert issubclass(OverseasOrderAPI, OverseasOrderProvider)


class TestOrders:
    def _api(self, response: dict[str, object]) -> OverseasOrderAPI:
        c = AsyncMock()
        c.post.return_value = response
        return OverseasOrderAPI(client=c)

    async def test_buy_sends_order_body(self) -> None:
        c = AsyncMock()
        c.post.return_value = {"rt_cd": "0", "msg1": "OK", "output": {"ODNO": "123", "ORD_TMD": "093000"}}
        api = OverseasOrderAPI(client=c)
        result = await api.buy("AAPL", "NASD", 10, Decimal("150.25"))

        assert isinstance(result, OrderResult)
        assert result.order_no == "123"
        call = c.post.call_args
        assert call.args[0] == OVERSEAS_ORDER_PATH
        assert call.kwargs.get("tr_id") in ("TTTT1002U", "VTTT1002U")
        body = call.kwargs.get("body")
        assert body["PDNO"] == "AAPL"
        assert body["OVRS_EXCG_CD"] == "NASD"
        assert body["ORD_QTY"] == "10"
        assert body["OVRS_ORD_UNPR"] == "150.25"
        assert body["ORD_DVSN"] == "00"

    async def test_sell_sets_sll_type_and_tr(self) -> None:
        c = AsyncMock()
        c.post.return_value = {"rt_cd": "0", "msg1": "OK", "output": {"ODNO": "999"}}
        api = OverseasOrderAPI(client=c)
        await api.sell("AAPL", "NASD", 5, Decimal("151.00"))
        call = c.post.call_args
        assert call.kwargs.get("tr_id") in ("TTTT1006U", "VTTT1006U")
        assert call.kwargs.get("body")["SLL_TYPE"] == "00"

    async def test_buy_market_price_zero(self) -> None:
        c = AsyncMock()
        c.post.return_value = {"rt_cd": "0", "output": {"ODNO": "1"}}
        api = OverseasOrderAPI(client=c)
        await api.buy("AAPL", "NASD", 1, Decimal("0"))
        assert api  # noqa: B018 (sanity)
        assert c.post.call_args.kwargs.get("body")["OVRS_ORD_UNPR"] == "0"

    async def test_rejects_on_error_rt_cd(self) -> None:
        api = self._api({"rt_cd": "1", "msg1": "잔고부족"})
        with pytest.raises(OrderError):
            await api.buy("AAPL", "NASD", 10, Decimal("150.25"))

    async def test_cancel_sends_rvsecncl(self) -> None:
        c = AsyncMock()
        c.post.return_value = {"rt_cd": "0", "output": {"ODNO": "1"}}
        api = OverseasOrderAPI(client=c)
        await api.cancel("ORG1", "AAPL", "NASD", 10)
        body = c.post.call_args.kwargs.get("body")
        assert body["ORGN_ODNO"] == "ORG1"
        assert body["RVSE_CNCL_DVSN_CD"] == "02"
```

- [ ] **Step 2: RED** — `python -m pytest tests/test_api/test_overseas_order.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: 구현** — `src/api/overseas_order.py`:

```python
"""해외(미국) 주문 API 모듈 (매수/매도/정정/취소).

단가는 Decimal, 결과는 기존 OrderResult 재사용. 미국 매수는 지정가(ORD_DVSN
"00")만 가능, 시장가는 OVRS_ORD_UNPR="0".
"""

from __future__ import annotations

from decimal import Decimal

from src.api.client import KISClient
from src.api.order import OrderResult
from src.config import settings
from src.utils.exceptions import OrderError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

OVERSEAS_ORDER_PATH: str = "/uapi/overseas-stock/v1/trading/order"
OVERSEAS_ORDER_RVSECNCL_PATH: str = "/uapi/overseas-stock/v1/trading/order-rvsecncl"

TR_ID_OVERSEAS_BUY_MAP: dict[str, str] = {"virtual": "VTTT1002U", "real": "TTTT1002U"}
TR_ID_OVERSEAS_SELL_MAP: dict[str, str] = {"virtual": "VTTT1006U", "real": "TTTT1006U"}
# 정정/취소 공통 (confidence=medium, 실측 재확인 필요)
TR_ID_OVERSEAS_RVSECNCL_MAP: dict[str, str] = {"virtual": "VTTT1004U", "real": "TTTT1004U"}

ORDER_TYPE_LIMIT: str = "00"  # 미국 매수는 지정가만


class OverseasOrderAPI:
    """KIS 해외주식 주문 API."""

    def __init__(self, client: KISClient | None = None) -> None:
        self._client = client or KISClient()
        self._env = settings.kis.env
        self._account_no = settings.kis.account_no
        self._product_code = settings.kis.account_product_code

    async def buy(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_type: str = ORDER_TYPE_LIMIT,
    ) -> OrderResult:
        """해외 매수 주문(미국은 지정가). 시장가는 price=Decimal('0')."""
        logger.info("[해외 매수] %s.%s qty=%d @%s", exchange, symbol, quantity, price)
        return await self._place(
            "buy", symbol, exchange, quantity, price, order_type
        )

    async def sell(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_type: str = ORDER_TYPE_LIMIT,
    ) -> OrderResult:
        """해외 매도 주문."""
        logger.info("[해외 매도] %s.%s qty=%d @%s", exchange, symbol, quantity, price)
        return await self._place(
            "sell", symbol, exchange, quantity, price, order_type
        )

    async def _place(
        self,
        side: str,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_type: str,
    ) -> OrderResult:
        if side == "buy":
            tr_id = TR_ID_OVERSEAS_BUY_MAP.get(self._env, "TTTT1002U")
        else:
            tr_id = TR_ID_OVERSEAS_SELL_MAP.get(self._env, "TTTT1006U")
        body = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": order_type,
        }
        if side == "sell":
            body["SLL_TYPE"] = "00"
        response = await self._client.post(
            OVERSEAS_ORDER_PATH, body=body, tr_id=tr_id, use_hashkey=True
        )
        return self._parse(response)

    async def modify(
        self,
        order_no: str,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
    ) -> OrderResult:
        """해외 주문 정정."""
        logger.info("[해외 정정] ord=%s %s.%s", order_no, exchange, symbol)
        return await self._rvsecncl(
            "01", order_no, symbol, exchange, quantity, price
        )

    async def cancel(
        self, order_no: str, symbol: str, exchange: str, quantity: int
    ) -> OrderResult:
        """해외 주문 취소."""
        logger.info("[해외 취소] ord=%s %s.%s", order_no, exchange, symbol)
        return await self._rvsecncl(
            "02", order_no, symbol, exchange, quantity, Decimal("0")
        )

    async def _rvsecncl(
        self,
        rvse_cncl: str,
        order_no: str,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
    ) -> OrderResult:
        tr_id = TR_ID_OVERSEAS_RVSECNCL_MAP.get(self._env, "TTTT1004U")
        body = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORGN_ODNO": order_no,
            "RVSE_CNCL_DVSN_CD": rvse_cncl,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
        }
        response = await self._client.post(
            OVERSEAS_ORDER_RVSECNCL_PATH, body=body, tr_id=tr_id, use_hashkey=True
        )
        return self._parse(response)

    def _parse(self, response: dict[str, object]) -> OrderResult:
        rt_cd = str(response.get("rt_cd", ""))
        msg1 = str(response.get("msg1", ""))
        if rt_cd != "0":
            raise OrderError(f"해외 주문 실패 (rt_cd={rt_cd}): {msg1}", rt_cd=rt_cd, msg1=msg1)
        output = response.get("output", {})
        out = output if isinstance(output, dict) else {}
        return OrderResult(
            order_no=str(out.get("ODNO", "")),
            order_time=str(out.get("ORD_TMD", "")),
            message=msg1,
            raw_response=response,
        )
```

- [ ] **Step 4: Protocol 추가** — `src/api/protocols.py` 끝에:

```python
@runtime_checkable
class OverseasOrderProvider(Protocol):
    """해외 주문(매수/매도/정정/취소) 인터페이스 (단가 Decimal)."""

    async def buy(
        self, symbol: str, exchange: str, quantity: int, price: Decimal,
        order_type: str = "00",
    ) -> OrderResult:
        """해외 매수 주문."""
        ...

    async def sell(
        self, symbol: str, exchange: str, quantity: int, price: Decimal,
        order_type: str = "00",
    ) -> OrderResult:
        """해외 매도 주문."""
        ...

    async def modify(
        self, order_no: str, symbol: str, exchange: str, quantity: int, price: Decimal,
    ) -> OrderResult:
        """해외 주문 정정."""
        ...

    async def cancel(
        self, order_no: str, symbol: str, exchange: str, quantity: int,
    ) -> OrderResult:
        """해외 주문 취소."""
        ...
```

(`OrderResult`는 이미 protocols.py에 import되어 있음.)

- [ ] **Step 5: GREEN + 검증 + 커밋**

```
python -m pytest tests/test_api/test_overseas_order.py -q   # PASS
python -m mypy src/api/overseas_order.py src/api/protocols.py  # Success
ruff check src/api/overseas_order.py src/api/protocols.py tests/test_api/test_overseas_order.py  # passed
git add src/api/overseas_order.py src/api/protocols.py tests/test_api/test_overseas_order.py
git commit -m "feat(api): 해외 주문 OverseasOrderAPI — 매수/매도/정정/취소 (P2c)"
```

---

### Task 2: 회귀

- [ ] `python -m pytest tests/test_api/ tests/test_market/ -q` → PASS.
- [ ] `python -m mypy src/api/` → Success(또는 사전존재 무관).

---

## Self-Review

**1. Spec coverage:** §2.1 주문(매수/매도 order, 정정취소 rvsecncl) ✓. 미국 매수 지정가 제약(ORD_DVSN "00" 기본) ✓. 시장가 OVRS_ORD_UNPR="0" ✓.
**2. Placeholder:** 모든 step 실제 코드. 정정취소 TR_ID confidence=medium 명시.
**3. Type consistency:** 메서드 시그니처(`buy/sell(symbol, exchange, quantity, price: Decimal, order_type="00")`, `modify(order_no, symbol, exchange, quantity, price)`, `cancel(order_no, symbol, exchange, quantity)`)가 Protocol과 일치. `OrderResult` 재사용. TR_ID 맵 virtual/real.
**4. 순환 import:** protocols → overseas_order? protocols는 overseas_order를 import하지 않음(반환 OrderResult는 order.py에서 이미 import). overseas_order → order(OrderResult), client, config. ✓
