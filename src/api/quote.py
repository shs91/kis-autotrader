"""시세 조회 API 모듈."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.api.client import KISClient
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 시세 조회 엔드포인트
CURRENT_PRICE_PATH: str = "/uapi/domestic-stock/v1/quotations/inquire-price"
DAILY_PRICE_PATH: str = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
MINUTE_PRICE_PATH: str = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
VOLUME_RANK_PATH: str = "/uapi/domestic-stock/v1/quotations/volume-rank"

# tr_id
TR_ID_CURRENT_PRICE: str = "FHKST01010100"
TR_ID_DAILY_PRICE: str = "FHKST01010400"
TR_ID_MINUTE_PRICE: str = "FHKST03010200"
TR_ID_VOLUME_RANK: str = "FHPST01710000"


def _get(data: dict[str, Any], key: str, default: str = "") -> str:
    """대소문자를 구분하지 않고 딕셔너리에서 값을 가져온다.

    KIS API는 실전/모의투자 환경에 따라 응답 필드명이
    대문자 또는 소문자로 달라질 수 있다.

    Args:
        data: 응답 딕셔너리
        key: 대문자 키 (예: "STCK_PRPR")
        default: 기본값

    Returns:
        찾은 값 또는 기본값
    """
    return data.get(key) or data.get(key.lower(), default)


@dataclass
class CurrentPrice:
    """현재가 정보."""

    stock_code: str
    stock_name: str
    current_price: int
    change_price: int
    change_rate: float
    volume: int
    high_price: int
    low_price: int
    open_price: int
    raw_data: dict[str, Any]


@dataclass
class DailyPriceItem:
    """일봉 데이터 한 건."""

    date: str
    open_price: int
    high_price: int
    low_price: int
    close_price: int
    volume: int


@dataclass
class MinutePriceItem:
    """분봉 데이터 한 건."""

    time: str
    open_price: int
    high_price: int
    low_price: int
    close_price: int
    volume: int


@dataclass
class VolumeRankItem:
    """거래량 순위 종목."""

    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    volume: int
    market_cap: int


class QuoteAPI:
    """KIS 시세 조회 API를 호출한다."""

    def __init__(self, client: KISClient | None = None) -> None:
        """QuoteAPI를 초기화한다.

        Args:
            client: KISClient 인스턴스 (기본값: 새로 생성)
        """
        self._client = client or KISClient()

    async def get_current_price(self, stock_code: str) -> CurrentPrice:
        """종목의 현재가를 조회한다.

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            현재가 정보
        """
        logger.info("[현재가 조회] 종목=%s", stock_code)

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        }

        response = await self._client.get(
            CURRENT_PRICE_PATH, params=params, tr_id=TR_ID_CURRENT_PRICE
        )

        output = response.get("output", {})

        return CurrentPrice(
            stock_code=stock_code,
            stock_name=_get(output, "HTS_KOR_ISNM"),
            current_price=int(_get(output, "STCK_PRPR", "0")),
            change_price=int(_get(output, "PRDY_VRSS", "0")),
            change_rate=float(_get(output, "PRDY_CTRT", "0")),
            volume=int(_get(output, "ACML_VOL", "0")),
            high_price=int(_get(output, "STCK_HGPR", "0")),
            low_price=int(_get(output, "STCK_LWPR", "0")),
            open_price=int(_get(output, "STCK_OPRC", "0")),
            raw_data=output,
        )

    async def get_daily_price(
        self,
        stock_code: str,
        period: str = "D",
        adjusted: bool = True,
    ) -> list[DailyPriceItem]:
        """종목의 일봉 데이터를 조회한다.

        Args:
            stock_code: 종목코드 (6자리)
            period: 기간 구분 ("D": 일, "W": 주, "M": 월)
            adjusted: 수정주가 반영 여부

        Returns:
            일봉 데이터 목록
        """
        logger.info("[일봉 조회] 종목=%s, 기간=%s", stock_code, period)

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_PERIOD_DIV_CODE": period,
            "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
        }

        response = await self._client.get(
            DAILY_PRICE_PATH, params=params, tr_id=TR_ID_DAILY_PRICE
        )

        output_list = response.get("output", [])
        results: list[DailyPriceItem] = []

        for item in output_list:
            results.append(
                DailyPriceItem(
                    date=_get(item, "STCK_BSOP_DATE"),
                    open_price=int(_get(item, "STCK_OPRC", "0")),
                    high_price=int(_get(item, "STCK_HGPR", "0")),
                    low_price=int(_get(item, "STCK_LWPR", "0")),
                    close_price=int(_get(item, "STCK_CLPR", "0")),
                    volume=int(_get(item, "ACML_VOL", "0")),
                )
            )

        return results

    async def get_minute_price(
        self,
        stock_code: str,
        time_unit: str = "1",
    ) -> list[MinutePriceItem]:
        """종목의 분봉 데이터를 조회한다.

        Args:
            stock_code: 종목코드 (6자리)
            time_unit: 분봉 단위 ("1", "3", "5", "10", "15", "30", "60")

        Returns:
            분봉 데이터 목록
        """
        logger.info("[분봉 조회] 종목=%s, 단위=%s분", stock_code, time_unit)

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_ETC_CLS_CODE": "",
            "FID_INPUT_HOUR_1": time_unit,
            "FID_PW_DATA_INCU_YN": "Y",
        }

        response = await self._client.get(
            MINUTE_PRICE_PATH, params=params, tr_id=TR_ID_MINUTE_PRICE
        )

        output_list = response.get("output2", [])
        results: list[MinutePriceItem] = []

        for item in output_list:
            results.append(
                MinutePriceItem(
                    time=_get(item, "STCK_CNTG_HOUR"),
                    open_price=int(_get(item, "STCK_OPRC", "0")),
                    high_price=int(_get(item, "STCK_HGPR", "0")),
                    low_price=int(_get(item, "STCK_LWPR", "0")),
                    close_price=int(_get(item, "STCK_PRPR", "0")),
                    volume=int(_get(item, "CNTG_VOL", "0")),
                )
            )

        return results

    async def get_volume_rank(
        self,
        market: str = "J",
        top_n: int = 20,
    ) -> list[VolumeRankItem]:
        """거래량 상위 종목을 조회한다.

        Args:
            market: 시장 구분 ("J": 전체, "0": KOSPI, "1": KOSDAQ)
            top_n: 조회할 상위 종목 수

        Returns:
            거래량 상위 종목 목록
        """
        logger.info("[거래량 순위 조회] 시장=%s, 상위 %d종목", market, top_n)

        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": "",
        }

        response = await self._client.get(
            VOLUME_RANK_PATH, params=params, tr_id=TR_ID_VOLUME_RANK
        )

        output_list = response.get("output", [])
        results: list[VolumeRankItem] = []

        for item in output_list[:top_n]:
            code = _get(item, "MKSC_SHRN_ISCD")
            if not code:
                continue
            results.append(
                VolumeRankItem(
                    stock_code=code,
                    stock_name=_get(item, "HTS_KOR_ISNM"),
                    current_price=int(_get(item, "STCK_PRPR", "0")),
                    change_rate=float(_get(item, "PRDY_CTRT", "0")),
                    volume=int(_get(item, "ACML_VOL", "0")),
                    market_cap=int(_get(item, "LSTN_STCN", "0")),
                )
            )

        logger.info("거래량 상위 %d종목 조회 완료", len(results))
        return results
