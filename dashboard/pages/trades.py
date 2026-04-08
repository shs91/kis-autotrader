"""매매 분석 페이지 — trades 테이블 기반."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="매매 분석", page_icon="\U0001f4b9", layout="wide")

DB_URL = st.secrets.get(
    "DATABASE_URL",
    "postgresql://kis_user:kis_password@localhost:5432/kis_trader",
)


@st.cache_resource
def get_engine():  # noqa: ANN201
    return create_engine(DB_URL, pool_pre_ping=True)


# ── 데이터 조회 ──────────────────────────────────


def load_trades(since: date) -> pd.DataFrame:
    """기간 내 체결 내역을 조회한다."""
    query = text("""
        SELECT traded_at, stock_code, stock_name, trade_type,
               quantity, price, total_amount,
               buy_reason, sell_reason, signal_type,
               profit_loss_pct, profit_loss_amount, cycle_number
        FROM trades
        WHERE traded_at >= :since
        ORDER BY traded_at
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_stock_pnl(since: date) -> pd.DataFrame:
    """종목별 손익을 집계한다."""
    query = text("""
        SELECT stock_code, stock_name,
               COUNT(*) FILTER (WHERE trade_type = 'BUY') AS buy_count,
               COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
               COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS total_pnl,
               ROUND(AVG(profit_loss_pct)
                     FILTER (WHERE trade_type = 'SELL')::numeric, 2) AS avg_pnl_pct
        FROM trades
        WHERE traded_at >= :since
        GROUP BY stock_code, stock_name
        ORDER BY total_pnl DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_buy_reason_dist(since: date) -> pd.DataFrame:
    """매수 사유 분포를 집계한다."""
    query = text("""
        SELECT buy_reason,
               COUNT(*) AS count,
               COALESCE(SUM(total_amount), 0) AS total_amount
        FROM trades
        WHERE trade_type = 'BUY' AND traded_at >= :since
        GROUP BY buy_reason
        ORDER BY count DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_sell_reason_dist(since: date) -> pd.DataFrame:
    """매도 사유 분포를 집계한다."""
    query = text("""
        SELECT sell_reason,
               COUNT(*) AS count,
               COALESCE(SUM(profit_loss_amount), 0) AS total_pnl,
               ROUND(AVG(profit_loss_pct)::numeric, 2) AS avg_pnl_pct
        FROM trades
        WHERE trade_type = 'SELL' AND traded_at >= :since
        GROUP BY sell_reason
        ORDER BY count DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_daily_trade_counts(since: date) -> pd.DataFrame:
    """일별 매매 건수를 집계한다."""
    query = text("""
        SELECT traded_at::date AS trade_date,
               COUNT(*) FILTER (WHERE trade_type = 'BUY') AS buy_count,
               COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
               COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS daily_pnl
        FROM trades
        WHERE traded_at >= :since
        GROUP BY trade_date
        ORDER BY trade_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


# ── 페이지 ───────────────────────────────────────

st.title("\U0001f4b9 매매 분석")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)
since = date.today() - timedelta(days=days)

trades_df = load_trades(since)

if trades_df.empty:
    st.info("선택 기간에 체결 데이터가 없습니다.")
    st.stop()

trades_df["traded_at"] = pd.to_datetime(trades_df["traded_at"])

# ── KPI ──────────────────────────────────────────

total_buys = (trades_df["trade_type"] == "BUY").sum()
total_sells = (trades_df["trade_type"] == "SELL").sum()
sell_df = trades_df[trades_df["trade_type"] == "SELL"]
total_pnl = sell_df["profit_loss_amount"].sum()
wins = (sell_df["profit_loss_amount"] > 0).sum()
win_rate = (wins / len(sell_df) * 100) if len(sell_df) > 0 else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("총 매수", f"{total_buys}건")
k2.metric("총 매도", f"{total_sells}건")
k3.metric("실현손익", f"{total_pnl:,.0f}원")
k4.metric("승률", f"{win_rate:.0f}%")
k5.metric("평균 수익률",
          f"{sell_df['profit_loss_pct'].mean():.2f}%" if len(sell_df) > 0 else "-")

st.divider()

# ── 일별 매매 추이 ───────────────────────────────

st.subheader("\U0001f4c5 일별 매매 추이")

daily_df = load_daily_trade_counts(since)

if not daily_df.empty:
    daily_df["trade_date"] = pd.to_datetime(daily_df["trade_date"])

    chart_c1, chart_c2 = st.columns(2)

    with chart_c1:
        st.caption("일별 매수/매도 건수")
        chart_data = daily_df.set_index("trade_date")[["buy_count", "sell_count"]]
        chart_data.columns = ["매수", "매도"]
        st.bar_chart(chart_data)

    with chart_c2:
        st.caption("일별 실현손익")
        pnl_data = daily_df.set_index("trade_date")["daily_pnl"]
        pnl_data.name = "손익"
        st.bar_chart(pnl_data, color="#4CAF50")

st.divider()

# ── 종목별 손익 ──────────────────────────────────

st.subheader("\U0001f3af 종목별 손익")

stock_pnl = load_stock_pnl(since)

if not stock_pnl.empty:
    # 차트: 상위 10종목
    top_stocks = stock_pnl.head(10).copy()
    top_stocks["label"] = top_stocks["stock_name"] + " (" + top_stocks["stock_code"] + ")"

    st.bar_chart(
        top_stocks.set_index("label")["total_pnl"],
        color="#2196F3",
    )

    st.dataframe(
        stock_pnl.rename(columns={
            "stock_code": "종목코드", "stock_name": "종목명",
            "buy_count": "매수", "sell_count": "매도",
            "total_pnl": "실현손익", "avg_pnl_pct": "평균수익률(%)",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── 매수 사유 분포 ───────────────────────────────

st.subheader("\U0001f4a1 매수 사유 분석")

buy_reason_df = load_buy_reason_dist(since)

if buy_reason_df.empty:
    st.info("매수 사유 데이터가 없습니다.")
else:
    buy_reason_labels = {
        "GOLDEN_CROSS": "골든크로스",
        "RSI_OVERSOLD": "RSI 과매도",
        "ENSEMBLE": "앙상블",
        "MANUAL": "수동",
    }
    buy_reason_df["buy_reason"] = buy_reason_df["buy_reason"].fillna("UNKNOWN")
    buy_reason_df["label"] = buy_reason_df["buy_reason"].map(
        lambda x: buy_reason_labels.get(x, x)
    )

    brc1, brc2 = st.columns(2)

    with brc1:
        st.caption("사유별 건수")
        st.bar_chart(buy_reason_df.set_index("label")["count"])

    with brc2:
        st.caption("사유별 매수금액")
        st.bar_chart(buy_reason_df.set_index("label")["total_amount"], color="#2196F3")

    st.dataframe(
        buy_reason_df[["label", "count", "total_amount"]].rename(columns={
            "label": "매수사유", "count": "건수",
            "total_amount": "총 매수금액",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── 매도 사유 분포 ───────────────────────────────

st.subheader("\U0001f6a8 매도 사유 분석")

reason_df = load_sell_reason_dist(since)

if not reason_df.empty:
    reason_labels = {
        "STOP_LOSS": "손절",
        "TAKE_PROFIT": "익절",
        "STRATEGY": "전략매도",
        "MANUAL": "수동",
        "UNKNOWN": "미분류",
    }
    reason_df["sell_reason"] = reason_df["sell_reason"].fillna("UNKNOWN")
    reason_df["label"] = reason_df["sell_reason"].map(
        lambda x: reason_labels.get(x, x)
    )

    rc1, rc2 = st.columns(2)

    with rc1:
        st.caption("사유별 건수")
        st.bar_chart(reason_df.set_index("label")["count"])

    with rc2:
        st.caption("사유별 손익")
        st.bar_chart(reason_df.set_index("label")["total_pnl"], color="#FF9800")

    st.dataframe(
        reason_df[["label", "count", "total_pnl", "avg_pnl_pct"]].rename(columns={
            "label": "매도사유", "count": "건수",
            "total_pnl": "총 손익", "avg_pnl_pct": "평균수익률(%)",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── 체결 내역 테이블 ─────────────────────────────

st.subheader("\U0001f4cb 체결 내역 상세")

_buy_reason_labels = {
    "GOLDEN_CROSS": "골든크로스",
    "RSI_OVERSOLD": "RSI 과매도",
    "ENSEMBLE": "앙상블",
    "MANUAL": "수동",
}
_sell_reason_labels = {
    "STOP_LOSS": "손절",
    "TAKE_PROFIT": "익절",
    "STRATEGY": "전략매도",
    "MANUAL": "수동",
}

detail_df = trades_df.copy()
detail_df["buy_reason"] = detail_df["buy_reason"].map(
    lambda x: _buy_reason_labels.get(x, x) if pd.notna(x) else ""
)
detail_df["sell_reason"] = detail_df["sell_reason"].map(
    lambda x: _sell_reason_labels.get(x, x) if pd.notna(x) else ""
)

st.dataframe(
    detail_df[[
        "traded_at", "stock_code", "stock_name", "trade_type",
        "quantity", "price", "total_amount",
        "buy_reason", "sell_reason", "signal_type",
        "profit_loss_pct", "profit_loss_amount",
    ]].rename(columns={
        "traded_at": "시각", "stock_code": "종목코드", "stock_name": "종목명",
        "trade_type": "유형", "quantity": "수량", "price": "가격",
        "total_amount": "체결금액", "buy_reason": "매수사유",
        "sell_reason": "매도사유",
        "signal_type": "시그널", "profit_loss_pct": "수익률(%)",
        "profit_loss_amount": "손익금액",
    }),
    use_container_width=True,
    hide_index=True,
)
