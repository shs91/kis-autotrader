"""주문 API 모듈 (매수/매도/정정/취소)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.api.client import KISClient
from src.config import settings
from src.utils.exceptions import OrderError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 주문 엔드포인트
ORDER_PATH: str = "/uapi/domestic-stock/v1/trading/order-cash"

# tr_id 매핑: (환경, 주문유형) → tr_id
TR_ID_MAP: dict[tuple[str, str], str] = {
    ("virtual", "buy"): "VTTC0802U",
    ("virtual", "sell"): "VTTC0801U",
    ("real", "buy"): "TTTC0802U",
    ("real", "sell"): "TTTC0801U",
}

# 정정/취소 tr_id
TR_ID_MODIFY_MAP: dict[str, str] = {
    "virtual": "VTTC0803U",
    "real": "TTTC0803U",
}

TR_ID_CANCEL_MAP: dict[str, str] = {
    "virtual": "VTTC0803U",
    "real": "TTTC0803U",
}

# 주문 구분 코드
ORDER_TYPE_LIMIT: str = "00"   # 지정가
ORDER_TYPE_MARKET: str = "01"  # 시장가


@dataclass
class OrderResult:
    """주문 결과 정보."""

    order_no: str
    order_time: str
    message: str
    raw_response: dict[str, Any]


class OrderAPI:
    """KIS 주문 API를 호출한다."""

    def __init__(self, client: KISClient | None = None) -> None:
        """OrderAPI를 초기화한다.

        Args:
            client: KISClient 인스턴스 (기본값: 새로 생성)
        """
        self._client = client or KISClient()
        self._env = settings.kis.env
        self._account_no = settings.kis.account_no
        self._product_code = settings.kis.account_product_code

    async def buy(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0,
        order_type: str = ORDER_TYPE_MARKET,
    ) -> OrderResult:
        """매수 주문을 실행한다.

        Args:
            stock_code: 종목코드 (6자리)
            quantity: 주문 수량
            price: 주문 가격 (시장가 주문 시 0)
            order_type: 주문 구분 ("00": 지정가, "01": 시장가)

        Returns:
            주문 결과

        Raises:
            OrderError: 주문 실패 시
        """
        logger.info(
            "[매수] 종목=%s, 수량=%d, 가격=%d, 유형=%s",
            stock_code, quantity, price, order_type,
        )
        return await self._place_order("buy", stock_code, quantity, price, order_type)

    async def sell(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0,
        order_type: str = ORDER_TYPE_MARKET,
    ) -> OrderResult:
        """매도 주문을 실행한다.

        Args:
            stock_code: 종목코드 (6자리)
            quantity: 주문 수량
            price: 주문 가격 (시장가 주문 시 0)
            order_type: 주문 구분 ("00": 지정가, "01": 시장가)

        Returns:
            주문 결과

        Raises:
            OrderError: 주문 실패 시
        """
        logger.info(
            "[매도] 종목=%s, 수량=%d, 가격=%d, 유형=%s",
            stock_code, quantity, price, order_type,
        )
        return await self._place_order("sell", stock_code, quantity, price, order_type)

    async def modify(
        self,
        order_no: str,
        stock_code: str,
        quantity: int,
        price: int,
    ) -> OrderResult:
        """주문을 정정한다.

        Args:
            order_no: 원주문 번호
            stock_code: 종목코드
            quantity: 정정 수량
            price: 정정 가격

        Returns:
            정정 결과

        Raises:
            OrderError: 정정 실패 시
        """
        logger.info(
            "[정정] 주문번호=%s, 종목=%s, 수량=%d, 가격=%d",
            order_no, stock_code, quantity, price,
        )

        tr_id = TR_ID_MODIFY_MAP.get(self._env)
        if not tr_id:
            raise OrderError(f"지원하지 않는 환경입니다: {self._env}")

        body = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_no,
            "ORD_DVSN": ORDER_TYPE_LIMIT,
            "RVSE_CNCL_DVSN_CD": "01",  # 정정
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price),
            "QTY_ALL_ORD_YN": "N",
        }

        response = await self._client.post(
            ORDER_PATH, body=body, tr_id=tr_id, use_hashkey=True
        )
        return self._parse_order_response(response)

    async def cancel(
        self,
        order_no: str,
        stock_code: str,
        quantity: int,
    ) -> OrderResult:
        """주문을 취소한다.

        Args:
            order_no: 원주문 번호
            stock_code: 종목코드
            quantity: 취소 수량

        Returns:
            취소 결과

        Raises:
            OrderError: 취소 실패 시
        """
        logger.info(
            "[취소] 주문번호=%s, 종목=%s, 수량=%d",
            order_no, stock_code, quantity,
        )

        tr_id = TR_ID_CANCEL_MAP.get(self._env)
        if not tr_id:
            raise OrderError(f"지원하지 않는 환경입니다: {self._env}")

        body = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_no,
            "ORD_DVSN": ORDER_TYPE_LIMIT,
            "RVSE_CNCL_DVSN_CD": "02",  # 취소
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }

        response = await self._client.post(
            ORDER_PATH, body=body, tr_id=tr_id, use_hashkey=True
        )
        return self._parse_order_response(response)

    async def _place_order(
        self,
        side: str,
        stock_code: str,
        quantity: int,
        price: int,
        order_type: str,
    ) -> OrderResult:
        """주문을 실행하는 내부 메서드.

        Args:
            side: "buy" 또는 "sell"
            stock_code: 종목코드
            quantity: 주문 수량
            price: 주문 가격
            order_type: 주문 구분

        Returns:
            주문 결과

        Raises:
            OrderError: 주문 실패 시
        """
        tr_id = TR_ID_MAP.get((self._env, side))
        if not tr_id:
            raise OrderError(f"지원하지 않는 환경/주문유형입니다: env={self._env}, side={side}")

        body = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "PDNO": stock_code,
            "ORD_DVSN": order_type,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price),
        }

        response = await self._client.post(
            ORDER_PATH, body=body, tr_id=tr_id, use_hashkey=True
        )
        return self._parse_order_response(response)

    def _parse_order_response(self, response: dict[str, Any]) -> OrderResult:
        """주문 응답을 파싱한다.

        Args:
            response: API 응답 딕셔너리

        Returns:
            파싱된 주문 결과

        Raises:
            OrderError: 응답이 실패인 경우
        """
        rt_cd = response.get("rt_cd", "")
        msg1 = response.get("msg1", "")

        if rt_cd != "0":
            raise OrderError(
                f"주문 실패 (rt_cd={rt_cd}): {msg1}", rt_cd=rt_cd, msg1=msg1,
            )

        output = response.get("output", {})
        return OrderResult(
            order_no=output.get("ODNO", ""),
            order_time=output.get("ORD_TMD", ""),
            message=msg1,
            raw_response=response,
        )
