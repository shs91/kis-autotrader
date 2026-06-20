"""리스크 — MDD/Sharpe/Profit Factor/연패 (시장별·네이티브 통화·시맨틱 차트)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from lib import charts, db, fmt, market

st.title(f"\U0001f6e1 리스크 · {market.label(market.current_market())}")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)
since = date.today() - timedelta(days=days)
params = {"since": since, **market.market_param()}

daily = db.run_query(
    """
    SELECT traded_at::date AS d, market,
           COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type='SELL'),0) AS daily_pnl,
           COUNT(*) FILTER (WHERE trade_type='SELL') AS sells,
           COUNT(*) FILTER (WHERE trade_type='SELL' AND profit_loss_amount>0) AS wins,
           COUNT(*) FILTER (WHERE trade_type='SELL' AND profit_loss_amount<0) AS losses,
           COALESCE(SUM(profit_loss_amount) FILTER
                    (WHERE trade_type='SELL' AND profit_loss_amount>0),0) AS gross_profit,
           COALESCE(SUM(profit_loss_amount) FILTER
                    (WHERE trade_type='SELL' AND profit_loss_amount<0),0) AS gross_loss
    FROM trades
    WHERE traded_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY d, market ORDER BY d
    """,
    params,
)
sells = db.run_query(
    """
    SELECT traded_at, market, profit_loss_amount
    FROM trades
    WHERE trade_type='SELL' AND profit_loss_amount IS NOT NULL
      AND traded_at >= :since AND (:market IS NULL OR market = :market)
    ORDER BY traded_at
    """,
    params,
)

if daily.empty:
    st.info("선택 기간에 매도 데이터가 없습니다.")
    st.stop()


def _max_streak(values: list[float], positive: bool) -> tuple[int, int]:
    """최대 연속/현재 연속 (positive=연승, else 연패)."""
    best = cur = 0
    for v in values:
        hit = v > 0 if positive else v < 0
        cur = cur + 1 if hit else 0
        best = max(best, cur)
    return best, cur


def render_market(mk: str, dm: pd.DataFrame, sm: pd.DataFrame) -> None:
    money_fmt = ",.2f" if mk == "US" else ",.0f"
    dm = dm.sort_values("d").copy()
    dm["cum"] = dm["daily_pnl"].cumsum()
    dm["peak"] = dm["cum"].cummax()
    dm["dd"] = dm["peak"] - dm["cum"]

    # MDD
    max_dd = float(dm["dd"].max())
    peak_at_dd = float(dm.loc[dm["dd"].idxmax(), "peak"]) if max_dd > 0 else 0.0
    mdd_pct = (max_dd / peak_at_dd * 100) if peak_at_dd > 0 else 0.0

    # Sharpe / Sortino (일 손익 기준)
    returns = dm["daily_pnl"].tolist()
    sharpe = sortino = 0.0
    if len(returns) >= 2:
        avg = sum(returns) / len(returns)
        rf = 0.035 / 252
        var = sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        sharpe = ((avg - rf) / std * math.sqrt(252)) if std > 0 else 0.0
        downside = [r for r in returns if r < 0]
        if len(downside) >= 2:
            dvar = sum(r**2 for r in downside) / (len(downside) - 1)
            sortino = ((avg - rf) / math.sqrt(dvar) * math.sqrt(252)) if dvar > 0 else 0.0

    # Profit Factor
    gp = float(dm["gross_profit"].sum())
    gl = abs(float(dm["gross_loss"].sum()))
    wins = int(dm["wins"].sum())
    losses = int(dm["losses"].sum())
    total_sells = int(dm["sells"].sum())
    pf = (gp / gl) if gl > 0 else 0.0
    win_rate = (wins / total_sells * 100) if total_sells else 0.0
    payoff = ((gp / wins) / (gl / losses)) if wins and losses and gl > 0 else 0.0

    # 연속 손익
    streak_vals = sm["profit_loss_amount"].tolist()
    max_win, cur_win = _max_streak(streak_vals, positive=True)
    max_loss, cur_loss = _max_streak(streak_vals, positive=False)

    if market.is_all():
        st.markdown(f"### {market.label(mk)}")

    st.markdown("**\U0001f4c9 최대 낙폭 (MDD)**")
    r1, r2, r3 = st.columns(3)
    r1.metric("MDD (금액)", fmt.money(max_dd, mk))
    r2.metric("MDD (%)", f"{mdd_pct:.1f}%")
    r3.metric("피크 누적손익", fmt.money(peak_at_dd, mk))
    cc1, cc2 = st.columns(2)
    with cc1:
        st.caption("누적 손익")
        charts.cumulative_line(dm, "d", "cum", money_fmt=money_fmt)
    with cc2:
        st.caption("일별 손익")
        charts.pnl_bar_time(dm, "d", "daily_pnl", money_fmt=money_fmt)

    st.markdown("**\U0001f4ca 위험조정수익률 / Profit Factor**")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Sharpe", f"{sharpe:.2f}")
    s2.metric("Sortino", f"{sortino:.2f}")
    s3.metric("Profit Factor", f"{pf:.2f}")
    s4.metric("승률", f"{win_rate:.0f}%")
    s5.metric("Payoff", f"{payoff:.2f}")

    st.markdown("**\U0001f525 연속 손익**")
    l1, l2, l3, l4 = st.columns(4)
    l1.metric("최대 연승", f"{max_win}회")
    l2.metric("최대 연패", f"{max_loss}회")
    l3.metric("현재 연승", f"{cur_win}회")
    l4.metric("현재 연패", f"{cur_loss}회")
    st.divider()


for mk in daily["market"].unique():
    render_market(mk, daily[daily["market"] == mk], sells[sells["market"] == mk])
