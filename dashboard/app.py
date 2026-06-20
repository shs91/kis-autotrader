"""KIS 자동매매 대시보드 — 엔트리포인트.

``st.navigation`` 으로 한글 메뉴/그룹을 구성하고, 사이드바 상단에 전역 시장
선택(전체/한국/미국)을 둔다. 시장 선택은 세션에 유지되어 모든 페이지가 따른다.

실행: .venv/bin/streamlit run dashboard/app.py --server.port 8501
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# lib / views 를 import할 수 있도록 dashboard 디렉토리를 path에 추가
_DASHBOARD_DIR = Path(__file__).resolve().parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from lib import db  # noqa: E402 — path 보강 후 import
from lib.market import market_selector  # noqa: E402

st.set_page_config(page_title="KIS 자동매매", page_icon="\U0001f4c8", layout="wide")

# ── 사이드바: 전역 시장 선택 + DB 상태 ──────────────
st.sidebar.title("\U0001f4c8 KIS 자동매매")
market_selector()

_db_name = db.current_database()
if _db_name and _db_name != "kis_trader_real":
    st.sidebar.warning(
        f"⚠️ 모의 DB(`{_db_name}`) 연결 — 실데이터가 아닙니다. "
        "`.env`의 `KIS_ENV=real` 확인 후 대시보드 재시작.",
        icon="⚠️",
    )
st.sidebar.caption(f"DB: `{_db_name or '연결 실패'}`")

# ── 네비게이션 (한글 라벨·그룹) ─────────────────────
pages = {
    "분석": [
        st.Page("views/overview.py", title="개요", icon="\U0001f4ca", default=True),
        st.Page("views/positions.py", title="보유 상세", icon="\U0001f4cd"),
        st.Page("views/trades.py", title="매매", icon="\U0001f4b9"),
        st.Page("views/signals.py", title="신호", icon="\U0001f4e1"),
        st.Page("views/risk.py", title="리스크", icon="\U0001f6e1"),
        st.Page("views/performance.py", title="성과", icon="\U0001f4c8"),
    ],
    "시스템": [
        st.Page("views/pipeline.py", title="파이프라인 KPI", icon="\U0001f6e0"),
    ],
}

st.navigation(pages).run()
