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
        symbol="AAPL",
        exchange="NASD",
        quantity=10,
        avg_price=Decimal("149.00"),
        current_price=Decimal("150.25"),
        eval_amount=Decimal("1502.50"),
        profit_loss=Decimal("12.50"),
        profit_rate=0.84,
        currency="USD",
    )
    assert h.eval_amount == Decimal("1502.50")
    b = OverseasBalance(holdings=[h], currency="USD", raw_response={})
    assert b.holdings[0].symbol == "AAPL"
    buy = OverseasBuyable(orderable_cash=Decimal("5000"), orderable_qty=33, raw={})
    assert buy.orderable_qty == 33


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


class TestGetBuyableAmount:
    async def test_parses_buyable(self) -> None:
        c = AsyncMock()
        c.get.return_value = {
            "output": {"ord_psbl_frcr_amt": "5000.00", "ord_psbl_qty": "33"}
        }
        api = OverseasAccountAPI(client=c)
        result = await api.get_buyable_amount("AAPL", "NASD", Decimal("150.25"))
        assert result.orderable_cash == Decimal("5000.00")
        assert result.orderable_qty == 33
