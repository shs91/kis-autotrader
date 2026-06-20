"""보유 상세 — 보유종목 가격 vs 매수가 비교(기준선·체결마커, Altair, 시장 인지)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from lib import db, fmt, market
from positions_data import build_markers_df, build_reference_levels

st.title(f"\U0001f4cd 보유 상세 · {market.label(market.current_market())}")

holdings = db.run_query(
    """
    SELECT s.code AS stock_code, s.name AS stock_name, p.market, p.currency,
           p.quantity, p.avg_price, p.current_price, p.peak_price
    FROM portfolios p LEFT JOIN stocks s ON s.id = p.stock_id
    WHERE p.quantity > 0 AND (:market IS NULL OR p.market = :market)
    ORDER BY p.market, s.code
    """,
    market.market_param(),
)
if holdings.empty:
    st.info("현재 보유 종목이 없습니다.")
    st.stop()

# ── 요약 표 (네이티브 통화) ─────────────────────────
summary = pd.DataFrame(index=holdings.index)
summary["시장"] = holdings["market"].map({"KRX": "🇰🇷", "US": "🇺🇸"}).fillna(holdings["market"])
summary["종목"] = holdings["stock_name"].astype(str) + " (" + holdings["stock_code"] + ")"
summary["수량"] = [fmt.num(q) for q in holdings["quantity"]]
summary["평단가"] = [
    fmt.money(p, mk) for p, mk in zip(holdings["avg_price"], holdings["market"], strict=False)
]
summary["현재가"] = [
    fmt.money(p, mk) for p, mk in zip(holdings["current_price"], holdings["market"], strict=False)
]
summary["손익률"] = [
    fmt.pct((c - a) / a * 100 if a else 0)
    for a, c in zip(holdings["avg_price"], holdings["current_price"], strict=False)
]
st.dataframe(summary, width="stretch", hide_index=True)

# ── 종목 선택 + 기간 ────────────────────────────────
codes = holdings["stock_code"].tolist()
labels = dict(zip(holdings["stock_code"], holdings["stock_name"], strict=False))
selected = st.selectbox("종목 선택", codes, format_func=lambda c: f"{labels.get(c, c)} ({c})")
row = holdings[holdings["stock_code"] == selected].iloc[0]
days = st.selectbox("기간(일)", [1, 3, 7], index=2)
since = datetime.now(UTC) - timedelta(days=days)

snaps = db.run_query(
    """
    SELECT captured_at, price FROM price_snapshots
    WHERE stock_code = :code AND captured_at >= :since ORDER BY captured_at
    """,
    {"code": selected, "since": since},
)
if snaps.empty:
    st.info("아직 수집된 가격 스냅샷이 없습니다(장 시작 후 수집됩니다).")
    st.stop()
snaps["price"] = snaps["price"].astype(float)

# ── 기준선(settings 실패 시 기본값) ─────────────────
try:
    from src.config import settings

    max_loss_rate = settings.trading.max_loss_rate
    take_profit_ratio = settings.strategy.take_profit_ratio
except Exception:  # noqa: BLE001 — 설정 로드 실패 시 기본값
    max_loss_rate, take_profit_ratio = 0.03, 0.05

levels = build_reference_levels(
    avg_price=float(row["avg_price"]),
    peak_price=float(row["peak_price"]) if pd.notna(row["peak_price"]) else None,
    max_loss_rate=max_loss_rate,
    take_profit_ratio=take_profit_ratio,
)

mk = row["market"]
unit = "$" if row["currency"] == "USD" else "₩"

# ── 손익률 메트릭 ──────────────────────────────────
pl_pct = (float(row["current_price"]) - float(row["avg_price"])) / float(row["avg_price"]) * 100.0
st.metric(
    f"{labels.get(selected, selected)} 손익률",
    fmt.pct(pl_pct),
    delta=f"현재 {fmt.money(row['current_price'], mk)} / 평단 {fmt.money(row['avg_price'], mk)}",
)

# ── 차트 (가격선 + 기준선 + 체결마커) ────────────────
price_line = (
    alt.Chart(snaps)
    .mark_line(color="#2196F3")
    .encode(
        x=alt.X("captured_at:T", title="시각"),
        y=alt.Y("price:Q", title=f"가격({unit})", scale=alt.Scale(zero=False)),
    )
)
rule_rows = pd.DataFrame([{"label": k, "value": v} for k, v in levels.items()])
color_map = {"평단가": "#9E9E9E", "손절선": "#F44336", "익절선": "#4CAF50", "peak": "#FF9800"}
rules = (
    alt.Chart(rule_rows)
    .mark_rule(strokeDash=[4, 4])
    .encode(
        y="value:Q",
        color=alt.Color(
            "label:N",
            scale=alt.Scale(domain=list(color_map), range=list(color_map.values())),
            title="기준선",
        ),
    )
)
markers = build_markers_df(
    db.run_query(
        """
        SELECT traded_at, price, trade_type, quantity FROM trades
        WHERE stock_code = :code AND traded_at >= :since ORDER BY traded_at
        """,
        {"code": selected, "since": since},
    ).assign(price=lambda d: d["price"].astype(float) if not d.empty else d.get("price"))
)
layers: list[alt.Chart] = [price_line, rules]
if not markers.empty:
    layers.append(
        alt.Chart(markers)
        .mark_point(size=120, filled=True)
        .encode(
            x="traded_at:T",
            y="price:Q",
            shape=alt.Shape(
                "trade_type:N",
                scale=alt.Scale(domain=["BUY", "SELL"], range=["triangle-up", "triangle-down"]),
                title="체결",
            ),
            color=alt.Color(
                "trade_type:N",
                scale=alt.Scale(domain=["BUY", "SELL"], range=["#E53935", "#1E88E5"]),
            ),
            tooltip=["traded_at:T", "trade_type:N", "marker:N", "price:Q", "quantity:Q"],
        )
    )
st.altair_chart(
    alt.layer(*layers).resolve_scale(y="shared").interactive(), width="stretch"
)
