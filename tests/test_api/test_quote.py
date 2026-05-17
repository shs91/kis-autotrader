"""시세 조회 API 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock

from src.api.quote import DAILY_PRICE_PATH, TR_ID_DAILY_PRICE, QuoteAPI


class TestQuoteAPI:
    """QuoteAPI 테스트."""

    def _make_quote_api(self, mock_response: dict) -> QuoteAPI:  # type: ignore[type-arg]
        """테스트용 QuoteAPI를 생성한다."""
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        return QuoteAPI(client=mock_client)

    async def test_get_current_price(self) -> None:
        """현재가 조회가 정상적으로 동작한다."""
        response = {
            "output": {
                "HTS_KOR_ISNM": "삼성전자",
                "STCK_PRPR": "72000",
                "PRDY_VRSS": "1000",
                "PRDY_CTRT": "1.41",
                "ACML_VOL": "15000000",
                "STCK_HGPR": "73000",
                "STCK_LWPR": "71000",
                "STCK_OPRC": "71500",
            }
        }

        api = self._make_quote_api(response)
        result = await api.get_current_price("005930")

        assert result.stock_code == "005930"
        assert result.stock_name == "삼성전자"
        assert result.current_price == 72000
        assert result.change_price == 1000
        assert result.change_rate == 1.41
        assert result.volume == 15000000
        assert result.high_price == 73000
        assert result.low_price == 71000
        assert result.open_price == 71500

    async def test_get_daily_price(self) -> None:
        """일봉 데이터 조회가 정상적으로 동작한다 (output2 응답)."""
        response = {
            "output1": {"hts_kor_isnm": "삼성전자"},
            "output2": [
                {
                    "STCK_BSOP_DATE": "20260331",
                    "STCK_OPRC": "71000",
                    "STCK_HGPR": "73000",
                    "STCK_LWPR": "70500",
                    "STCK_CLPR": "72000",
                    "ACML_VOL": "15000000",
                },
                {
                    "STCK_BSOP_DATE": "20260330",
                    "STCK_OPRC": "70000",
                    "STCK_HGPR": "71500",
                    "STCK_LWPR": "69500",
                    "STCK_CLPR": "71000",
                    "ACML_VOL": "12000000",
                },
            ],
        }

        api = self._make_quote_api(response)
        result = await api.get_daily_price("005930")

        assert len(result) == 2
        assert result[0].date == "20260331"
        assert result[0].close_price == 72000
        assert result[0].volume == 15000000
        assert result[1].date == "20260330"

    async def test_get_daily_price_uses_itemchartprice_endpoint(self) -> None:
        """`inquire-daily-itemchartprice` 엔드포인트와 TR_ID로 호출된다."""
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": []}

        api = QuoteAPI(client=mock_client)
        await api.get_daily_price("005930")

        call_args = mock_client.get.call_args
        # 첫 인자가 path
        assert call_args.args[0] == DAILY_PRICE_PATH
        assert DAILY_PRICE_PATH.endswith("inquire-daily-itemchartprice")
        assert call_args.kwargs.get("tr_id") == TR_ID_DAILY_PRICE
        assert TR_ID_DAILY_PRICE == "FHKST03010100"

    async def test_get_daily_price_passes_date_range_params(self) -> None:
        """일봉 조회 시 날짜 범위 파라미터가 전달된다."""
        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": []}

        api = QuoteAPI(client=mock_client)
        await api.get_daily_price("005930")

        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert "FID_INPUT_DATE_1" in params
        assert "FID_INPUT_DATE_2" in params
        assert len(params["FID_INPUT_DATE_1"]) == 8
        assert len(params["FID_INPUT_DATE_2"]) == 8
        assert params["FID_PERIOD_DIV_CODE"] == "D"

    async def test_get_minute_price(self) -> None:
        """분봉 데이터 조회가 정상적으로 동작한다."""
        response = {
            "output2": [
                {
                    "STCK_CNTG_HOUR": "130000",
                    "STCK_OPRC": "71500",
                    "STCK_HGPR": "72000",
                    "STCK_LWPR": "71000",
                    "STCK_PRPR": "71800",
                    "CNTG_VOL": "50000",
                },
            ]
        }

        api = self._make_quote_api(response)
        result = await api.get_minute_price("005930", time_unit="5")

        assert len(result) == 1
        assert result[0].time == "130000"
        assert result[0].close_price == 71800
        assert result[0].volume == 50000

    async def test_get_daily_price_empty(self) -> None:
        """일봉 데이터가 없으면 빈 목록을 반환한다."""
        response = {"output2": []}

        api = self._make_quote_api(response)
        result = await api.get_daily_price("005930")

        assert result == []

    async def test_get_daily_price_single_call_returns_60_items(self) -> None:
        """1회 호출로 60건 일봉을 반환받아 정상 파싱한다."""
        page = [
            {
                "STCK_BSOP_DATE": f"202605{60 - i:02d}",
                "STCK_OPRC": "70000",
                "STCK_HGPR": "72000",
                "STCK_LWPR": "69000",
                "STCK_CLPR": "71000",
                "ACML_VOL": "1000000",
            }
            for i in range(60)
        ]

        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": page}

        api = QuoteAPI(client=mock_client)
        result = await api.get_daily_price("005930", lookback_days=60)

        assert len(result) == 60
        # 단일 호출로 lookback_days 충족 시 추가 호출 없음
        assert mock_client.get.call_count == 1
        assert result[0].close_price == 71000

    async def test_get_daily_price_handles_100_items(self) -> None:
        """`output2`에 100건 응답이 도착해도 모두 무결하게 파싱된다."""
        page = [
            {
                "STCK_BSOP_DATE": f"2026{(5 - (i // 30)):02d}{30 - (i % 30):02d}",
                "STCK_OPRC": "70000",
                "STCK_HGPR": "72000",
                "STCK_LWPR": "69000",
                "STCK_CLPR": "71000",
                "ACML_VOL": "1000000",
            }
            for i in range(100)
        ]
        # 위 생성 로직은 중복 날짜를 만들 수 있으므로 명시적으로 100건 unique date를 만든다.
        page = []
        for i in range(100):
            month = 5 - (i // 28)
            day = 28 - (i % 28)
            page.append(
                {
                    "STCK_BSOP_DATE": f"2026{month:02d}{day:02d}",
                    "STCK_OPRC": "70000",
                    "STCK_HGPR": "72000",
                    "STCK_LWPR": "69000",
                    "STCK_CLPR": "71000",
                    "ACML_VOL": "1000000",
                }
            )

        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": page}

        api = QuoteAPI(client=mock_client)
        result = await api.get_daily_price("005930", lookback_days=60)

        # 60건 도달 시점에서 루프가 종료되지만, 1회 호출 결과 100건은
        # 한 번에 모두 파싱되어 결과 길이는 최소 60 이상이다.
        assert len(result) >= 60
        assert all(item.close_price == 71000 for item in result)

    async def test_get_daily_price_fallback_second_call(self) -> None:
        """1차 호출이 lookback 미달이면 더 이른 날짜로 1회만 추가 조회한다."""
        page1 = [
            {
                "STCK_BSOP_DATE": f"202605{30 - i:02d}",
                "STCK_OPRC": "70000",
                "STCK_HGPR": "72000",
                "STCK_LWPR": "69000",
                "STCK_CLPR": "71000",
                "ACML_VOL": "1000000",
            }
            for i in range(30)
        ]
        page2 = [
            {
                "STCK_BSOP_DATE": f"202604{30 - i:02d}",
                "STCK_OPRC": "68000",
                "STCK_HGPR": "70000",
                "STCK_LWPR": "67000",
                "STCK_CLPR": "69000",
                "ACML_VOL": "900000",
            }
            for i in range(30)
        ]

        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            {"output2": page1},
            {"output2": page2},
        ]

        api = QuoteAPI(client=mock_client)
        result = await api.get_daily_price("005930", lookback_days=60)

        assert len(result) == 60
        # 최대 2회 호출 (1차 + fallback 1회)
        assert mock_client.get.call_count == 2
        assert result[0].date == "20260530"
        assert result[-1].date == "20260401"

    async def test_get_daily_price_single_page_when_enough(self) -> None:
        """lookback_days=30 이하이면 단일 페이지로 충분하다."""
        page = [
            {
                "STCK_BSOP_DATE": f"202605{30 - i:02d}",
                "STCK_OPRC": "70000",
                "STCK_HGPR": "72000",
                "STCK_LWPR": "69000",
                "STCK_CLPR": "71000",
                "ACML_VOL": "1000000",
            }
            for i in range(30)
        ]

        mock_client = AsyncMock()
        mock_client.get.return_value = {"output2": page}

        api = QuoteAPI(client=mock_client)
        result = await api.get_daily_price("005930", lookback_days=30)

        assert len(result) == 30
        assert mock_client.get.call_count == 1

    async def test_get_current_price_passes_params(self) -> None:
        """현재가 조회 시 올바른 파라미터가 전달된다."""
        mock_client = AsyncMock()
        mock_client.get.return_value = {
            "output": {
                "HTS_KOR_ISNM": "테스트",
                "STCK_PRPR": "10000",
                "PRDY_VRSS": "0",
                "PRDY_CTRT": "0",
                "ACML_VOL": "0",
                "STCK_HGPR": "0",
                "STCK_LWPR": "0",
                "STCK_OPRC": "0",
            }
        }

        api = QuoteAPI(client=mock_client)
        await api.get_current_price("005930")

        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["FID_INPUT_ISCD"] == "005930"
        assert params["FID_COND_MRKT_DIV_CODE"] == "J"
