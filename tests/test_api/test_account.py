"""AccountAPI 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock

from src.api.account import AccountAPI, Buyable


class TestGetBuyable:
    """매수가능조회(TTTC8908R) 파싱·파라미터."""

    def _api(self, response: dict) -> AccountAPI:  # type: ignore[type-arg]
        client = AsyncMock()
        client.get.return_value = response
        return AccountAPI(client=client)

    async def test_parses_nrcvb_and_cash(self) -> None:
        api = self._api(
            {
                "output": {
                    "ord_psbl_cash": "278800",
                    "nrcvb_buy_amt": "278000",
                    "nrcvb_buy_qty": "4",
                    "max_buy_qty": "10",
                }
            }
        )
        b = await api.get_buyable("204320", 69900)
        assert isinstance(b, Buyable)
        assert b.ord_psbl_cash == 278800
        assert b.nrcvb_buy_amt == 278000
        assert b.nrcvb_buy_qty == 4  # 미수 없는(현금만) 매수수량 — 사이징 캡 기준
        assert b.max_buy_qty == 10

    async def test_passes_psbl_order_params(self) -> None:
        client = AsyncMock()
        client.get.return_value = {"output": {}}
        api = AccountAPI(client=client)
        await api.get_buyable("005930", 70000)
        call = client.get.call_args
        params = call.kwargs.get("params") or call[1].get("params")
        assert params["PDNO"] == "005930"
        assert params["ORD_UNPR"] == "70000"
        assert params["ORD_DVSN"] == "01"  # 매수 주문과 동일 시장가
        assert params["CMA_EVLU_AMT_ICLD_YN"] == "N"

    async def test_empty_output_yields_zero(self) -> None:
        api = self._api({"output": {}})
        b = await api.get_buyable("005930", 70000)
        assert b.nrcvb_buy_qty == 0
        assert b.ord_psbl_cash == 0
