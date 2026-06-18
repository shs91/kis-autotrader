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
        c.post.return_value = {
            "rt_cd": "0",
            "msg1": "OK",
            "output": {"ODNO": "123", "ORD_TMD": "093000"},
        }
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
        body = c.post.call_args.kwargs.get("body")
        assert body["OVRS_ORD_UNPR"] == "0"

    async def test_rejects_on_error_rt_cd(self) -> None:
        api = self._api({"rt_cd": "1", "msg1": "잔고부족"})
        with pytest.raises(OrderError):
            await api.buy("AAPL", "NASD", 10, Decimal("150.25"))

    async def test_order_is_non_idempotent(self) -> None:
        """해외 매수/매도는 idempotent=False로 전달돼 재시도 중복주문을 막는다."""
        c = AsyncMock()
        c.post.return_value = {"rt_cd": "0", "output": {"ODNO": "1"}}
        api = OverseasOrderAPI(client=c)
        await api.buy("AAPL", "NASD", 1, Decimal("150.25"))
        assert c.post.call_args.kwargs.get("idempotent") is False
        await api.sell("AAPL", "NASD", 1, Decimal("150.25"))
        assert c.post.call_args.kwargs.get("idempotent") is False

    async def test_cancel_sends_rvsecncl(self) -> None:
        c = AsyncMock()
        c.post.return_value = {"rt_cd": "0", "output": {"ODNO": "1"}}
        api = OverseasOrderAPI(client=c)
        await api.cancel("ORG1", "AAPL", "NASD", 10)
        body = c.post.call_args.kwargs.get("body")
        assert body["ORGN_ODNO"] == "ORG1"
        assert body["RVSE_CNCL_DVSN_CD"] == "02"
