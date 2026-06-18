"""해외 잔고 API(OverseasAccountAPI) 테스트."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

from src.api.overseas_account import (
    OVERSEAS_BALANCE_PATH,
    OVERSEAS_PRESENT_BALANCE_PATH,
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
    async def test_parses_buyable_cash_fallback(self) -> None:
        # 통합 필드 부재 시 현금 필드(ord_psbl_qty/ord_psbl_frcr_amt) 폴백.
        c = AsyncMock()
        c.get.return_value = {
            "output": {"ord_psbl_frcr_amt": "5000.00", "ord_psbl_qty": "33"}
        }
        api = OverseasAccountAPI(client=c)
        result = await api.get_buyable_amount("AAPL", "NASD", Decimal("150.25"))
        assert result.orderable_cash == Decimal("5000.00")
        assert result.orderable_qty == 33

    async def test_prefers_integrated_margin_fields(self) -> None:
        # 통합증거금: ord_psbl_qty=0(현금)이어도 ovrs_max_ord_psbl_qty(통합) 우선.
        c = AsyncMock()
        c.get.return_value = {
            "output": {
                "ord_psbl_frcr_amt": "0.00", "ord_psbl_qty": "0",
                "ovrs_max_ord_psbl_qty": "124", "frcr_ord_psbl_amt1": "620.11",
            }
        }
        api = OverseasAccountAPI(client=c)
        result = await api.get_buyable_amount("SNAP", "NYSE", Decimal("5"))
        assert result.orderable_qty == 124  # 통합증거금 반영(현금 0 아님)
        assert result.orderable_cash == Decimal("620.11")


class TestGetPresentBalance:
    def _real_api(self, response: dict[str, object]) -> OverseasAccountAPI:
        c = AsyncMock()
        c.get.return_value = response
        api = OverseasAccountAPI(client=c)
        api._env = "real"  # CTRP6504R는 실전 전용
        return api

    async def test_parses_output3_real_fields(self) -> None:
        # 실측(2026-06-18): 데이터는 output3에. 매수여력(frcr_use_psbl_amt)·
        # 외화평가총액·총손익·수익률(evlu_erng_rt1). output2(환율)는 부재 변형.
        response = {
            "output3": {
                "frcr_use_psbl_amt": "1000.50",
                "tot_dncl_amt": "999.00",
                "frcr_evlu_tota": "2502.50",
                "tot_evlu_pfls_amt": "120.30",
                "evlu_erng_rt1": "5.04",
            },
        }
        pb = await self._real_api(response).get_present_balance("USD")
        assert pb.valid is True
        assert pb.deposit == Decimal("1000.50")  # 매수여력 우선
        assert pb.total_eval == Decimal("2502.50")
        assert pb.total_profit_loss == Decimal("120.30")
        assert pb.profit_rate == 5.04
        assert pb.currency == "USD"

    async def test_fx_from_output2_when_present(self) -> None:
        response = {
            "output2": [{"crcy_cd": "USD", "frst_bltn_exrt": "1385.20"}],
            "output3": {"frcr_use_psbl_amt": "500.00"},
        }
        pb = await self._real_api(response).get_present_balance("USD")
        assert pb.fx_rate == Decimal("1385.20")
        assert pb.deposit == Decimal("500.00")

    async def test_sends_present_balance_params(self) -> None:
        c = AsyncMock()
        c.get.return_value = {"output2": [], "output3": {}}
        api = OverseasAccountAPI(client=c)
        api._env = "real"
        await api.get_present_balance("USD")
        call = c.get.call_args
        assert call.args[0] == OVERSEAS_PRESENT_BALANCE_PATH
        params = call.kwargs.get("params")
        assert params["WCRC_FRCR_DVSN_CD"] == "02"
        assert params["NATN_CD"] == "840"

    async def test_virtual_env_returns_invalid_without_call(self) -> None:
        # 모의투자는 present-balance 미지원 → 호출 없이 무효 반환(폴백 유도).
        c = AsyncMock()
        api = OverseasAccountAPI(client=c)
        api._env = "virtual"
        pb = await api.get_present_balance("USD")
        assert pb.valid is False
        c.get.assert_not_called()

    async def test_zero_values_marked_invalid(self) -> None:
        response = {
            "output2": [{"crcy_cd": "USD", "frcr_dncl_amt_2": "0"}],
            "output3": {"frcr_evlu_tota": "0", "tot_evlu_pfls_amt": "0"},
        }
        pb = await self._real_api(response).get_present_balance("USD")
        assert pb.valid is False

    async def test_falls_back_to_alternate_field_names(self) -> None:
        # 후보키 폴백: frcr_dncl_amt_2 부재 시 frcr_dncl_amt1 사용.
        response = {
            "output2": [{"crcy_cd": "USD", "frcr_dncl_amt1": "777.00"}],
            "output3": {"evlu_amt_smtl_amt": "800.00"},
        }
        pb = await self._real_api(response).get_present_balance("USD")
        assert pb.deposit == Decimal("777.00")
        assert pb.total_eval == Decimal("800.00")
        assert pb.valid is True
