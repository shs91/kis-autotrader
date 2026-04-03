"""성과 분석 페이지."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="성과 분석", page_icon="\U0001f4ca", layout="wide")

DB_URL = st.secrets.get("DATABASE_URL", "postgresql://kis_user:kis_password@localhost:5432/kis_trader")


@st.cache_resource
def get_engine():  # noqa: ANN201
    return create_engine(DB_URL, pool_pre_ping=True)


# ── 데이터 조회 ──────────────────────────────────

def load_daily_performance(days: int) -> pd.DataFrame:
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT date, total_profit_loss, profit_rate, execution_count
        FROM daily_performances
        WHERE date >= :since
        ORDER BY date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_orders_with_stocks() -> pd.DataFrame:
    query = text("""
        SELECT o.created_at, s.code, s.name, o.order_type, o.quantity, o.price, o.status
        FROM orders o
        JOIN stocks s ON s.id = o.stock_id
        WHERE o.status IN ('SUBMITTED', 'FILLED')
        ORDER BY o.created_at
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn)


# ── 페이지 ───────────────────────────────────────

st.title("\U0001f4ca 성과 분석")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)

perf_df = load_daily_performance(days=days)

if perf_df.empty:
    st.info("선택 기간에 성과 데이터가 없습니다.")
    st.stop()

perf_df["date"] = pd.to_datetime(perf_df["date"])

# ── 수익률 추이 ──────────────────────────────────

st.subheader("일별 수익률 추이")

perf_df["profit_rate_pct"] = perf_df["profit_rate"] * 100
st.line_chart(perf_df.set_index("date")["profit_rate_pct"], color="#FF9800")

# ── 통계 요약 ────────────────────────────────────

st.subheader("기간 통계")

win_days = (perf_df["total_profit_loss"] > 0).sum()
lose_days = (perf_df["total_profit_loss"] < 0).sum()
even_days = (perf_df["total_profit_loss"] == 0).sum()
total_days = len(perf_df)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("거래일 수", f"{total_days}일")
col2.metric("수익일 / 손실일", f"{win_days} / {lose_days}")
col3.metric("승률", f"{win_days / total_days * 100:.0f}%" if total_days > 0 else "-")
col4.metric("평균 일 손익", f"{perf_df['total_profit_loss'].mean():,.0f}원")
col5.metric("최대 수익 / 최대 손실", f"{perf_df['total_profit_loss'].max():,.0f} / {perf_df['total_profit_loss'].min():,.0f}")

# ── 주간별 집계 ──────────────────────────────────

st.subheader("주간별 성과")

perf_df["week"] = perf_df["date"].dt.isocalendar().week.astype(int)
perf_df["year"] = perf_df["date"].dt.isocalendar().year.astype(int)
weekly = perf_df.groupby(["year", "week"]).agg(
    total_pl=("total_profit_loss", "sum"),
    trades=("execution_count", "sum"),
    days=("date", "count"),
).reset_index()
weekly["label"] = weekly.apply(lambda r: f"{int(r['year'])}-W{int(r['week']):02d}", axis=1)

st.bar_chart(weekly.set_index("label")["total_pl"], color="#4CAF50")

# ── 종목별 매매 통계 ─────────────────────────────

st.subheader("종목별 매매 통계")

orders_df = load_orders_with_stocks()

if not orders_df.empty:
    buy_df = orders_df[orders_df["order_type"] == "BUY"].groupby(["code", "name"]).agg(
        buy_count=("quantity", "count"),
        buy_total_qty=("quantity", "sum"),
        avg_buy_price=("price", "mean"),
    ).reset_index()

    sell_df = orders_df[orders_df["order_type"] == "SELL"].groupby(["code", "name"]).agg(
        sell_count=("quantity", "count"),
        sell_total_qty=("quantity", "sum"),
        avg_sell_price=("price", "mean"),
    ).reset_index()

    stock_stats = buy_df.merge(sell_df, on=["code", "name"], how="outer").fillna(0)
    stock_stats["total_trades"] = stock_stats["buy_count"] + stock_stats["sell_count"]
    stock_stats = stock_stats.sort_values("total_trades", ascending=False)

    st.dataframe(
        stock_stats[["code", "name", "buy_count", "sell_count", "buy_total_qty", "sell_total_qty"]].rename(
            columns={
                "code": "종목코드",
                "name": "종목명",
                "buy_count": "매수 횟수",
                "sell_count": "매도 횟수",
                "buy_total_qty": "총 매수량",
                "sell_total_qty": "총 매도량",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("주문 데이터가 없습니다.")
