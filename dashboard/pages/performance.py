"""성과 분석 페이지 — trades/daily_summary 기반 고도화."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="성과 분석", page_icon="\U0001f4ca", layout="wide")

DB_URL = st.secrets.get(
    "DATABASE_URL",
    "postgresql://kis_user:kis_password@localhost:5432/kis_trader",
)


@st.cache_resource
def get_engine():  # noqa: ANN201
    return create_engine(DB_URL, pool_pre_ping=True)


# ── 데이터 조회 ──────────────────────────────────


def load_daily_summary(days: int) -> pd.DataFrame:
    """daily_summary 테이블에서 일일 요약을 조회한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT report_date, total_buy_count, total_sell_count,
               total_profit_loss, win_rate,
               stop_loss_count, take_profit_count, strategy_sell_count,
               screening_count, screening_conversion_count,
               error_count, cycle_count
        FROM daily_summary
        WHERE report_date >= :since
        ORDER BY report_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_cumulative_pnl(days: int) -> pd.DataFrame:
    """trades 테이블에서 일별 실현손익을 집계한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT traded_at::date AS trade_date,
               COALESCE(SUM(profit_loss_amount) FILTER (WHERE trade_type = 'SELL'), 0) AS daily_pnl
        FROM trades
        WHERE traded_at >= :since
        GROUP BY trade_date
        ORDER BY trade_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_daily_performance(days: int) -> pd.DataFrame:
    """기존 daily_performances 테이블 (폴백용)."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT date, total_profit_loss, profit_rate, execution_count
        FROM daily_performances
        WHERE date >= :since
        ORDER BY date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_screening_stats(days: int) -> pd.DataFrame:
    """일별 스크리닝 전환율을 집계한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT screened_at::date AS screen_date,
               COUNT(*) AS total_screened,
               SUM(CASE WHEN converted_to_trade THEN 1 ELSE 0 END) AS converted,
               ROUND(
                   SUM(CASE WHEN converted_to_trade THEN 1 ELSE 0 END)::numeric
                   / NULLIF(COUNT(*), 0) * 100, 1
               ) AS conversion_rate
        FROM screening_results
        WHERE screened_at >= :since
        GROUP BY screen_date
        ORDER BY screen_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_risk_stats(days: int) -> pd.DataFrame:
    """매도 사유별 수익률 분포를 조회한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT sell_reason,
               COUNT(*) AS count,
               ROUND(AVG(profit_loss_pct)::numeric, 2) AS avg_pct,
               ROUND(MIN(profit_loss_pct)::numeric, 2) AS min_pct,
               ROUND(MAX(profit_loss_pct)::numeric, 2) AS max_pct,
               COALESCE(SUM(profit_loss_amount), 0) AS total_pnl
        FROM trades
        WHERE trade_type = 'SELL'
          AND sell_reason IS NOT NULL
          AND traded_at >= :since
        GROUP BY sell_reason
        ORDER BY count DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_error_trend(days: int) -> pd.DataFrame:
    """일별 에러 발생 추이를 조회한다."""
    since = date.today() - timedelta(days=days)
    query = text("""
        SELECT recorded_at::date AS error_date,
               COUNT(*) AS error_count
        FROM system_metrics
        WHERE metric_type = 'ERROR'
          AND recorded_at >= :since
        GROUP BY error_date
        ORDER BY error_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


# ── 페이지 ───────────────────────────────────────

st.title("\U0001f4ca 성과 분석")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)

# ── 누적 손익 곡선 (trades 기반) ──────────────────

st.subheader("\U0001f4c8 누적 실현손익")

cum_df = load_cumulative_pnl(days)

if cum_df.empty:
    # 폴백: 기존 daily_performances
    perf_df = load_daily_performance(days)
    if not perf_df.empty:
        perf_df["date"] = pd.to_datetime(perf_df["date"])
        perf_df["cumulative_pl"] = perf_df["total_profit_loss"].cumsum()

        st.line_chart(perf_df.set_index("date")["cumulative_pl"], color="#2196F3")
        st.caption("(daily_performances 기반 — trades 데이터 적재 후 자동 전환)")
    else:
        st.info("손익 데이터가 없습니다.")
else:
    cum_df["trade_date"] = pd.to_datetime(cum_df["trade_date"])
    cum_df["cumulative_pnl"] = cum_df["daily_pnl"].cumsum()
    total_pnl = int(cum_df["daily_pnl"].sum())

    kc1, kc2, kc3 = st.columns(3)
    kc1.metric("총 실현손익", f"{total_pnl:,}원")
    kc2.metric("거래일 수", f"{len(cum_df)}일")
    avg_daily = total_pnl / len(cum_df) if len(cum_df) > 0 else 0
    kc3.metric("일 평균 손익", f"{avg_daily:,.0f}원")

    cc1, cc2 = st.columns(2)
    with cc1:
        st.caption("일별 실현손익")
        st.bar_chart(cum_df.set_index("trade_date")["daily_pnl"], color="#4CAF50")
    with cc2:
        st.caption("누적 실현손익")
        st.line_chart(
            cum_df.set_index("trade_date")["cumulative_pnl"],
            color="#2196F3",
        )

st.divider()

# ── 일일 요약 추이 (daily_summary) ────────────────

st.subheader("\U0001f4ca 일일 요약 추이")

summary_df = load_daily_summary(days)

if summary_df.empty:
    st.info("daily_summary 데이터가 없습니다. 장 마감 후 자동 집계됩니다.")
else:
    summary_df["report_date"] = pd.to_datetime(summary_df["report_date"])

    # 기간 KPI
    sk1, sk2, sk3, sk4 = st.columns(4)
    sk1.metric("총 매수", f"{summary_df['total_buy_count'].sum()}건")
    sk2.metric("총 매도", f"{summary_df['total_sell_count'].sum()}건")
    sk3.metric("평균 승률",
               f"{summary_df['win_rate'].mean() * 100:.0f}%")
    sk4.metric("총 사이클", f"{summary_df['cycle_count'].sum()}")

    # 차트: 매매 건수 + 손익
    sc1, sc2 = st.columns(2)

    with sc1:
        st.caption("일별 매수/매도 건수")
        trade_counts = summary_df.set_index("report_date")[
            ["total_buy_count", "total_sell_count"]
        ]
        trade_counts.columns = ["매수", "매도"]
        st.bar_chart(trade_counts)

    with sc2:
        st.caption("일별 승률 추이")
        win_rate_series = (summary_df.set_index("report_date")["win_rate"] * 100)
        win_rate_series.name = "승률(%)"
        st.line_chart(win_rate_series, color="#FF9800")

    # 주간별 집계
    summary_df["week"] = summary_df["report_date"].dt.isocalendar().week.astype(int)
    summary_df["year"] = summary_df["report_date"].dt.isocalendar().year.astype(int)
    weekly = summary_df.groupby(["year", "week"]).agg(
        total_pl=("total_profit_loss", "sum"),
        trades=("total_buy_count", "sum"),
        sells=("total_sell_count", "sum"),
        days=("report_date", "count"),
    ).reset_index()
    weekly["label"] = weekly.apply(
        lambda r: f"{int(r['year'])}-W{int(r['week']):02d}", axis=1,
    )

    st.caption("주간별 실현손익")
    st.bar_chart(weekly.set_index("label")["total_pl"], color="#4CAF50")

st.divider()

# ── 리스크 분석 ──────────────────────────────────

st.subheader("\U0001f6a8 리스크 분석")

risk_df = load_risk_stats(days)

if risk_df.empty:
    st.info("매도 데이터가 없습니다.")
else:
    reason_labels = {
        "STOP_LOSS": "손절",
        "TAKE_PROFIT": "익절",
        "STRATEGY": "전략매도",
        "MANUAL": "수동",
    }
    risk_df["label"] = risk_df["sell_reason"].map(
        lambda x: reason_labels.get(x, x)
    )

    rc1, rc2 = st.columns(2)

    with rc1:
        st.caption("사유별 평균 수익률 (%)")
        st.bar_chart(risk_df.set_index("label")["avg_pct"], color="#FF5722")

    with rc2:
        st.caption("사유별 건수")
        st.bar_chart(risk_df.set_index("label")["count"])

    st.dataframe(
        risk_df[["label", "count", "avg_pct", "min_pct", "max_pct", "total_pnl"]].rename(
            columns={
                "label": "매도사유", "count": "건수",
                "avg_pct": "평균(%)", "min_pct": "최소(%)",
                "max_pct": "최대(%)", "total_pnl": "총 손익",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── 스크리닝 전환율 ──────────────────────────────

st.subheader("\U0001f50d 스크리닝 전환율 추이")

screen_df = load_screening_stats(days)

if screen_df.empty:
    st.info("스크리닝 데이터가 없습니다.")
else:
    screen_df["screen_date"] = pd.to_datetime(screen_df["screen_date"])

    total_screened = screen_df["total_screened"].sum()
    total_converted = screen_df["converted"].sum()
    overall_rate = (
        total_converted / total_screened * 100
    ) if total_screened > 0 else 0

    sk1, sk2, sk3 = st.columns(3)
    sk1.metric("총 스크리닝", f"{total_screened}건")
    sk2.metric("전환", f"{total_converted}건")
    sk3.metric("전환율", f"{overall_rate:.1f}%")

    sc1, sc2 = st.columns(2)
    with sc1:
        st.caption("일별 스크리닝/전환 건수")
        chart = screen_df.set_index("screen_date")[
            ["total_screened", "converted"]
        ]
        chart.columns = ["스크리닝", "전환"]
        st.bar_chart(chart)
    with sc2:
        st.caption("일별 전환율 (%)")
        st.line_chart(
            screen_df.set_index("screen_date")["conversion_rate"],
            color="#9C27B0",
        )

st.divider()

# ── 에러 추이 ────────────────────────────────────

st.subheader("\U000026a0 에러 발생 추이")

error_df = load_error_trend(days)

if error_df.empty:
    st.info("에러 데이터가 없습니다.")
else:
    error_df["error_date"] = pd.to_datetime(error_df["error_date"])
    st.bar_chart(
        error_df.set_index("error_date")["error_count"],
        color="#F44336",
    )
    st.metric("총 에러", f"{error_df['error_count'].sum()}건")
