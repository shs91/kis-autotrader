"""개요 — 시스템 상태, 당일 요약, 보유 포트폴리오, 최근 체결 (시장 인지)."""

from __future__ import annotations

from datetime import date

import httpx
import streamlit as st
from lib import db, fmt, market, tables

st.title(f"\U0001f4ca 개요 · {market.label(market.current_market())}")

# ── 시스템 상태 (헬스체크) ───────────────────────────
HEALTH_URL = db.secret_get("HEALTH_URL", "http://localhost:18923/health")


def _fetch_health() -> dict | None:
    try:
        resp = httpx.get(HEALTH_URL, timeout=5.0)
        if resp.status_code == 200:
            return dict(resp.json())
    except Exception:  # noqa: BLE001 — 헬스 실패는 OFFLINE 표시로 처리
        return None
    return None


health = _fetch_health()
c1, c2, c3, c4 = st.columns(4)
if health:
    trading = health.get("components", {}).get("trading", {})
    c1.metric("시스템 상태", str(health.get("status", "unknown")).upper())
    c2.metric("업타임", health.get("uptime", "-"))
    c3.metric("매매 사이클", f"#{trading.get('cycle_count', 0):,}")
    c4.metric("API 호출", f"{trading.get('daily_api_calls', 0):,}")
else:
    c1.metric("시스템 상태", "OFFLINE")
    c2.metric("업타임", "-")
    c3.metric("매매 사이클", "-")
    c4.metric("API 호출", "-")
    st.warning("헬스체크 서버에 연결할 수 없습니다.")

st.divider()

# ── 당일 매매 요약 (trades 파생, 시장 인지) ─────────────
st.subheader("\U0001f4b9 당일 매매 요약")
summary = db.run_query(
    """
    SELECT market, currency,
           COUNT(*) FILTER (WHERE trade_type='BUY')  AS buy_count,
           COUNT(*) FILTER (WHERE trade_type='SELL') AS sell_count,
           COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type='SELL'),0) AS realized_pnl,
           COUNT(*) FILTER (WHERE trade_type='SELL' AND profit_loss_amount>0) AS wins,
           COUNT(*) FILTER (WHERE trade_type='SELL') AS sells
    FROM trades
    WHERE traded_at >= :today AND (:market IS NULL OR market = :market)
    GROUP BY market, currency
    ORDER BY market
    """,
    {"today": date.today(), **market.market_param()},
)

if summary.empty:
    st.info("당일 체결이 없습니다.")
else:
    for _, row in summary.iterrows():
        mk = row["market"]
        st.caption(f"{market.label(mk)}")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("매수", f"{int(row['buy_count'])}건")
        s2.metric("매도", f"{int(row['sell_count'])}건")
        win_rate = (row["wins"] / row["sells"] * 100) if row["sells"] else 0.0
        s3.metric("실현손익", fmt.money(row["realized_pnl"], mk, signed=True),
                  delta=f"승률 {win_rate:.0f}%")
        s4.metric("승률", f"{win_rate:.0f}%")

st.divider()

# ── 보유 포트폴리오 (시장 인지, 네이티브 통화) ───────────
st.subheader("\U0001f4bc 보유 포트폴리오")
portfolio = db.run_query(
    """
    SELECT s.code AS stock_code, s.name AS stock_name, p.market, p.currency,
           p.quantity, p.avg_price, p.current_price,
           CASE WHEN p.avg_price>0
                THEN (p.current_price - p.avg_price)/p.avg_price*100 ELSE 0 END AS profit_rate,
           p.quantity*(p.current_price - p.avg_price) AS profit_loss
    FROM portfolios p JOIN stocks s ON s.id = p.stock_id
    WHERE p.quantity > 0 AND (:market IS NULL OR p.market = :market)
    ORDER BY p.market, profit_loss DESC
    """,
    market.market_param(),
)

if portfolio.empty:
    st.info("보유 종목이 없습니다.")
else:
    pcol1, pcol2 = st.columns(2)
    pcol1.metric("보유 종목", f"{len(portfolio)}개")
    # 평가금액/손익은 통화별로 분리 표기(환산하지 않음)
    by_ccy = portfolio.groupby("market").apply(
        lambda g: (g["quantity"] * g["current_price"]).sum(), include_groups=False
    )
    eval_txt = " · ".join(fmt.money(v, mk) for mk, v in by_ccy.items())
    pcol2.metric("총 평가금액", eval_txt or "-")
    st.dataframe(
        tables.portfolio_display(portfolio, show_market=market.is_all()),
        width="stretch",
        hide_index=True,
    )

st.divider()

# ── 최근 체결 ───────────────────────────────────────
st.subheader("\U0001f4cb 최근 체결 (20건)")
recent = db.run_query(
    """
    SELECT traded_at, market, currency, stock_code, stock_name, trade_type,
           quantity, price, total_amount, buy_reason, sell_reason,
           profit_loss_pct, profit_loss_amount
    FROM trades
    WHERE (:market IS NULL OR market = :market)
    ORDER BY traded_at DESC
    LIMIT 20
    """,
    market.market_param(),
)
if recent.empty:
    st.info("체결 내역이 없습니다.")
else:
    st.dataframe(
        tables.trades_display(recent, show_market=market.is_all()),
        width="stretch",
        hide_index=True,
    )
