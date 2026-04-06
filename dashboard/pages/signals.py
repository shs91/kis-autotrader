"""시그널 분석 페이지 — signals 테이블 기반."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="시그널 분석", page_icon="\U0001f4e1", layout="wide")

DB_URL = st.secrets.get(
    "DATABASE_URL",
    "postgresql://kis_user:kis_password@localhost:5432/kis_trader",
)


@st.cache_resource
def get_engine():  # noqa: ANN201
    return create_engine(DB_URL, pool_pre_ping=True)


# ── 데이터 조회 ──────────────────────────────────


def load_signals(since: date) -> pd.DataFrame:
    """기간 내 시그널을 조회한다."""
    query = text("""
        SELECT detected_at, stock_code, stock_name,
               signal_type, confidence, action_taken
        FROM signals
        WHERE detected_at >= :since
        ORDER BY detected_at DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_signal_type_stats(since: date) -> pd.DataFrame:
    """시그널 유형별 통계를 집계한다."""
    query = text("""
        SELECT signal_type,
               COUNT(*) AS total,
               SUM(CASE WHEN action_taken THEN 1 ELSE 0 END) AS acted,
               ROUND(AVG(confidence)::numeric, 3) AS avg_confidence,
               ROUND(MIN(confidence)::numeric, 3) AS min_confidence,
               ROUND(MAX(confidence)::numeric, 3) AS max_confidence
        FROM signals
        WHERE detected_at >= :since
        GROUP BY signal_type
        ORDER BY total DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_daily_signal_counts(since: date) -> pd.DataFrame:
    """일별 시그널 발생 건수를 집계한다."""
    query = text("""
        SELECT detected_at::date AS signal_date,
               signal_type,
               COUNT(*) AS count
        FROM signals
        WHERE detected_at >= :since
        GROUP BY signal_date, signal_type
        ORDER BY signal_date
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_signal_stock_freq(since: date) -> pd.DataFrame:
    """종목별 시그널 발생 빈도를 집계한다."""
    query = text("""
        SELECT stock_code, stock_name, signal_type,
               COUNT(*) AS count,
               SUM(CASE WHEN action_taken THEN 1 ELSE 0 END) AS acted
        FROM signals
        WHERE detected_at >= :since
        GROUP BY stock_code, stock_name, signal_type
        ORDER BY count DESC
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


def load_confidence_distribution(since: date) -> pd.DataFrame:
    """신뢰도 분포를 조회한다."""
    query = text("""
        SELECT confidence, action_taken, signal_type
        FROM signals
        WHERE detected_at >= :since
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(query, conn, params={"since": since})


# ── 페이지 ───────────────────────────────────────

st.title("\U0001f4e1 시그널 분석")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)
since = date.today() - timedelta(days=days)

signals_df = load_signals(since)

if signals_df.empty:
    st.info("선택 기간에 시그널 데이터가 없습니다.")
    st.stop()

signals_df["detected_at"] = pd.to_datetime(signals_df["detected_at"])

# ── KPI ──────────────────────────────────────────

total = len(signals_df)
acted = signals_df["action_taken"].sum()
act_rate = (acted / total * 100) if total > 0 else 0
avg_conf = signals_df["confidence"].mean()

k1, k2, k3, k4 = st.columns(4)
k1.metric("총 시그널", f"{total}건")
k2.metric("실행 시그널", f"{int(acted)}건")
k3.metric("실행률", f"{act_rate:.1f}%")
k4.metric("평균 신뢰도", f"{avg_conf:.3f}")

st.divider()

# ── 시그널 유형별 통계 ───────────────────────────

st.subheader("\U0001f4ca 시그널 유형별 통계")

type_stats = load_signal_type_stats(since)

if not type_stats.empty:
    type_stats["act_rate"] = (
        type_stats["acted"] / type_stats["total"] * 100
    ).round(1)

    tc1, tc2 = st.columns(2)

    with tc1:
        st.caption("유형별 발생 건수")
        st.bar_chart(type_stats.set_index("signal_type")["total"])

    with tc2:
        st.caption("유형별 실행률 (%)")
        st.bar_chart(
            type_stats.set_index("signal_type")["act_rate"],
            color="#FF9800",
        )

    st.dataframe(
        type_stats.rename(columns={
            "signal_type": "시그널 유형", "total": "발생",
            "acted": "실행", "act_rate": "실행률(%)",
            "avg_confidence": "평균 신뢰도",
            "min_confidence": "최소 신뢰도",
            "max_confidence": "최대 신뢰도",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── 일별 시그널 추이 ─────────────────────────────

st.subheader("\U0001f4c5 일별 시그널 추이")

daily_signals = load_daily_signal_counts(since)

if not daily_signals.empty:
    daily_signals["signal_date"] = pd.to_datetime(daily_signals["signal_date"])
    pivot = daily_signals.pivot_table(
        index="signal_date", columns="signal_type",
        values="count", fill_value=0,
    )
    st.bar_chart(pivot)

st.divider()

# ── 신뢰도 분포 ─────────────────────────────────

st.subheader("\U0001f3af 신뢰도 분포")

conf_df = load_confidence_distribution(since)

if not conf_df.empty:
    cc1, cc2 = st.columns(2)

    with cc1:
        st.caption("전체 신뢰도 분포")
        # 0.0~1.0을 10구간으로 나눠 히스토그램
        conf_df["bin"] = pd.cut(
            conf_df["confidence"],
            bins=[i / 10 for i in range(11)],
            labels=[f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)],
        )
        hist = conf_df["bin"].value_counts().sort_index()
        st.bar_chart(hist)

    with cc2:
        st.caption("실행 여부별 평균 신뢰도")
        acted_conf = conf_df.groupby("action_taken")["confidence"].mean()
        acted_conf.index = acted_conf.index.map({True: "실행", False: "미실행"})
        st.bar_chart(acted_conf, color="#2196F3")

st.divider()

# ── 종목별 시그널 빈도 ───────────────────────────

st.subheader("\U0001f50d 종목별 시그널 빈도")

stock_freq = load_signal_stock_freq(since)

if not stock_freq.empty:
    st.dataframe(
        stock_freq.rename(columns={
            "stock_code": "종목코드", "stock_name": "종목명",
            "signal_type": "시그널 유형", "count": "발생",
            "acted": "실행",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── 시그널 타임라인 ──────────────────────────────

st.subheader("\U0001f552 시그널 타임라인 (최근 100건)")

st.dataframe(
    signals_df.head(100)[[
        "detected_at", "stock_code", "stock_name",
        "signal_type", "confidence", "action_taken",
    ]].rename(columns={
        "detected_at": "시각", "stock_code": "종목코드",
        "stock_name": "종목명", "signal_type": "시그널 유형",
        "confidence": "신뢰도", "action_taken": "실행 여부",
    }),
    use_container_width=True,
    hide_index=True,
)
