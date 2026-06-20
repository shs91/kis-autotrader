"""매매 — 체결 분석(구체화된 사유), 종목별/사유별 손익, 시맨틱 차트 (시장 인지)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from lib import charts, db, fmt, market, reasons, tables

st.title(f"\U0001f4b9 매매 · {market.label(market.current_market())}")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)
since = date.today() - timedelta(days=days)
# 시장 필터: 정적 술어 (:market IS NULL OR <col> = :market) + 바인드 파라미터
params = {"since": since, **market.market_param()}


def _market_label(code: str) -> str:
    return {"KRX": "🇰🇷 한국", "US": "🇺🇸 미국"}.get(code, code)


# ── KPI (시장별) ────────────────────────────────────
kpi = db.run_query(
    """
    SELECT market,
           COUNT(*) FILTER (WHERE trade_type='BUY')  AS buys,
           COUNT(*) FILTER (WHERE trade_type='SELL') AS sells,
           COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type='SELL'),0) AS pnl,
           COUNT(*) FILTER (WHERE trade_type='SELL' AND profit_loss_amount>0) AS wins,
           AVG(profit_loss_pct) FILTER (WHERE trade_type='SELL') AS avg_pct
    FROM trades
    WHERE traded_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY market ORDER BY market
    """,
    params,
)
if kpi.empty:
    st.info("선택 기간에 체결 데이터가 없습니다.")
    st.stop()

for _, row in kpi.iterrows():
    mk = row["market"]
    st.caption(_market_label(mk))
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("매수", f"{int(row['buys'])}건")
    k2.metric("매도", f"{int(row['sells'])}건")
    k3.metric("실현손익", fmt.money(row["pnl"], mk, signed=True))
    win_rate = (row["wins"] / row["sells"] * 100) if row["sells"] else 0.0
    k4.metric("승률", f"{win_rate:.0f}%")
    k5.metric("평균 수익률", fmt.pct(row["avg_pct"]) if pd.notna(row["avg_pct"]) else "-")

st.divider()

# ── 일별 매매 추이 (건수: 합산 / 손익: 시장별) ──────────
st.subheader("\U0001f4c5 일별 매매 추이")
daily = db.run_query(
    """
    SELECT traded_at::date AS d, market,
           COUNT(*) FILTER (WHERE trade_type='BUY')  AS 매수,
           COUNT(*) FILTER (WHERE trade_type='SELL') AS 매도,
           COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type='SELL'),0) AS pnl
    FROM trades
    WHERE traded_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY d, market ORDER BY d
    """,
    params,
)
counts = daily.groupby("d", as_index=False)[["매수", "매도"]].sum().melt(
    "d", var_name="구분", value_name="건수"
)
st.caption("일별 매수/매도 건수")
charts.grouped_count_bar(
    counts, "d", "구분", "건수", color_scale={"매수": charts.POS, "매도": charts.NEG}
)
st.caption("일별 실현손익")
for mk, sub in daily.groupby("market"):
    if market.is_all():
        st.markdown(f"**{_market_label(mk)}**")
    charts.pnl_bar_time(sub.rename(columns={"d": "date"}), "date", "pnl",
                        money_fmt=",.2f" if mk == "US" else ",.0f")

st.divider()

# ── 종목별 손익 ─────────────────────────────────────
st.subheader("\U0001f3af 종목별 손익")
stock_pnl = db.run_query(
    """
    SELECT stock_code, stock_name, market,
           COUNT(*) FILTER (WHERE trade_type='BUY')  AS buy_count,
           COUNT(*) FILTER (WHERE trade_type='SELL') AS sell_count,
           COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type='SELL'),0) AS total_pnl,
           AVG(profit_loss_pct) FILTER (WHERE trade_type='SELL') AS avg_pct
    FROM trades
    WHERE traded_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY stock_code, stock_name, market ORDER BY market, total_pnl DESC
    """,
    params,
)
if not stock_pnl.empty:
    disp = pd.DataFrame(index=stock_pnl.index)
    if market.is_all():
        disp["시장"] = stock_pnl["market"].map({"KRX": "🇰🇷", "US": "🇺🇸"})
    disp["종목"] = stock_pnl["stock_name"].astype(str) + " (" + stock_pnl["stock_code"] + ")"
    disp["매수"] = stock_pnl["buy_count"]
    disp["매도"] = stock_pnl["sell_count"]
    disp["실현손익"] = [
        fmt.money(v, mk, signed=True)
        for v, mk in zip(stock_pnl["total_pnl"], stock_pnl["market"], strict=False)
    ]
    disp["평균수익률"] = [fmt.pct(v) if pd.notna(v) else "-" for v in stock_pnl["avg_pct"]]
    st.dataframe(disp, width="stretch", hide_index=True)

st.divider()

# ── 매수/매도 사유 분포 ─────────────────────────────
st.subheader("\U0001f4a1 매수 사유 분포")
buy_reason = db.run_query(
    """
    SELECT buy_reason, COUNT(*) AS 건수
    FROM trades
    WHERE trade_type='BUY' AND traded_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY buy_reason ORDER BY 건수 DESC
    """,
    params,
)
if not buy_reason.empty:
    buy_reason["사유"] = buy_reason["buy_reason"].map(reasons.buy_label)
    st.bar_chart(buy_reason.set_index("사유")["건수"], color=charts.NEUTRAL)

st.subheader("\U0001f6a8 매도 사유 분석")
sell_reason = db.run_query(
    """
    SELECT sell_reason, market, COUNT(*) AS cnt,
           COALESCE(SUM(profit_loss_amount),0) AS total_pnl,
           AVG(profit_loss_pct) AS avg_pct
    FROM trades
    WHERE trade_type='SELL' AND sell_reason IS NOT NULL
      AND traded_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY sell_reason, market ORDER BY market, cnt DESC
    """,
    params,
)
if not sell_reason.empty:
    sell_reason["사유"] = sell_reason["sell_reason"].map(reasons.sell_label)
    st.caption("사유별 손익 (이익=초록 / 손실=빨강)")
    for mk, sub in sell_reason.groupby("market"):
        if market.is_all():
            st.markdown(f"**{_market_label(mk)}**")
        charts.pnl_bar_category(sub, "사유", "total_pnl",
                                money_fmt=",.2f" if mk == "US" else ",.0f")
    disp = pd.DataFrame({
        "매도사유": sell_reason["사유"],
        "건수": sell_reason["cnt"],
        "총 손익": [
            fmt.money(v, mk, signed=True)
            for v, mk in zip(sell_reason["total_pnl"], sell_reason["market"], strict=False)
        ],
        "평균수익률": [fmt.pct(v) if pd.notna(v) else "-" for v in sell_reason["avg_pct"]],
    })
    st.dataframe(disp, width="stretch", hide_index=True)

st.divider()

# ── 체결 내역 상세 (구체화된 사유: 신뢰도·시그널) ─────────
st.subheader("\U0001f4cb 체결 내역 상세")
st.caption("신뢰도는 진입 시점 직전 신호의 confidence (참고용). 전략별 투표는 '신호' 페이지 참조.")
detail = db.run_query(
    """
    SELECT t.traded_at, t.market, t.currency, t.stock_code, t.stock_name, t.trade_type,
           t.quantity, t.price, t.total_amount, t.buy_reason, t.sell_reason,
           t.profit_loss_pct, t.profit_loss_amount, sig.confidence
    FROM trades t
    LEFT JOIN LATERAL (
        SELECT confidence FROM signals s
        WHERE s.stock_code = t.stock_code AND s.detected_at <= t.traded_at
        ORDER BY s.detected_at DESC LIMIT 1
    ) sig ON true
    WHERE t.traded_at >= :since AND (:market IS NULL OR t.market = :market)
    ORDER BY t.traded_at DESC LIMIT 200
    """,
    params,
)
if not detail.empty:
    st.dataframe(
        tables.trades_display(detail, show_market=market.is_all()),
        width="stretch",
        hide_index=True,
    )
