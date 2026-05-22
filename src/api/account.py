"""잔고 및 계좌 조회 API 모듈."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from src.api.client import KISClient
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 계좌 조회 엔드포인트
BALANCE_PATH: str = "/uapi/domestic-stock/v1/trading/inquire-balance"
EXECUTIONS_PATH: str = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

# tr_id 매핑
TR_ID_BALANCE_MAP: dict[str, str] = {
    "virtual": "VTTC8434R",
    "real": "TTTC8434R",
}

TR_ID_EXECUTIONS_MAP: dict[str, str] = {
    "virtual": "VTTC8001R",
    "real": "TTTC8001R",
}


def _get(data: dict[str, Any], key: str, default: str = "") -> str:
    """대소문자를 구분하지 않고 딕셔너리에서 값을 가져온다."""
    return cast(str, data.get(key) or data.get(key.lower(), default))


@dataclass
class StockHolding:
    """보유 종목 정보."""

    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: int
    eval_amount: int
    profit_loss: int
    profit_rate: float


@dataclass
class Balance:
    """잔고 정보."""

    deposit: int
    total_eval_amount: int
    total_profit_loss: int
    total_profit_rate: float
    holdings: list[StockHolding]
    raw_response: dict[str, Any]


@dataclass
class Execution:
    """체결 내역."""

    order_date: str
    order_time: str
    stock_code: str
    stock_name: str
    side: str
    quantity: int
    price: int
    amount: int
    order_no: str


class AccountAPI:
    """KIS 잔고 및 계좌 조회 API를 호출한다."""

    def __init__(self, client: KISClient | None = None) -> None:
        """AccountAPI를 초기화한다.

        Args:
            client: KISClient 인스턴스 (기본값: 새로 생성)
        """
        self._client = client or KISClient()
        self._env = settings.kis.env
        self._account_no = settings.kis.account_no
        self._product_code = settings.kis.account_product_code

    async def get_balance(self) -> Balance:
        """잔고를 조회한다 (보유 종목, 예수금 포함).

        Returns:
            잔고 정보

        Raises:
            KISAutoTraderError: API 호출 실패 시
        """
        logger.info("[잔고 조회] 계좌=%s", self._account_no)

        tr_id = TR_ID_BALANCE_MAP.get(self._env, "VTTC8434R")

        params = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        response = await self._client.get(BALANCE_PATH, params=params, tr_id=tr_id)

        # 보유 종목 파싱
        output1 = response.get("output1", [])
        holdings: list[StockHolding] = []

        for item in output1:
            qty = int(_get(item, "HLDG_QTY", "0"))
            if qty <= 0:
                continue

            holdings.append(
                StockHolding(
                    stock_code=_get(item, "PDNO"),
                    stock_name=_get(item, "PRDT_NAME"),
                    quantity=qty,
                    avg_price=float(_get(item, "PCHS_AVG_PRIC", "0")),
                    current_price=int(_get(item, "PRPR", "0")),
                    eval_amount=int(_get(item, "EVLU_AMT", "0")),
                    profit_loss=int(_get(item, "EVLU_PFLS_AMT", "0")),
                    profit_rate=float(_get(item, "EVLU_PFLS_RT", "0")),
                )
            )

        # 계좌 요약 파싱
        output2 = response.get("output2", [{}])
        summary = output2[0] if output2 else {}

        return Balance(
            deposit=int(_get(summary, "DNCA_TOT_AMT", "0")),
            total_eval_amount=int(_get(summary, "SCTS_EVLU_AMT", "0")),
            total_profit_loss=int(_get(summary, "EVLU_PFLS_SMTL_AMT", "0")),
            # KIS API 실제 응답 필드는 ASST_ICDC_ERNG_RT (자산증감수익률).
            # TOT_EVLU_PFLS_RT 같은 필드는 응답에 존재하지 않아 항상 0이 반환되던 버그.
            total_profit_rate=float(_get(summary, "ASST_ICDC_ERNG_RT", "0")),
            holdings=holdings,
            raw_response=response,
        )

    async def get_executions(self) -> list[Execution]:
        """당일 체결 내역을 조회한다.

        Returns:
            체결 내역 목록

        Raises:
            KISAutoTraderError: API 호출 실패 시
        """
        logger.info("[체결내역 조회] 계좌=%s", self._account_no)

        tr_id = TR_ID_EXECUTIONS_MAP.get(self._env, "VTTC8001R")

        params = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "INQR_STRT_DT": _today_str_compact(),
            "INQR_END_DT": _today_str_compact(),
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "01",
            "PDNO": "",
            "CCLD_DVSN": "01",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "01",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        response = await self._client.get(EXECUTIONS_PATH, params=params, tr_id=tr_id)

        output1 = response.get("output1", [])
        results: list[Execution] = []

        for item in output1:
            qty = int(_get(item, "TOT_CCLD_QTY", "0"))
            if qty <= 0:
                continue

            side_code = _get(item, "SLL_BUY_DVSN_CD")
            side = "매수" if side_code == "02" else "매도"

            results.append(
                Execution(
                    order_date=_get(item, "ORD_DT"),
                    order_time=_get(item, "ORD_TMD"),
                    stock_code=_get(item, "PDNO"),
                    stock_name=_get(item, "PRDT_NAME"),
                    side=side,
                    quantity=qty,
                    price=int(_get(item, "AVG_PRVS", "0")),
                    amount=int(_get(item, "TOT_CCLD_AMT", "0")),
                    order_no=_get(item, "ODNO"),
                )
            )

        return results


def _today_str_compact() -> str:
    """오늘 날짜를 YYYYMMDD 형식 문자열로 반환한다."""
    import datetime

    return datetime.date.today().strftime("%Y%m%d")
