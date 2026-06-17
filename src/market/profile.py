"""시장별 메타데이터(MarketProfile)와 레지스트리.

멀티마켓(KRX/US) 분기를 선언적으로 집약한다. 국내/해외 API의 엔드포인트·
파라미터·응답 체계가 완전히 다르므로, 시장 종속 값을 코드 곳곳의 ``if`` 분기
대신 이 프로파일 한 곳에 모은다. 신규 시장 추가 시 프로파일 인스턴스만 추가한다.

순환 import를 피하기 위해 이 모듈은 ``src.config``를 import하지 않으며,
``MARKET`` 환경변수는 ``os.getenv``로 직접 읽는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketHours:
    """시장별 스케줄 시각 (시, 분). 스케줄러가 **시장 타임존**에서 cron으로 사용한다.

    각 값은 ``(hour, minute)``. US는 ET(America/New_York) 기준이라 KST에서 자정을
    교차하지만, 스케줄러를 시장 타임존에서 돌리면 같은 날 세션으로 단순해진다.
    """

    pre_market: tuple[int, int]
    """장 시작 전 작업(리스크 상태 재구성 등)."""
    register: tuple[int, int]
    """당일 장중 매매 사이클 잡 등록(장 시작 직전)."""
    market_open: tuple[int, int]
    """장중 매매 사이클 시작."""
    market_close: tuple[int, int]
    """장중 매매 사이클 종료(실제 폐장 약간 전)."""
    post_market: tuple[int, int]
    """장 마감 후 작업(결산/캘린더/포트폴리오 동기화)."""
    summary: tuple[int, int]
    """일일 요약 집계."""


# KRX 시각 — jobs.py 기존 상수와 동일(행동 불변). KST 타임존에서 cron.
_KRX_TRADING_HOURS = MarketHours(
    pre_market=(8, 30),
    register=(8, 55),
    market_open=(9, 0),
    market_close=(15, 20),
    post_market=(15, 40),
    summary=(16, 0),
)

# US 정규장(ET) — 09:30~16:00. 사이클 종료는 폐장 약간 전(15:50). ET 타임존에서 cron.
_US_TRADING_HOURS = MarketHours(
    pre_market=(9, 0),
    register=(9, 25),
    market_open=(9, 30),
    market_close=(15, 50),
    post_market=(16, 10),
    summary=(16, 30),
)


@dataclass(frozen=True)
class MarketProfile:
    """한 시장(KRX/US 등)의 매매에 필요한 메타데이터 묶음."""

    market_code: str
    """시장 식별 코드 ("KRX" | "US")."""

    currency: str
    """결제 통화 ISO 코드 ("KRW" | "USD")."""

    currency_symbol: str
    """통화 기호 ("₩" | "$")."""

    price_precision: int
    """가격 소수점 자릿수. KRX=0(정수 원), US=2(0.01달러)."""

    timezone: str
    """시장 IANA 타임존 ("Asia/Seoul" | "America/New_York")."""

    kis_env: str
    """시장별 기본 KIS_ENV ("virtual" | "real"). 프로세스 env로 override 가능."""

    credentials_env_prefix: str
    """자격증명 환경변수 prefix ("KIS" | "KIS_US")."""

    exchanges: tuple[str, ...]
    """주문용 거래소코드(OVRS_EXCG_CD) 목록. KRX는 빈 튜플."""

    quote_exchange_map: dict[str, str] = field(default_factory=dict)
    """주문 거래소코드(4자리) → 시세 거래소코드(3자리) 매핑. KRX는 빈 dict."""

    trading_hours: MarketHours = field(default_factory=lambda: _KRX_TRADING_HOURS)
    """시장 타임존 기준 스케줄 시각(시,분). 기본은 KRX 시각."""

    @property
    def is_overseas(self) -> bool:
        """해외 시장이면 True (국내 KRX는 False)."""
        return self.market_code != "KRX"


KRX_PROFILE = MarketProfile(
    market_code="KRX",
    currency="KRW",
    currency_symbol="₩",
    price_precision=0,
    timezone="Asia/Seoul",
    kis_env="virtual",
    credentials_env_prefix="KIS",
    exchanges=(),
    quote_exchange_map={},
    trading_hours=_KRX_TRADING_HOURS,
)

US_PROFILE = MarketProfile(
    market_code="US",
    currency="USD",
    currency_symbol="$",
    price_precision=2,
    timezone="America/New_York",
    kis_env="real",
    credentials_env_prefix="KIS_US",
    exchanges=("NASD", "NYSE", "AMEX"),
    quote_exchange_map={"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"},
    trading_hours=_US_TRADING_HOURS,
)

_PROFILES: dict[str, MarketProfile] = {
    KRX_PROFILE.market_code: KRX_PROFILE,
    US_PROFILE.market_code: US_PROFILE,
}


def get_market_profile(market_code: str) -> MarketProfile:
    """시장 코드로 MarketProfile을 조회한다(대소문자 무관).

    Args:
        market_code: "KRX" 또는 "US" (대소문자 무관)

    Returns:
        해당 시장의 프로파일

    Raises:
        ValueError: 지원하지 않는 시장 코드인 경우
    """
    try:
        return _PROFILES[market_code.upper()]
    except KeyError:
        raise ValueError(f"지원하지 않는 시장: {market_code}") from None


def active_market_profile() -> MarketProfile:
    """``MARKET`` 환경변수로 활성 시장 프로파일을 반환한다(기본 "KRX").

    분리 프로세스 운영에서 주간 프로세스는 ``MARKET=KRX``, 야간 프로세스는
    ``MARKET=US``로 기동한다. 미설정 시 기존 동작(KRX)을 보존한다.
    """
    return get_market_profile(os.getenv("MARKET", "KRX"))
