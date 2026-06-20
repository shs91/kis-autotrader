"""전역 시장 선택(전체/한국/미국)과 SQL 필터 헬퍼.

사이드바의 시장 선택을 ``st.session_state`` 로 유지하고, 각 페이지는
``current_market()`` 로 선택값을 읽어 쿼리에 ``market_filter()`` 절을 끼운다.
"""

from __future__ import annotations

import streamlit as st

ALL = "ALL"
KRX = "KRX"
US = "US"

# 선택 가능한 시장(표시 라벨 포함). ALL은 필터 미적용(전체).
MARKETS: dict[str, str] = {
    ALL: "🌐 전체",
    KRX: "🇰🇷 한국",
    US: "🇺🇸 미국",
}

_SESSION_KEY = "selected_market"


def market_selector() -> str:
    """사이드바에 시장 선택 위젯을 렌더하고 선택된 시장 코드를 반환한다."""
    options = list(MARKETS.keys())
    selected = st.sidebar.radio(
        "시장",
        options,
        format_func=lambda code: MARKETS[code],
        key=_SESSION_KEY,
    )
    return str(selected)


def current_market() -> str:
    """현재 선택된 시장 코드(ALL/KRX/US). 미설정 시 ALL."""
    return str(st.session_state.get(_SESSION_KEY, ALL))


def is_all() -> bool:
    """'전체'(시장 필터 미적용) 여부."""
    return current_market() == ALL


def label(market: str) -> str:
    """시장 코드의 표시 라벨."""
    return MARKETS.get(market, market)


def market_param() -> dict[str, object]:
    """선택 시장의 SQL 바인드 파라미터. ALL이면 ``{"market": None}``.

    쿼리는 정적 술어 ``(:market IS NULL OR <col> = :market)`` 를 그대로 쓰고
    이 파라미터를 함께 넘긴다(f-string SQL 보간을 피해 정적·안전하게 유지).
    ALL일 때 ``:market`` 이 NULL이라 ``IS NULL`` 분기가 필터를 무력화한다.
    """
    market = current_market()
    return {"market": None if market == ALL else market}
