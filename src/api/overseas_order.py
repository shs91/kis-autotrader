"""해외(미국) 주문 API 모듈 (매수/매도/정정/취소).

단가는 Decimal, 결과는 기존 OrderResult 재사용. 미국 매수는 지정가(ORD_DVSN
"00")만 가능, 시장가는 OVRS_ORD_UNPR="0".
"""

from __future__ import annotations

from decimal import Decimal

from src.api.client import KISClient
from src.api.order import OrderResult
from src.config import settings
from src.utils.exceptions import OrderError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

OVERSEAS_ORDER_PATH: str = "/uapi/overseas-stock/v1/trading/order"
OVERSEAS_ORDER_RVSECNCL_PATH: str = "/uapi/overseas-stock/v1/trading/order-rvsecncl"

TR_ID_OVERSEAS_BUY_MAP: dict[str, str] = {"virtual": "VTTT1002U", "real": "TTTT1002U"}
TR_ID_OVERSEAS_SELL_MAP: dict[str, str] = {"virtual": "VTTT1006U", "real": "TTTT1006U"}
# 정정/취소 공통 (confidence=medium, 실측 재확인 필요)
TR_ID_OVERSEAS_RVSECNCL_MAP: dict[str, str] = {"virtual": "VTTT1004U", "real": "TTTT1004U"}

ORDER_TYPE_LIMIT: str = "00"  # 미국 매수는 지정가만


class OverseasOrderAPI:
    """KIS 해외주식 주문 API."""

    def __init__(self, client: KISClient | None = None) -> None:
        self._client = client or KISClient()
        self._env = settings.kis.env
        self._account_no = settings.kis.account_no
        self._product_code = settings.kis.account_product_code

    async def buy(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_type: str = ORDER_TYPE_LIMIT,
    ) -> OrderResult:
        """해외 매수 주문(미국은 지정가). 시장가는 price=Decimal('0')."""
        logger.info("[해외 매수] %s.%s qty=%d @%s", exchange, symbol, quantity, price)
        return await self._place("buy", symbol, exchange, quantity, price, order_type)

    async def sell(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_type: str = ORDER_TYPE_LIMIT,
    ) -> OrderResult:
        """해외 매도 주문."""
        logger.info("[해외 매도] %s.%s qty=%d @%s", exchange, symbol, quantity, price)
        return await self._place("sell", symbol, exchange, quantity, price, order_type)

    async def _place(
        self,
        side: str,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
        order_type: str,
    ) -> OrderResult:
        if side == "buy":
            tr_id = TR_ID_OVERSEAS_BUY_MAP.get(self._env, "TTTT1002U")
        else:
            tr_id = TR_ID_OVERSEAS_SELL_MAP.get(self._env, "TTTT1006U")
        body = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": order_type,
        }
        if side == "sell":
            body["SLL_TYPE"] = "00"
        # 주문 체결은 비멱등 — 5xx/타임아웃 재시도 시 실자금 중복주문 위험이라
        # 재시도하지 않는다(실패 시 다음 사이클이 잔고로 재조정).
        response = await self._client.post(
            OVERSEAS_ORDER_PATH, body=body, tr_id=tr_id, use_hashkey=True,
            idempotent=False,
        )
        return self._parse(response)

    async def modify(
        self,
        order_no: str,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
    ) -> OrderResult:
        """해외 주문 정정."""
        logger.info("[해외 정정] ord=%s %s.%s", order_no, exchange, symbol)
        return await self._rvsecncl("01", order_no, symbol, exchange, quantity, price)

    async def cancel(
        self, order_no: str, symbol: str, exchange: str, quantity: int
    ) -> OrderResult:
        """해외 주문 취소."""
        logger.info("[해외 취소] ord=%s %s.%s", order_no, exchange, symbol)
        return await self._rvsecncl(
            "02", order_no, symbol, exchange, quantity, Decimal("0")
        )

    async def _rvsecncl(
        self,
        rvse_cncl: str,
        order_no: str,
        symbol: str,
        exchange: str,
        quantity: int,
        price: Decimal,
    ) -> OrderResult:
        tr_id = TR_ID_OVERSEAS_RVSECNCL_MAP.get(self._env, "TTTT1004U")
        body = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORGN_ODNO": order_no,
            "RVSE_CNCL_DVSN_CD": rvse_cncl,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
        }
        response = await self._client.post(
            OVERSEAS_ORDER_RVSECNCL_PATH, body=body, tr_id=tr_id, use_hashkey=True
        )
        return self._parse(response)

    def _parse(self, response: dict[str, object]) -> OrderResult:
        rt_cd = str(response.get("rt_cd", ""))
        msg1 = str(response.get("msg1", ""))
        if rt_cd != "0":
            raise OrderError(
                f"해외 주문 실패 (rt_cd={rt_cd}): {msg1}", rt_cd=rt_cd, msg1=msg1
            )
        output = response.get("output", {})
        out = output if isinstance(output, dict) else {}
        return OrderResult(
            order_no=str(out.get("ODNO", "")),
            order_time=str(out.get("ORD_TMD", "")),
            message=msg1,
            raw_response=response,
        )
