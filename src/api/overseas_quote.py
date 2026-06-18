"""해외(미국) 시세 조회 API 모듈.

국내 ``src/api/quote.py``와 응답 체계가 완전히 달라(엔드포인트 overseas-price,
파라미터 EXCD/SYMB, 응답 필드 last/clos 등) 별도 모듈로 둔다. 가격은 KIS가
문자열로 내려주므로 부동소수점 손실 없이 ``Decimal``로 파싱한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from src.api.client import KISClient
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# ── 엔드포인트 / TR_ID (spec §2.2, §2.3) ──
OVERSEAS_PRICE_PATH: str = "/uapi/overseas-price/v1/quotations/price"
OVERSEAS_DAILY_PATH: str = "/uapi/overseas-price/v1/quotations/dailyprice"
OVERSEAS_RANK_VOL_PATH: str = "/uapi/overseas-stock/v1/ranking/trade-vol"

TR_ID_OVERSEAS_PRICE: str = "HHDFS00000300"
TR_ID_OVERSEAS_DAILY: str = "HHDFS76240000"
TR_ID_OVERSEAS_RANK_VOL: str = "HHDFS76310010"

# 기간(period) → KIS GUBN 코드
_GUBN_MAP: dict[str, str] = {"D": "0", "W": "1", "M": "2"}


def _get(data: dict[str, Any], key: str, default: str = "") -> str:
    """대소문자 무관 조회. 해외 응답은 소문자 키(last/clos 등)지만 환경별 변동 대비."""
    return cast(str, data.get(key) or data.get(key.upper(), default))


def _decimal(value: str) -> Decimal:
    """문자열 가격을 Decimal로 파싱한다. 빈 값/파싱 불가 시 Decimal('0')."""
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return Decimal("0")


@dataclass
class OverseasCurrentPrice:
    """해외 현재가 정보 (가격은 Decimal)."""

    symbol: str
    exchange: str  # 시세 거래소코드(EXCD): NAS/NYS/AMS
    last: Decimal
    base: Decimal  # 전일종가
    change_rate: float  # rate (%)
    volume: int  # tvol
    high: Decimal
    low: Decimal
    open: Decimal
    raw_data: dict[str, Any]


@dataclass
class OverseasDailyPriceItem:
    """해외 일봉 한 건 (가격은 Decimal)."""

    date: str  # xymd
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal  # clos
    volume: int  # tvol


@dataclass
class OverseasRankItem:
    """해외 거래량순위 종목."""

    symbol: str
    exchange: str
    last: Decimal
    change_rate: float
    volume: int
    rank: int
    name: str = ""  # 종목명(ename 영문 우선, 없으면 심볼). 표시/로그/캘린더용.


class OverseasQuoteAPI:
    """KIS 해외주식 시세 조회 API. (EXCD/SYMB 기반, 가격 Decimal)"""

    def __init__(self, client: KISClient | None = None) -> None:
        self._client = client or KISClient()

    async def get_current_price(
        self, symbol: str, exchange: str
    ) -> OverseasCurrentPrice:
        """해외 종목 현재가를 조회한다.

        Args:
            symbol: 종목 심볼 (예: "AAPL")
            exchange: 시세 거래소코드 EXCD ("NAS"/"NYS"/"AMS")
        """
        logger.info("[해외 현재가] %s.%s", exchange, symbol)
        params = {"AUTH": "", "EXCD": exchange, "SYMB": symbol}
        response = await self._client.get(
            OVERSEAS_PRICE_PATH, params=params, tr_id=TR_ID_OVERSEAS_PRICE
        )
        output = response.get("output", {}) or {}
        return OverseasCurrentPrice(
            symbol=symbol,
            exchange=exchange,
            last=_decimal(_get(output, "last")),
            base=_decimal(_get(output, "base")),
            change_rate=float(_get(output, "rate", "0") or "0"),
            volume=int(_get(output, "tvol", "0") or "0"),
            high=_decimal(_get(output, "high")),
            low=_decimal(_get(output, "low")),
            open=_decimal(_get(output, "open")),
            raw_data=output,
        )

    async def get_daily_price(
        self,
        symbol: str,
        exchange: str,
        period: str = "D",
        lookback_days: int = 60,
    ) -> list[OverseasDailyPriceItem]:
        """해외 종목 일봉을 조회한다(최신→과거).

        Args:
            symbol: 종목 심볼
            exchange: 시세 거래소코드 EXCD
            period: "D"(일)/"W"(주)/"M"(월)
            lookback_days: 확보할 최대 건수(응답 상위 N건 절단)
        """
        logger.info("[해외 일봉] %s.%s period=%s", exchange, symbol, period)
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol,
            "GUBN": _GUBN_MAP.get(period, "0"),
            "BYMD": "",
            "MODP": "1",
        }
        response = await self._client.get(
            OVERSEAS_DAILY_PATH, params=params, tr_id=TR_ID_OVERSEAS_DAILY
        )
        output2 = response.get("output2", []) or []
        results: list[OverseasDailyPriceItem] = []
        for item in output2[:lookback_days]:
            item_date = _get(item, "xymd")
            if not item_date:
                continue
            results.append(
                OverseasDailyPriceItem(
                    date=item_date,
                    open=_decimal(_get(item, "open")),
                    high=_decimal(_get(item, "high")),
                    low=_decimal(_get(item, "low")),
                    close=_decimal(_get(item, "clos")),
                    volume=int(_get(item, "tvol", "0") or "0"),
                )
            )
        return results

    async def get_ranking(
        self, exchange: str, top_n: int = 20
    ) -> list[OverseasRankItem]:
        """거래소별 거래량순위를 조회한다(HHDFS76310010).

        Args:
            exchange: 시세 거래소코드 EXCD ("NAS"/"NYS"/"AMS")
            top_n: 상위 N개 절단
        """
        logger.info("[해외 거래량순위] EXCD=%s top=%d", exchange, top_n)
        # PRC1/PRC2(가격범위)·KEYB(연속조회키)는 빈값이어도 **필수**. 누락 시
        # OPSQ2001 "ERROR INPUT FIELD NOT FOUND [PRC1]"로 output 부재(빈 결과).
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "NDAY": "0",
            "PRC1": "",
            "PRC2": "",
            "VOL_RANG": "0",
            "KEYB": "",
        }
        response = await self._client.get(
            OVERSEAS_RANK_VOL_PATH, params=params, tr_id=TR_ID_OVERSEAS_RANK_VOL
        )
        output2 = response.get("output2", []) or []
        results: list[OverseasRankItem] = []
        for idx, item in enumerate(output2[:top_n], start=1):
            symbol = _get(item, "symb")
            if not symbol:
                continue
            results.append(
                OverseasRankItem(
                    symbol=symbol,
                    exchange=exchange,
                    last=_decimal(_get(item, "last")),
                    change_rate=float(_get(item, "rate", "0") or "0"),
                    volume=int(_get(item, "tvol", "0") or "0"),
                    rank=int(_get(item, "rank", "0") or str(idx)),
                    # 순위 응답이 영문명(ename)·한글명(name) 제공 → 종목명 보강.
                    name=_get(item, "ename") or _get(item, "name") or symbol,
                )
            )
        return results
