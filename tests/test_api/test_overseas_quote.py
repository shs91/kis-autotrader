"""해외 시세 API(OverseasQuoteAPI) 테스트."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

from src.api.overseas_quote import (
    OVERSEAS_DAILY_PATH,
    OVERSEAS_PRICE_PATH,
    OVERSEAS_RANK_VOL_PATH,
    TR_ID_OVERSEAS_DAILY,
    TR_ID_OVERSEAS_PRICE,
    TR_ID_OVERSEAS_RANK_VOL,
    OverseasCurrentPrice,
    OverseasDailyPriceItem,
    OverseasQuoteAPI,
    OverseasRankItem,
    _decimal,
)
from src.api.protocols import OverseasQuoteProvider


class TestDecimalHelper:
    def test_parses_decimal_string(self) -> None:
        assert _decimal("150.25") == Decimal("150.25")

    def test_empty_string_is_zero(self) -> None:
        assert _decimal("") == Decimal("0")

    def test_invalid_is_zero(self) -> None:
        assert _decimal("N/A") == Decimal("0")

    def test_preserves_precision(self) -> None:
        # float 손실 없이 문자열 그대로 보존
        assert _decimal("0.0001") == Decimal("0.0001")


def test_overseas_quote_api_satisfies_protocol() -> None:
    assert issubclass(OverseasQuoteAPI, OverseasQuoteProvider)


def test_dataclass_shapes() -> None:
    cp = OverseasCurrentPrice(
        symbol="AAPL",
        exchange="NAS",
        last=Decimal("150.25"),
        base=Decimal("149.00"),
        change_rate=0.84,
        volume=1000,
        high=Decimal("151.0"),
        low=Decimal("148.5"),
        open=Decimal("149.5"),
        raw_data={},
    )
    assert cp.last == Decimal("150.25")
    dp = OverseasDailyPriceItem(
        date="20260615",
        open=Decimal("149.5"),
        high=Decimal("151.0"),
        low=Decimal("148.5"),
        close=Decimal("150.25"),
        volume=1000,
    )
    assert dp.close == Decimal("150.25")
    ri = OverseasRankItem(
        symbol="AAPL",
        exchange="NAS",
        last=Decimal("150.25"),
        change_rate=0.84,
        volume=1000,
        rank=1,
    )
    assert ri.rank == 1


class TestOverseasCurrentPrice:
    def _make_api(self, response: dict[str, object]) -> OverseasQuoteAPI:
        mock_client = AsyncMock()
        mock_client.get.return_value = response
        return OverseasQuoteAPI(client=mock_client)

    async def test_get_current_price_parses_decimal(self) -> None:
        response = {
            "output": {
                "rsym": "DNASAAPL",
                "zdiv": "2",
                "base": "149.00",
                "last": "150.25",
                "open": "149.50",
                "high": "151.00",
                "low": "148.50",
                "tvol": "50000000",
                "rate": "0.84",
            }
        }
        api = self._make_api(response)
        result = await api.get_current_price("AAPL", "NAS")

        assert result.symbol == "AAPL"
        assert result.exchange == "NAS"
        assert result.last == Decimal("150.25")
        assert result.base == Decimal("149.00")
        assert result.open == Decimal("149.50")
        assert result.high == Decimal("151.00")
        assert result.low == Decimal("148.50")
        assert result.volume == 50000000
        assert result.change_rate == 0.84

    async def test_get_current_price_sends_excd_symb(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output": {}}
        api = OverseasQuoteAPI(client=mock_client)
        await api.get_current_price("AAPL", "NAS")

        call = mock_client.get.call_args
        assert call.args[0] == OVERSEAS_PRICE_PATH
        assert call.kwargs.get("tr_id") == TR_ID_OVERSEAS_PRICE
        params = call.kwargs.get("params")
        assert params["EXCD"] == "NAS"
        assert params["SYMB"] == "AAPL"
        assert "AUTH" in params


class TestOverseasDailyPrice:
    def _make_api(self, response: dict[str, object]) -> OverseasQuoteAPI:
        mock_client = AsyncMock()
        mock_client.get.return_value = response
        return OverseasQuoteAPI(client=mock_client)

    async def test_get_daily_price_parses_output2(self) -> None:
        response = {
            "output1": {"rsym": "DNASAAPL"},
            "output2": [
                {
                    "xymd": "20260615",
                    "open": "149.50",
                    "high": "151.00",
                    "low": "148.50",
                    "clos": "150.25",
                    "tvol": "50000000",
                },
                {
                    "xymd": "20260612",
                    "open": "148.00",
                    "high": "149.80",
                    "low": "147.50",
                    "clos": "149.00",
                    "tvol": "42000000",
                },
            ],
        }
        api = self._make_api(response)
        result = await api.get_daily_price("AAPL", "NAS")

        assert len(result) == 2
        assert result[0].date == "20260615"
        assert result[0].close == Decimal("150.25")
        assert result[0].volume == 50000000
        assert result[1].date == "20260612"

    async def test_get_daily_price_sends_gubn_for_period(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": []}
        api = OverseasQuoteAPI(client=mock_client)
        await api.get_daily_price("AAPL", "NAS", period="W")

        call = mock_client.get.call_args
        assert call.args[0] == OVERSEAS_DAILY_PATH
        assert call.kwargs.get("tr_id") == TR_ID_OVERSEAS_DAILY
        params = call.kwargs.get("params")
        assert params["GUBN"] == "1"  # W → 1
        assert params["EXCD"] == "NAS"
        assert params["SYMB"] == "AAPL"


class TestOverseasRanking:
    def _make_api(self, response: dict[str, object]) -> OverseasQuoteAPI:
        mock_client = AsyncMock()
        mock_client.get.return_value = response
        return OverseasQuoteAPI(client=mock_client)

    async def test_get_ranking_parses_output2(self) -> None:
        response = {
            "output2": [
                {"symb": "TSLA", "ename": "TESLA INC", "last": "250.10",
                 "rate": "3.2", "tvol": "90000000", "rank": "1"},
                {"symb": "AAPL", "last": "150.25", "rate": "0.84",
                 "tvol": "50000000", "rank": "2"},
            ]
        }
        api = self._make_api(response)
        result = await api.get_ranking("NAS", top_n=10)

        assert len(result) == 2
        assert result[0].symbol == "TSLA"
        assert result[0].last == Decimal("250.10")
        assert result[0].rank == 1
        assert result[0].name == "TESLA INC"  # ename 보강
        assert result[1].symbol == "AAPL"
        assert result[1].name == "AAPL"  # ename 부재 시 심볼 폴백

    async def test_get_ranking_sends_required_params(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": []}
        api = OverseasQuoteAPI(client=mock_client)
        await api.get_ranking("NYS")

        call = mock_client.get.call_args
        assert call.args[0] == OVERSEAS_RANK_VOL_PATH
        assert call.kwargs.get("tr_id") == TR_ID_OVERSEAS_RANK_VOL
        params = call.kwargs.get("params")
        assert params["EXCD"] == "NYS"
        # 필수 파라미터 — 누락 시 OPSQ2001(빈 결과)되던 회귀 가드
        for required in ("PRC1", "PRC2", "VOL_RANG", "KEYB"):
            assert required in params, f"필수 순위 파라미터 누락: {required}"

    async def test_get_ranking_empty_on_missing_output2(self) -> None:
        api = self._make_api({})
        result = await api.get_ranking("NAS")
        assert result == []
