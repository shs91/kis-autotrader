"""리스크 분석 페이지 — MDD, Sharpe, Profit Factor, 연패 추적."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="리스크 분석", page_icon="\U0001f6e1", layout="wide")

DB_URL = st.secrets.get(
    "DATABASE_URL",
    "postgresql://kis_user:kis_password@localhost:5432/kis_trader",
)


@st.cache_resource
def get_engine():  # noqa: ANN201
    return create_engine(DB_URL, pool_pre_ping=True)


# ── 데이터 조회 ──────────────────────────────────


def load_daily_pnl(days: int) -> pd.DataFrame:
    """일별 실현손익을 조회한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT traded_at::date AS trade_date,
               COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS daily_pnl,
               COUNT(*) FILTER (WHERE trade_type = 'SELL') AS sell_count,
               SUM(CASE WHEN trade_type = 'SELL' AND profit_loss_amount > 0 THEN 1 ELSE 0 END) AS win_count,
               SUM(CASE WHEN trade_type = 'SELL' AND profit_loss_amount < 0 THEN 1 ELSE 0 END) AS loss_count,
               COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL' AND profit_loss_amount > 0), 0) AS total_profit,
               COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL' AND profit_loss_amount < 0), 0) AS total_loss
        FROM trades
        WHERE traded_at >= :since
        GROUP BY trade_date
        ORDER BY trade_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_sell_streaks(days: int) -> pd.DataFrame:
    """개별 매도 손익을 시간순으로 조회한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT traded_at, stock_code, stock_name, profit_loss_amount, profit_loss_pct
        FROM trades
        WHERE trade_type = 'SELL' AND profit_loss_amount IS NOT NULL AND traded_at >= :since
        ORDER BY traded_at
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


# ── 페이지 ───────────────────────────────────────

st.title("\U0001f6e1 리스크 분석")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)

pnl_df = load_daily_pnl(days)

if pnl_df.empty:
    st.info("분석 기간에 매도 데이터가 없습니다.")
    st.stop()

pnl_df["trade_date"] = pd.to_datetime(pnl_df["trade_date"])
pnl_df["cumulative_pnl"] = pnl_df["daily_pnl"].cumsum()

# ── MDD 계산 ─────────────────────────────────────

st.subheader("\U0001f4c9 최대 낙폭 (MDD)")

pnl_df["peak"] = pnl_df["cumulative_pnl"].cummax()
pnl_df["drawdown"] = pnl_df["peak"] - pnl_df["cumulative_pnl"]
max_dd_idx = pnl_df["drawdown"].idxmax()
max_dd = int(pnl_df.loc[max_dd_idx, "drawdown"])
peak_val = int(pnl_df.loc[max_dd_idx, "peak"])
mdd_pct = (max_dd / peak_val * 100) if peak_val > 0 else 0.0

mc1, mc2, mc3 = st.columns(3)
mc1.metric("MDD (금액)", f"{max_dd:,}원")
mc2.metric("MDD (%)", f"{mdd_pct:.1f}%")
mc3.metric("피크 누적손익", f"{peak_val:,}원")

cc1, cc2 = st.columns(2)
with cc1:
    st.caption("누적 손익 + 피크")
    chart_data = pnl_df.set_index("trade_date")[["cumulative_pnl", "peak"]]
    chart_data.columns = ["누적손익", "피크"]
    st.line_chart(chart_data)
with cc2:
    st.caption("드로우다운")
    st.area_chart(
        pnl_df.set_index("trade_date")["drawdown"],
        color="#F44336",
    )

st.divider()

# ── Sharpe / Sortino ─────────────────────────────

st.subheader("\U0001f4ca 위험조정수익률")

import math  # noqa: E402

returns = pnl_df["daily_pnl"].tolist()
if len(returns) >= 2:
    avg_return = sum(returns) / len(returns)
    daily_rf = 0.035 / 252
    variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = ((avg_return - daily_rf) / std_dev * math.sqrt(252)) if std_dev > 0 else 0.0

    downside = [r for r in returns if r < 0]
    if len(downside) >= 2:
        down_var = sum(r ** 2 for r in downside) / (len(downside) - 1)
        sortino = ((avg_return - daily_rf) / math.sqrt(down_var) * math.sqrt(252)) if down_var > 0 else 0.0
    else:
        sortino = 0.0

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Sharpe Ratio", f"{sharpe:.2f}")
    sc2.metric("Sortino Ratio", f"{sortino:.2f}")
    sc3.metric("일 평균 손익", f"{avg_return:,.0f}원")
    sc4.metric("일 표준편차", f"{std_dev:,.0f}원")
else:
    st.info("Sharpe/Sortino 계산에 최소 2일 데이터가 필요합니다.")

st.divider()

# ── Profit Factor ────────────────────────────────

st.subheader("\U0001f4b0 Profit Factor")

total_profit = int(pnl_df["total_profit"].sum())
total_loss = abs(int(pnl_df["total_loss"].sum()))
total_wins = int(pnl_df["win_count"].sum())
total_losses = int(pnl_df["loss_count"].sum())
total_sells = int(pnl_df["sell_count"].sum())

pf = (total_profit / total_loss) if total_loss > 0 else 0.0
win_rate = (total_wins / total_sells * 100) if total_sells > 0 else 0.0
avg_win = (total_profit / total_wins) if total_wins > 0 else 0
avg_loss = (total_loss / total_losses) if total_losses > 0 else 0
payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0

pc1, pc2, pc3, pc4, pc5 = st.columns(5)
pc1.metric("Profit Factor", f"{pf:.2f}")
pc2.metric("승률", f"{win_rate:.0f}%")
pc3.metric("평균 수익", f"{avg_win:,.0f}원")
pc4.metric("평균 손실", f"{avg_loss:,.0f}원")
pc5.metric("Payoff Ratio", f"{payoff:.2f}")

st.divider()

# ── 연속 손실/수익 ───────────────────────────────

st.subheader("\U0001f525 연속 손실/수익 추적")

sell_df = load_sell_streaks(days)

if not sell_df.empty:
    max_win_streak = 0
    max_loss_streak = 0
    current_win = 0
    current_loss = 0

    for _, row in sell_df.iterrows():
        pnl = row["profit_loss_amount"]
        if pnl > 0:
            current_win += 1
            current_loss = 0
            max_win_streak = max(max_win_streak, current_win)
        elif pnl < 0:
            current_loss += 1
            current_win = 0
            max_loss_streak = max(max_loss_streak, current_loss)
        else:
            current_win = 0
            current_loss = 0

    lc1, lc2, lc3, lc4 = st.columns(4)
    lc1.metric("최대 연승", f"{max_win_streak}회")
    lc2.metric("최대 연패", f"{max_loss_streak}회")
    lc3.metric("현재 연승", f"{current_win}회")
    lc4.metric("현재 연패", f"{current_loss}회")
else:
    st.info("매도 데이터가 없습니다.")

st.divider()

# ── 일별 손익 분포 ───────────────────────────────

st.subheader("\U0001f4ca 일별 손익 분포")

st.bar_chart(
    pnl_df.set_index("trade_date")["daily_pnl"],
    color="#4CAF50",
)

# ── 자동 갱신 ────────────────────────────────────

st.divider()
auto_refresh = st.checkbox("30초 자동 갱신", value=False)
if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()
