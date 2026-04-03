"""KIS 자동매매 대시보드 — Streamlit 앱.

실행: .venv/bin/streamlit run dashboard/app.py --server.port 8501
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ── 페이지 설정 ─────────────────────────────────

st.set_page_config(
    page_title="KIS 자동매매",
    page_icon="\U0001f4c8",
    layout="wide",
)

# ── DB 연결 ──────────────────────────────────────

DB_URL = st.secrets.get("DATABASE_URL", "postgresql://kis_user:kis_password@localhost:5432/kis_trader")
HEALTH_URL = st.secrets.get("HEALTH_URL", "http://localhost:8080/health")


@st.cache_resource
def get_engine():  # noqa: ANN201
    """DB 엔진을 생성한다."""
    return create_engine(DB_URL, pool_pre_ping=True)


def get_session() -> Session:
    """DB 세션을 반환한다."""
    factory = sessionmaker(bind=get_engine())
    return factory()


# ── 헬스체크 ─────────────────────────────────────

def fetch_health() -> dict | None:
    """헬스체크 API를 호출한다."""
    try:
        resp = httpx.get(HEALTH_URL, timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ── 데이터 조회 ──────────────────────────────────

def load_portfolio() -> pd.DataFrame:
    """보유 포트폴리오를 조회한다."""
    query = text("""
        SELECT s.code, s.name, p.quantity, p.avg_price, p.current_price,
               p.updated_at,
               CASE WHEN p.avg_price > 0
                    THEN ROUND(((p.current_price - p.avg_price) / p.avg_price * 100)::numeric, 2)
                    ELSE 0 END AS profit_rate,
               ROUND((p.quantity * (p.current_price - p.avg_price))::numeric, 0) AS profit_loss
        FROM portfolios p
        JOIN stocks s ON s.id = p.stock_id
        WHERE p.quantity > 0
        ORDER BY profit_loss DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn)


def load_daily_performance(days: int = 30) -> pd.DataFrame:
    """일일 성과를 조회한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT date, total_profit_loss, profit_rate, execution_count, details
        FROM daily_performances
        WHERE date >= :since
        ORDER BY date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_recent_orders(limit: int = 50) -> pd.DataFrame:
    """최근 주문 내역을 조회한다."""
    query = text("""
        SELECT o.created_at, s.code, s.name, o.order_type, o.quantity, o.price,
               o.status, o.order_no
        FROM orders o
        JOIN stocks s ON s.id = o.stock_id
        ORDER BY o.created_at DESC
        LIMIT :limit
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"limit": limit})


# ── 헤더 ────────────────────────────────────────

st.title("\U0001f4c8 KIS 자동매매 대시보드")

# ── 시스템 상태 ──────────────────────────────────

health = fetch_health()

col1, col2, col3, col4 = st.columns(4)

if health:
    components = health.get("components", {})
    trading = components.get("trading", {})
    scheduler = components.get("scheduler", {})
    db_status = components.get("db", {})

    col1.metric("시스템 상태", health.get("status", "unknown").upper())
    col2.metric("업타임", health.get("uptime", "-"))
    col3.metric("매매 사이클", f"#{trading.get('cycle_count', 0):,}")
    col4.metric("API 호출", f"{trading.get('daily_api_calls', 0):,}")
else:
    col1.metric("시스템 상태", "OFFLINE")
    col2.metric("업타임", "-")
    col3.metric("매매 사이클", "-")
    col4.metric("API 호출", "-")
    st.warning("헬스체크 서버에 연결할 수 없습니다.")

st.divider()

# ── 보유 포트폴리오 ──────────────────────────────

st.subheader("\U0001f4bc 보유 포트폴리오")

portfolio_df = load_portfolio()

if portfolio_df.empty:
    st.info("보유 종목이 없습니다.")
else:
    # 요약 지표
    total_pl = portfolio_df["profit_loss"].sum()
    total_eval = (portfolio_df["quantity"] * portfolio_df["current_price"]).sum()
    total_cost = (portfolio_df["quantity"] * portfolio_df["avg_price"]).sum()
    total_rate = ((total_eval - total_cost) / total_cost * 100) if total_cost > 0 else 0

    pcol1, pcol2, pcol3 = st.columns(3)
    pcol1.metric("보유 종목", f"{len(portfolio_df)}개")
    pcol2.metric("총 평가손익", f"{total_pl:,.0f}원", delta=f"{total_rate:+.2f}%")
    pcol3.metric("총 평가금액", f"{total_eval:,.0f}원")

    st.dataframe(
        portfolio_df[["code", "name", "quantity", "avg_price", "current_price", "profit_rate", "profit_loss"]].rename(
            columns={
                "code": "종목코드",
                "name": "종목명",
                "quantity": "수량",
                "avg_price": "평균가",
                "current_price": "현재가",
                "profit_rate": "수익률(%)",
                "profit_loss": "평가손익",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── 일일 성과 ────────────────────────────────────

st.subheader("\U0001f4c5 일일 성과 추이")

days = st.selectbox("기간", [7, 14, 30, 60, 90], index=2)
perf_df = load_daily_performance(days=days)

if perf_df.empty:
    st.info("성과 데이터가 없습니다.")
else:
    perf_df["date"] = pd.to_datetime(perf_df["date"])

    # 누적 수익률 계산
    perf_df["cumulative_pl"] = perf_df["total_profit_loss"].cumsum()

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.caption("일별 손익 (원)")
        st.bar_chart(perf_df.set_index("date")["total_profit_loss"], color="#4CAF50")

    with chart_col2:
        st.caption("누적 손익 (원)")
        st.line_chart(perf_df.set_index("date")["cumulative_pl"], color="#2196F3")

    # 성과 요약
    scol1, scol2, scol3, scol4 = st.columns(4)
    scol1.metric("총 손익", f"{perf_df['total_profit_loss'].sum():,.0f}원")
    scol2.metric("총 체결", f"{perf_df['execution_count'].sum():,}건")
    scol3.metric("승률", f"{(perf_df['total_profit_loss'] > 0).mean() * 100:.0f}%")
    scol4.metric("최대 손실일", f"{perf_df['total_profit_loss'].min():,.0f}원")

st.divider()

# ── 최근 주문 내역 ───────────────────────────────

st.subheader("\U0001f4cb 최근 주문 내역")

orders_df = load_recent_orders()

if orders_df.empty:
    st.info("주문 내역이 없습니다.")
else:
    st.dataframe(
        orders_df.rename(
            columns={
                "created_at": "시각",
                "code": "종목코드",
                "name": "종목명",
                "order_type": "유형",
                "quantity": "수량",
                "price": "가격",
                "status": "상태",
                "order_no": "주문번호",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

# ── 이벤트 로그 ──────────────────────────────────

st.divider()
st.subheader("\U0001f4dd 이벤트 로그")

event_query = text("""
    SELECT timestamp, level, category, message
    FROM event_logs
    ORDER BY timestamp DESC
    LIMIT 30
""")
try:
    with get_engine().connect() as conn:
        event_df = pd.read_sql(event_query, conn)
    if event_df.empty:
        st.info("이벤트 로그가 없습니다.")
    else:
        st.dataframe(
            event_df.rename(columns={
                "timestamp": "시각",
                "level": "레벨",
                "category": "분류",
                "message": "내용",
            }),
            use_container_width=True,
            hide_index=True,
        )
except Exception:
    st.info("이벤트 로그 테이블이 아직 생성되지 않았습니다.")

# ── 푸터 ────────────────────────────────────────

st.divider()
st.caption(f"환경: {health.get('env', '-') if health else '-'} | 데이터 갱신: 페이지 새로고침")
