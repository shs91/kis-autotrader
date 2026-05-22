"""시세 조회 API 모듈."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast

from src.api.client import KISClient
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 시세 조회 엔드포인트
CURRENT_PRICE_PATH: str = "/uapi/domestic-stock/v1/quotations/inquire-price"
# 일봉 조회는 `inquire-daily-itemchartprice` 엔드포인트를 사용한다.
# 기존 `inquire-daily-price`는 응답이 항상 최근 30거래일로 고정되어
# 60일 페이지네이션이 의도대로 동작하지 않는 한계가 있어 교체했다.
# (참고: 제안서 docs/proposals/2026-05-16_daily-quote-endpoint-switch-itemchartprice.md)
DAILY_PRICE_PATH: str = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
MINUTE_PRICE_PATH: str = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
VOLUME_RANK_PATH: str = "/uapi/domestic-stock/v1/quotations/volume-rank"

# tr_id
TR_ID_CURRENT_PRICE: str = "FHKST01010100"
# 일/주/월/년 기간별 시세 조회 TR_ID (실전·모의 공통)
TR_ID_DAILY_PRICE: str = "FHKST03010100"
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
    return cast(str, data.get(key) or data.get(key.lower(), default))


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
        lookback_days: int = 60,
    ) -> list[DailyPriceItem]:
        """종목의 일봉 데이터를 조회한다.

        `inquire-daily-itemchartprice` 엔드포인트는 1회 호출로 최대 100건의
        일봉 데이터를 반환하므로 통상 페이지네이션이 불필요하다. 다만
        영업일 외 휴장 영향 등으로 1회 응답이 ``lookback_days`` 미달인
        경우에 한해 더 이른 날짜 범위를 한 번만 더 조회하는 fallback을
        둔다(최대 2회 호출).

        응답 구조는 ``output1``(헤더)·``output2``(일봉 리스트)이며 본
        메서드는 ``output2``만 사용한다. 응답 필드명(``STCK_BSOP_DATE``,
        ``STCK_OPRC/HGPR/LWPR/CLPR``, ``ACML_VOL``)은 기존 엔드포인트와
        호환된다.

        Args:
            stock_code: 종목코드 (6자리)
            period: 기간 구분 ("D": 일, "W": 주, "M": 월, "Y": 년)
            adjusted: 수정주가 반영 여부
            lookback_days: 확보할 거래일 수 (기본 60)

        Returns:
            일봉 데이터 목록 (최신→과거 순)
        """
        logger.info(
            "[일봉 조회] 종목=%s, 기간=%s, lookback=%d",
            stock_code, period, lookback_days,
        )

        all_results: list[DailyPriceItem] = []
        seen_dates: set[str] = set()
        page_end = date.today()
        # 1차 호출에서 lookback_days * 2 만큼의 캘린더 범위를 요청하면
        # 통상 응답이 lookback_days 거래일을 충분히 포함한다.
        first_window_days = max(lookback_days * 2, 60)
        max_calls = 2

        for call_idx in range(max_calls):
            window_days = first_window_days if call_idx == 0 else first_window_days
            page_start = page_end - timedelta(days=window_days)

            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
                "FID_INPUT_DATE_1": page_start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": page_end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": period,
                "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
            }

            response = await self._client.get(
                DAILY_PRICE_PATH, params=params, tr_id=TR_ID_DAILY_PRICE
            )

            # `inquire-daily-itemchartprice`는 output2에 일봉 리스트가 들어온다.
            # 일부 환경/응답 형태 호환을 위해 output도 보조로 확인한다.
            output_list = response.get("output2") or response.get("output") or []
            if not output_list:
                break

            oldest_date_str: str | None = None
            for item in output_list:
                dt = _get(item, "STCK_BSOP_DATE")
                if not dt or dt in seen_dates:
                    continue
                seen_dates.add(dt)
                all_results.append(
                    DailyPriceItem(
                        date=dt,
                        open_price=int(_get(item, "STCK_OPRC", "0")),
                        high_price=int(_get(item, "STCK_HGPR", "0")),
                        low_price=int(_get(item, "STCK_LWPR", "0")),
                        close_price=int(_get(item, "STCK_CLPR", "0")),
                        volume=int(_get(item, "ACML_VOL", "0")),
                    )
                )
                oldest_date_str = dt

            if len(all_results) >= lookback_days:
                break

            # fallback 1회: 첫 호출이 lookback 미달인 경우 더 이른 날짜로 1회만 추가 조회
            if oldest_date_str is None:
                break

            page_end = datetime.strptime(oldest_date_str, "%Y%m%d").date() - timedelta(days=1)

            if call_idx + 1 < max_calls:
                await asyncio.sleep(0.05)

        logger.info("[일봉 조회 완료] 종목=%s, %d건 확보", stock_code, len(all_results))
        return all_results

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
