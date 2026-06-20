"""Altair 기반 시맨틱 차트 — 손익 부호별 색상(이익=초록 / 손실=빨강).

기존 ``st.bar_chart(color="#4CAF50")`` 는 음수(손실)도 단색(초록)으로 그려
손실을 이익색으로 오인하게 했다. 손익 계열은 부호별로 색을 분리한다.
빈/단일 데이터에서 Vega가 'Infinite extent' 경고를 내지 않도록 가드한다.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

POS = "#26A69A"  # 이익(초록)
NEG = "#EF5350"  # 손실(빨강)
NEUTRAL = "#42A5F5"  # 중립(파랑) — 누적선 등
ACCENT = "#7E57C2"  # 보조(보라)


def _empty(df: pd.DataFrame | None, value_col: str) -> bool:
    """그릴 데이터가 없으면 안내 메시지를 띄우고 True를 반환한다."""
    if df is None or df.empty:
        st.info("표시할 데이터가 없습니다.")
        return True
    return False


def pnl_bar_time(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    *,
    value_title: str = "손익",
    money_fmt: str = ",.0f",
) -> None:
    """시간축 손익 막대(부호별 색상)."""
    if _empty(df, value_col):
        return
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{date_col}:T", title=None),
            y=alt.Y(f"{value_col}:Q", title=value_title),
            color=alt.condition(
                f"datum['{value_col}'] >= 0", alt.value(POS), alt.value(NEG)
            ),
            tooltip=[
                alt.Tooltip(f"{date_col}:T", title="날짜"),
                alt.Tooltip(f"{value_col}:Q", title=value_title, format=money_fmt),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, width="stretch")


def pnl_bar_category(
    df: pd.DataFrame,
    cat_col: str,
    value_col: str,
    *,
    value_title: str = "손익",
    money_fmt: str = ",.0f",
    sort_by_value: bool = True,
) -> None:
    """범주축 손익 막대(부호별 색상)."""
    if _empty(df, value_col):
        return
    sort = "-y" if sort_by_value else None
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{cat_col}:N", title=None, sort=sort),
            y=alt.Y(f"{value_col}:Q", title=value_title),
            color=alt.condition(
                f"datum['{value_col}'] >= 0", alt.value(POS), alt.value(NEG)
            ),
            tooltip=[
                alt.Tooltip(f"{cat_col}:N", title="구분"),
                alt.Tooltip(f"{value_col}:Q", title=value_title, format=money_fmt),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, width="stretch")


def cumulative_line(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    *,
    value_title: str = "누적 손익",
    money_fmt: str = ",.0f",
) -> None:
    """누적 손익 선(0선 기준 영역 강조)."""
    if _empty(df, value_col):
        return
    base = alt.Chart(df).encode(
        x=alt.X(f"{date_col}:T", title=None),
        y=alt.Y(f"{value_col}:Q", title=value_title),
    )
    line = base.mark_line(color=NEUTRAL, point=True).encode(
        tooltip=[
            alt.Tooltip(f"{date_col}:T", title="날짜"),
            alt.Tooltip(f"{value_col}:Q", title=value_title, format=money_fmt),
        ],
    )
    zero = alt.Chart(df).mark_rule(color="#9E9E9E", strokeDash=[4, 4]).encode(y=alt.datum(0))
    st.altair_chart((zero + line).properties(height=260), width="stretch")


def grouped_count_bar(
    df: pd.DataFrame,
    date_col: str,
    series_col: str,
    value_col: str,
    *,
    color_scale: dict[str, str] | None = None,
) -> None:
    """시간축 그룹 막대(건수 등 — 부호 무관, 계열별 색상)."""
    if df is None or df.empty:
        st.info("표시할 데이터가 없습니다.")
        return
    color = alt.Color(f"{series_col}:N", title=None)
    if color_scale:
        color = alt.Color(
            f"{series_col}:N",
            title=None,
            scale=alt.Scale(domain=list(color_scale), range=list(color_scale.values())),
        )
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{date_col}:T", title=None),
            y=alt.Y(f"{value_col}:Q", title=None, stack=None),
            color=color,
            xOffset=f"{series_col}:N",
            tooltip=list(df.columns),
        )
        .properties(height=260)
    )
    st.altair_chart(chart, width="stretch")
