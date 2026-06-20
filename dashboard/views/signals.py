"""신호 — 통계/추이/신뢰도 + 앙상블 투표 탐색기(vote_meta) (시장 인지)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from lib import db, fmt, market, reasons

st.title(f"\U0001f4e1 신호 · {market.label(market.current_market())}")

days = st.selectbox("분석 기간", [7, 14, 30, 60, 90], index=2)
since = date.today() - timedelta(days=days)
params = {"since": since, **market.market_param()}

# ── KPI ─────────────────────────────────────────────
kpi = db.run_query(
    """
    SELECT COUNT(*) AS total,
           SUM(CASE WHEN action_taken THEN 1 ELSE 0 END) AS acted,
           AVG(confidence) AS avg_conf
    FROM signals
    WHERE detected_at >= :since AND (:market IS NULL OR market = :market)
    """,
    params,
)
row = kpi.iloc[0]
total = int(row["total"] or 0)
if total == 0:
    st.info("선택 기간에 신호 데이터가 없습니다.")
    st.stop()
acted = int(row["acted"] or 0)
k1, k2, k3, k4 = st.columns(4)
k1.metric("총 신호", f"{total:,}건")
k2.metric("실행 신호", f"{acted:,}건")
k3.metric("실행률", f"{acted / total * 100:.1f}%")
k4.metric("평균 신뢰도", fmt.num(row["avg_conf"], decimals=3))

st.divider()

# ── 유형별 통계 ─────────────────────────────────────
st.subheader("\U0001f4ca 시그널 유형별 통계")
types = db.run_query(
    """
    SELECT signal_type,
           COUNT(*) AS total,
           SUM(CASE WHEN action_taken THEN 1 ELSE 0 END) AS acted,
           ROUND(AVG(confidence)::numeric, 3) AS avg_conf,
           ROUND(MIN(confidence)::numeric, 3) AS min_conf,
           ROUND(MAX(confidence)::numeric, 3) AS max_conf
    FROM signals
    WHERE detected_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY signal_type ORDER BY total DESC
    """,
    params,
)
if not types.empty:
    types["실행률"] = (types["acted"] / types["total"] * 100).round(1)
    st.dataframe(
        types.rename(columns={
            "signal_type": "유형", "total": "발생", "acted": "실행",
            "avg_conf": "평균신뢰도", "min_conf": "최소", "max_conf": "최대",
            "실행률": "실행률(%)",
        }),
        width="stretch", hide_index=True,
    )

# ── 일별 추이 ───────────────────────────────────────
st.subheader("\U0001f4c5 일별 신호 추이")
daily = db.run_query(
    """
    SELECT detected_at::date AS d, signal_type, COUNT(*) AS cnt
    FROM signals
    WHERE detected_at >= :since AND (:market IS NULL OR market = :market)
    GROUP BY d, signal_type ORDER BY d
    """,
    params,
)
if not daily.empty:
    pivot = daily.pivot_table(index="d", columns="signal_type", values="cnt", fill_value=0)
    st.bar_chart(pivot)

# ── 신뢰도 분포 ─────────────────────────────────────
st.subheader("\U0001f3af 신뢰도 분포")
conf = db.run_query(
    """
    SELECT confidence, action_taken FROM signals
    WHERE detected_at >= :since AND (:market IS NULL OR market = :market)
    """,
    params,
)
if not conf.empty:
    conf["bin"] = pd.cut(
        conf["confidence"], bins=[i / 10 for i in range(11)],
        labels=[f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)],
    )
    hist = conf["bin"].value_counts().sort_index()
    st.bar_chart(hist)

st.divider()

# ── 앙상블 투표 탐색기 (vote_meta) ──────────────────
st.subheader("\U0001f5f3 앙상블 투표 탐색기")
st.caption(
    "최근 평가된 종목을 선택하면 개별 전략(이동평균·RSI·MACD·볼린저)의 판정·신뢰도·"
    "지표값과 가중 합산 결과를 보여줍니다. (HOLD 평가 기록 기준)"
)
evaluated = db.run_query(
    """
    SELECT DISTINCT sm.detail->>'stock_code' AS code,
           COALESCE(s.name, sm.detail->>'stock_code') AS name
    FROM system_metrics sm
    JOIN stocks s ON s.code = sm.detail->>'stock_code'
    WHERE sm.metric_type = 'SIGNAL_SKIP'
      AND sm.recorded_at >= now() - interval '2 days'
      AND (:market IS NULL OR s.market = :market)
    ORDER BY name LIMIT 300
    """,
    market.market_param(),
)
if evaluated.empty:
    st.info("최근 2일 내 평가 기록이 없습니다.")
else:
    options = evaluated["code"].tolist()
    labels = dict(zip(evaluated["code"], evaluated["name"], strict=False))
    picked = st.selectbox(
        "종목 선택", options, format_func=lambda c: f"{labels.get(c, c)} ({c})"
    )
    latest = db.run_query(
        """
        SELECT detail, recorded_at FROM system_metrics
        WHERE metric_type = 'SIGNAL_SKIP' AND detail->>'stock_code' = :code
        ORDER BY recorded_at DESC LIMIT 1
        """,
        {"code": picked},
    )
    if latest.empty:
        st.info("선택 종목의 평가 기록이 없습니다.")
    else:
        detail = latest.iloc[0]["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail)
        vote_meta = (detail or {}).get("vote_meta", {})
        ts = pd.to_datetime(latest.iloc[0]["recorded_at"]).strftime("%Y-%m-%d %H:%M")
        m1, m2, m3 = st.columns(3)
        m1.metric("최종 판정", reasons.action_label(detail.get("signal_type", "HOLD")))
        m2.metric("종합 신뢰도", fmt.num(detail.get("confidence", 0), decimals=3))
        m3.metric("평가 시각", ts)
        st.caption(reasons.ensemble_summary(vote_meta))
        votes_df = reasons.votes_to_df(vote_meta)
        if votes_df.empty:
            st.info("투표 내역이 없습니다.")
        else:
            st.dataframe(votes_df, width="stretch", hide_index=True)
