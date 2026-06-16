"""해외(미국) 잔고/매수가능금액 조회 API 모듈.

응답 금액은 Decimal, 통화는 명시 필드. _get/_decimal은 overseas_quote에서 재사용.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.api.client import KISClient
from src.api.overseas_quote import _decimal, _get
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

OVERSEAS_BALANCE_PATH: str = "/uapi/overseas-stock/v1/trading/inquire-balance"
OVERSEAS_PSAMOUNT_PATH: str = "/uapi/overseas-stock/v1/trading/inquire-psamount"

TR_ID_OVERSEAS_BALANCE_MAP: dict[str, str] = {"virtual": "VTTS3012R", "real": "TTTS3012R"}
TR_ID_OVERSEAS_PSAMOUNT_MAP: dict[str, str] = {"virtual": "VTTS3007R", "real": "TTTS3007R"}


@dataclass
class OverseasHolding:
    """해외 보유종목 (외화 기준)."""

    symbol: str
    exchange: str
    quantity: int
    avg_price: Decimal
    current_price: Decimal
    eval_amount: Decimal
    profit_loss: Decimal
    profit_rate: float
    currency: str


@dataclass
class OverseasBalance:
    """해외 잔고."""

    holdings: list[OverseasHolding]
    currency: str
    raw_response: dict[str, Any]


@dataclass
class OverseasBuyable:
    """해외 매수가능 정보."""

    orderable_cash: Decimal  # 외화 주문가능금액
    orderable_qty: int  # 주문가능수량
    raw: dict[str, Any]


class OverseasAccountAPI:
    """KIS 해외주식 잔고/매수가능금액 조회 API."""

    def __init__(self, client: KISClient | None = None) -> None:
        self._client = client or KISClient()
        self._env = settings.kis.env
        self._account_no = settings.kis.account_no
        self._product_code = settings.kis.account_product_code

    async def get_balance(
        self, exchange: str, currency: str = "USD"
    ) -> OverseasBalance:
        """해외 잔고를 조회한다.

        Args:
            exchange: 주문 거래소코드 OVRS_EXCG_CD ("NASD"/"NYSE"/"AMEX")
            currency: 거래통화코드 ("USD")
        """
        logger.info("[해외 잔고] EXCG=%s CRCY=%s", exchange, currency)
        tr_id = TR_ID_OVERSEAS_BALANCE_MAP.get(self._env, "TTTS3012R")
        params = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "TR_CRCY_CD": currency,
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }
        response = await self._client.get(
            OVERSEAS_BALANCE_PATH, params=params, tr_id=tr_id
        )
        output1 = response.get("output1", []) or []
        holdings: list[OverseasHolding] = []
        for item in output1:
            qty = int(_get(item, "ovrs_cblc_qty", "0") or "0")
            if qty <= 0:
                continue
            holdings.append(
                OverseasHolding(
                    symbol=_get(item, "ovrs_pdno"),
                    exchange=_get(item, "ovrs_excg_cd") or exchange,
                    quantity=qty,
                    avg_price=_decimal(_get(item, "pchs_avg_pric")),
                    current_price=_decimal(_get(item, "now_pric2")),
                    eval_amount=_decimal(_get(item, "ovrs_stck_evlu_amt")),
                    profit_loss=_decimal(_get(item, "frcr_evlu_pfls_amt")),
                    profit_rate=float(_get(item, "evlu_pfls_rt", "0") or "0"),
                    currency=_get(item, "tr_crcy_cd") or currency,
                )
            )
        return OverseasBalance(
            holdings=holdings, currency=currency, raw_response=response
        )

    async def get_buyable_amount(
        self, symbol: str, exchange: str, price: Decimal
    ) -> OverseasBuyable:
        """해외 매수가능금액을 조회한다(통합증거금 적용분 포함).

        Args:
            symbol: 종목 심볼
            exchange: 주문 거래소코드 OVRS_EXCG_CD
            price: 주문 예정 단가(외화)
        """
        logger.debug("[해외 매수가능] %s.%s @%s", exchange, symbol, price)
        tr_id = TR_ID_OVERSEAS_PSAMOUNT_MAP.get(self._env, "TTTS3007R")
        params = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "OVRS_ORD_UNPR": str(price),
            "ITEM_CD": symbol,
        }
        response = await self._client.get(
            OVERSEAS_PSAMOUNT_PATH, params=params, tr_id=tr_id
        )
        output = response.get("output", {}) or {}
        return OverseasBuyable(
            orderable_cash=_decimal(_get(output, "ord_psbl_frcr_amt")),
            orderable_qty=int(_get(output, "ord_psbl_qty", "0") or "0"),
            raw=output,
        )
