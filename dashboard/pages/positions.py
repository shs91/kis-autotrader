"""보유종목 실시간 가격 vs 매수가 비교 차트 페이지."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# db_config(공용 DB URL 리졸버)를 import할 수 있도록 dashboard/ 를 path에 추가
# db_config 내부에서 프로젝트 루트도 sys.path에 추가 → src.* import 가능
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from db_config import resolve_db_url  # noqa: E402 — path 보강 후 import
from positions_data import build_markers_df, build_reference_levels  # noqa: E402

st.set_page_config(page_title="보유종목 차트", page_icon="\U0001f4c8", layout="wide")

# 매매 엔진과 동일한 단일 소스(src.config / KIS_ENV)에서 DB URL을 해석한다.
DB_URL = resolve_db_url()


@st.cache_resource
def get_engine():  # noqa: ANN201
    """SQLAlchemy 엔진 캐시."""
    return create_engine(DB_URL, pool_pre_ping=True)


def load_holdings() -> pd.DataFrame:
    """현재 보유종목(portfolios, 수량>0)을 조회한다."""
    query = text(
        """
        SELECT s.code AS stock_code, s.name AS stock_name, p.market, p.currency,
               p.quantity, p.avg_price, p.current_price, p.peak_price
        FROM portfolios p
        LEFT JOIN stocks s ON s.id = p.stock_id
        WHERE p.quantity > 0
        ORDER BY p.market, s.code
        """
    )
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn)


def load_snapshots(stock_code: str, days: int) -> pd.DataFrame:
    """가격 스냅샷을 지정 일수만큼 조회한다."""
    since = datetime.now(UTC) - timedelta(days=days)
    query = text(
        """
        SELECT captured_at, price
        FROM price_snapshots
        WHERE stock_code = :code AND captured_at >= :since
        ORDER BY captured_at
        """
    )
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"code": stock_code, "since": since})


def load_trade_markers(stock_code: str, days: int) -> pd.DataFrame:
    """체결 내역(매수/매도)을 지정 일수만큼 조회한다."""
    since = datetime.now(UTC) - timedelta(days=days)
    query = text(
        """
        SELECT traded_at, price, trade_type, quantity
        FROM trades
        WHERE stock_code = :code AND traded_at >= :since
        ORDER BY traded_at
        """
    )
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"code": stock_code, "since": since})


# ── 메인 UI ──────────────────────────────────────────────────────────────────

st.title("\U0001f4c8 보유종목 가격 vs 매수가")

holdings = load_holdings()
if holdings.empty:
    st.info("현재 보유 종목이 없습니다.")
    st.stop()

summary = holdings.copy()
summary["손익률%"] = (
    (summary["current_price"] - summary["avg_price"]) / summary["avg_price"] * 100.0
).round(2)
st.dataframe(
    summary[
        ["stock_code", "stock_name", "market", "quantity", "avg_price", "current_price", "손익률%"]
    ],
    use_container_width=True,
)

codes = holdings["stock_code"].tolist()
selected = st.selectbox("종목 선택", codes)
row = holdings[holdings["stock_code"] == selected].iloc[0]
days = st.selectbox("기간(일)", [1, 3, 7], index=2)

snaps = load_snapshots(selected, days)
if snaps.empty:
    st.info("아직 수집된 가격 스냅샷이 없습니다(장 시작 후 수집됩니다).")
    st.stop()

# ── 기준선 파라미터(settings 로드 실패 시 기본값 사용) ──────────────────────
try:
    from src.config import settings  # noqa: PLC0415

    max_loss_rate = settings.trading.max_loss_rate
    take_profit_ratio = settings.strategy.take_profit_ratio
except Exception:  # noqa: BLE001
    max_loss_rate, take_profit_ratio = 0.03, 0.05

levels = build_reference_levels(
    avg_price=float(row["avg_price"]),
    peak_price=float(row["peak_price"]) if pd.notna(row["peak_price"]) else None,
    max_loss_rate=max_loss_rate,
    take_profit_ratio=take_profit_ratio,
)

cur = row["currency"]
unit = "$" if cur == "USD" else "₩"

# ── 차트 레이어 ───────────────────────────────────────────────────────────────

price_line = (
    alt.Chart(snaps)
    .mark_line(color="#2196F3")
    .encode(
        x=alt.X("captured_at:T", title="시각"),
        y=alt.Y("price:Q", title=f"가격({unit})", scale=alt.Scale(zero=False)),
    )
)

rule_rows = pd.DataFrame([{"label": k, "value": v} for k, v in levels.items()])
color_map = {
    "평단가": "#9E9E9E",
    "손절선": "#F44336",
    "익절선": "#4CAF50",
    "peak": "#FF9800",
}
rules = (
    alt.Chart(rule_rows)
    .mark_rule(strokeDash=[4, 4])
    .encode(
        y="value:Q",
        color=alt.Color(
            "label:N",
            scale=alt.Scale(
                domain=list(color_map.keys()), range=list(color_map.values())
            ),
            title="기준선",
        ),
    )
)

markers = build_markers_df(load_trade_markers(selected, days))
layers: list[alt.Chart] = [price_line, rules]
if not markers.empty:
    marker_chart = (
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
    layers.append(marker_chart)

# ── 손익률 메트릭 + 차트 출력 ─────────────────────────────────────────────────

pl_pct = (
    (float(row["current_price"]) - float(row["avg_price"])) / float(row["avg_price"]) * 100.0
)
cur_price_fmt = f"{unit}{float(row['current_price']):,.2f}"
avg_price_fmt = f"{unit}{float(row['avg_price']):,.2f}"
st.metric(
    f"{selected} 손익률",
    f"{pl_pct:+.2f}%",
    delta=f"현재 {cur_price_fmt} / 평단 {avg_price_fmt}",
)
st.altair_chart(
    alt.layer(*layers).resolve_scale(y="shared").interactive(),
    use_container_width=True,
)
