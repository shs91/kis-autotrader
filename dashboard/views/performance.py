"""성과 — 누적 실현손익·승률 추이·스크리닝 전환율 (시장별·시맨틱 차트)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from lib import charts, db, fmt, market

st.title(f"\U0001f4c8 성과 · {market.label(market.current_market())}")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)
since = date.today() - timedelta(days=days)
params = {"since": since, **market.market_param()}


def _mlabel(mk: str) -> str:
    return {"KRX": "🇰🇷 한국", "US": "🇺🇸 미국"}.get(mk, mk)


# ── 누적 실현손익 (시장별) ──────────────────────────
st.subheader("\U0001f4c8 누적 실현손익")
daily = db.run_query(
    """
    SELECT traded_at::date AS d, market,
           COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type='SELL'),0) AS daily_pnl,
           COUNT(*) FILTER (WHERE trade_type='SELL') AS sells,
           COUNT(*) FILTER (WHERE trade_type='SELL' AND profit_loss_amount>0) AS wins
    FROM trades
    WHERE traded_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY d, market ORDER BY d
    """,
    params,
)
if daily.empty:
    st.info("선택 기간에 손익 데이터가 없습니다.")
    st.stop()

for mk in daily["market"].unique():
    dm = daily[daily["market"] == mk].sort_values("d").copy()
    money_fmt = ",.2f" if mk == "US" else ",.0f"
    dm["cum"] = dm["daily_pnl"].cumsum()
    if market.is_all():
        st.markdown(f"**{_mlabel(mk)}**")
    total_pnl = float(dm["daily_pnl"].sum())
    trade_days = int((dm["daily_pnl"] != 0).sum())
    kc1, kc2, kc3 = st.columns(3)
    kc1.metric("총 실현손익", fmt.money(total_pnl, mk, signed=True))
    kc2.metric("거래일 수", f"{trade_days}일")
    kc3.metric("일 평균", fmt.money(total_pnl / trade_days if trade_days else 0, mk, signed=True))
    cc1, cc2 = st.columns(2)
    with cc1:
        st.caption("일별 실현손익")
        charts.pnl_bar_time(dm, "d", "daily_pnl", money_fmt=money_fmt)
    with cc2:
        st.caption("누적 실현손익")
        charts.cumulative_line(dm, "d", "cum", money_fmt=money_fmt)

st.divider()

# ── 일별 승률 추이 (시장별) ─────────────────────────
st.subheader("\U0001f4ca 일별 승률 추이")
winrate = daily.copy()
winrate["승률"] = (winrate["wins"] / winrate["sells"].replace(0, pd.NA) * 100).fillna(0)
pivot = winrate.pivot_table(index="d", columns="market", values="승률", fill_value=0)
pivot = pivot.rename(columns={c: _mlabel(c) for c in pivot.columns})
st.line_chart(pivot)

st.divider()

# ── 스크리닝 전환율 (시장별) ────────────────────────
st.subheader("\U0001f50d 스크리닝 전환율")
screen = db.run_query(
    """
    SELECT screened_at::date AS d, market,
           COUNT(*) AS total,
           SUM(CASE WHEN converted_to_trade THEN 1 ELSE 0 END) AS conv
    FROM screening_results
    WHERE screened_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY d, market ORDER BY d
    """,
    params,
)
if screen.empty:
    st.info("스크리닝 데이터가 없습니다.")
else:
    agg = screen.groupby("market").agg(total=("total", "sum"), conv=("conv", "sum"))
    cols = st.columns(max(len(agg), 1))
    for col, (mk, r) in zip(cols, agg.iterrows(), strict=False):
        rate = (r["conv"] / r["total"] * 100) if r["total"] else 0
        col.metric(
            f"{_mlabel(mk)} 전환율", f"{rate:.1f}%",
            delta=f"{int(r['conv'])} / {int(r['total'])}건",
        )
    screen["전환율"] = (screen["conv"] / screen["total"].replace(0, pd.NA) * 100).fillna(0)
    conv_pivot = screen.pivot_table(index="d", columns="market", values="전환율", fill_value=0)
    conv_pivot = conv_pivot.rename(columns={c: _mlabel(c) for c in conv_pivot.columns})
    st.caption("일별 전환율 (%)")
    st.line_chart(conv_pivot)
