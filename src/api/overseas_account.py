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
OVERSEAS_PRESENT_BALANCE_PATH: str = (
    "/uapi/overseas-stock/v1/trading/inquire-present-balance"
)

TR_ID_OVERSEAS_BALANCE_MAP: dict[str, str] = {"virtual": "VTTS3012R", "real": "TTTS3012R"}
TR_ID_OVERSEAS_PSAMOUNT_MAP: dict[str, str] = {"virtual": "VTTS3007R", "real": "TTTS3007R"}
# 해외주식 체결기준현재잔고(CTRP6504R) — 외화예수금·총평가·총손익·고시환율 제공.
# 모의투자(virtual)는 미지원이라 실전(real) 전용. US 프로파일은 KIS_ENV=real.
TR_ID_OVERSEAS_PRESENT_BALANCE_MAP: dict[str, str] = {"real": "CTRP6504R"}


def _get_any(item: dict[str, Any], *keys: str, default: str = "") -> str:
    """후보 키들을 순서대로 시도해 첫 비어있지 않은 값을 반환한다.

    KIS 해외 present-balance 응답 필드명은 버전/문서별 편차가 있어(confidence=medium),
    실측 전까지 후보 키 목록으로 방어적으로 파싱한다.
    """
    for key in keys:
        val = _get(item, key, "")
        if val not in ("", None):
            return val
    return default


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


@dataclass
class OverseasPresentBalance:
    """해외 체결기준 현재잔고 요약 (외화 기준 + 고시환율).

    ``valid``=False면 응답 파싱이 신뢰 불가(필드 부재/0)임을 뜻하며, 호출부는
    보수적 폴백(보유 합산·예산값)을 써야 한다 — 라이브 자금 오표기 방지.
    """

    deposit: Decimal  # 외화 예수금
    total_eval: Decimal  # 외화 평가총액(보유 평가금액 합)
    total_profit_loss: Decimal  # 외화 평가손익
    profit_rate: float  # 평가수익률(%)
    fx_rate: Decimal  # 고시환율(1 외화 = ? 원)
    currency: str
    valid: bool
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

    async def get_present_balance(
        self, currency: str = "USD", country_code: str = "840"
    ) -> OverseasPresentBalance:
        """해외 체결기준 현재잔고(CTRP6504R)를 조회한다.

        외화 예수금·총평가금액·총평가손익·평가수익률·고시환율을 한 번에 반환한다
        (inquire-balance는 보유종목만, 예수금/환율은 미제공). 모의투자 미지원이라
        실전 전용. 응답 필드명 confidence=medium → 후보키 폴백 + ``valid`` 플래그로
        호출부의 보수적 폴백을 유도한다.

        Args:
            currency: 조회 통화("USD").
            country_code: 국가코드(미국=840).
        """
        tr_id = TR_ID_OVERSEAS_PRESENT_BALANCE_MAP.get(self._env)
        if tr_id is None:
            # 모의투자 등 미지원 환경 — 무효 반환(호출부 폴백).
            return OverseasPresentBalance(
                deposit=Decimal(0), total_eval=Decimal(0),
                total_profit_loss=Decimal(0), profit_rate=0.0,
                fx_rate=Decimal(0), currency=currency, valid=False, raw={},
            )
        logger.info("[해외 현재잔고] CRCY=%s NATN=%s", currency, country_code)
        params = {
            "CANO": self._account_no,
            "ACNT_PRDT_CD": self._product_code,
            "WCRC_FRCR_DVSN_CD": "02",  # 02=외화
            "NATN_CD": country_code,
            "TR_MKET_CD": "00",  # 전체 시장
            "INQR_DVSN_CD": "00",
        }
        response = await self._client.get(
            OVERSEAS_PRESENT_BALANCE_PATH, params=params, tr_id=tr_id
        )
        out2_list = response.get("output2", []) or []
        out3 = response.get("output3", {}) or {}
        if isinstance(out3, list):
            out3 = out3[0] if out3 else {}

        # 통화별 잔고(output2)에서 해당 통화 행 선택
        cur_row: dict[str, Any] = {}
        for row in out2_list:
            if _get(row, "crcy_cd", "").upper() == currency.upper():
                cur_row = row
                break
        if not cur_row and out2_list:
            cur_row = out2_list[0]

        deposit = _decimal(
            _get_any(cur_row, "frcr_dncl_amt_2", "frcr_dncl_amt1", "frcr_dncl_amt")
        )
        fx_rate = _decimal(_get_any(cur_row, "frst_bltn_exrt", "bass_exrt"))
        total_eval = _decimal(
            _get_any(out3, "frcr_evlu_tota", "evlu_amt_smtl_amt", "ovrs_tot_evlu_amt")
        )
        total_pl = _decimal(
            _get_any(out3, "tot_evlu_pfls_amt", "ovrs_tot_pfls", "frcr_evlu_pfls_amt")
        )
        profit_rate = float(
            _get_any(out3, "evlu_erng_rt", "tot_evlu_pfls_rt", default="0") or "0"
        )
        # 유효성: 예수금/평가 중 하나라도 양수면 신뢰. 둘 다 0이면 무효(폴백 유도).
        valid = deposit > 0 or total_eval > 0
        return OverseasPresentBalance(
            deposit=deposit,
            total_eval=total_eval,
            total_profit_loss=total_pl,
            profit_rate=profit_rate,
            fx_rate=fx_rate,
            currency=currency,
            valid=valid,
            raw=response,
        )
