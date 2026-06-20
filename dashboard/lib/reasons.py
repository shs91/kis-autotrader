"""매수/매도 사유 한글 라벨 + 앙상블 투표(vote_meta) 파싱.

- ``buy_label`` / ``sell_label``: enum 코드 → 한글(누락분 포함 전체 매핑).
- ``votes_to_df``: ``system_metrics.detail.vote_meta`` → 전략별 투표표
  (전략·판정·신뢰도·핵심 지표값). 약세장 0매매의 '왜'를 전략 단위로 노출.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# buy_reason_enum: GOLDEN_CROSS, RSI_OVERSOLD, ENSEMBLE, MANUAL
BUY_REASON_LABELS: dict[str, str] = {
    "GOLDEN_CROSS": "골든크로스",
    "RSI_OVERSOLD": "RSI 과매도",
    "ENSEMBLE": "앙상블",
    "MANUAL": "수동",
}

# sell_reason_enum: STOP_LOSS, TAKE_PROFIT, STRATEGY, MANUAL,
#                   TRAILING_STOP, MARKET_CLOSE, BREAKEVEN, STAGNATION
SELL_REASON_LABELS: dict[str, str] = {
    "STOP_LOSS": "손절",
    "TAKE_PROFIT": "익절",
    "STRATEGY": "전략매도",
    "MANUAL": "수동",
    "TRAILING_STOP": "추격손절",
    "MARKET_CLOSE": "장마감청산",
    "BREAKEVEN": "본전청산",
    "STAGNATION": "정체청산",
}

ACTION_LABELS: dict[str, str] = {
    "BUY": "매수",
    "SELL": "매도",
    "HOLD": "관망",
}


def buy_label(code: Any) -> str:
    """매수 사유 코드를 한글 라벨로. 빈 값은 '미분류'."""
    if code is None or (isinstance(code, float) and pd.isna(code)) or code == "":
        return "미분류"
    return BUY_REASON_LABELS.get(str(code), str(code))


def sell_label(code: Any) -> str:
    """매도 사유 코드를 한글 라벨로. 빈 값은 '미분류'."""
    if code is None or (isinstance(code, float) and pd.isna(code)) or code == "":
        return "미분류"
    return SELL_REASON_LABELS.get(str(code), str(code))


def action_label(action: Any) -> str:
    """전략 판정(BUY/SELL/HOLD)을 한글로."""
    return ACTION_LABELS.get(str(action), str(action))


def _indicator_summary(vote: dict[str, Any]) -> str:
    """전략별 핵심 지표값을 한 줄 요약한다(vote_meta의 전략별 필드 차이를 흡수)."""
    if "last_rsi" in vote:
        return f"RSI {vote['last_rsi']:.1f}"
    if "last_macd" in vote:
        return (
            f"MACD {vote['last_macd']:.0f} · 시그널 {vote.get('last_signal', 0):.0f} · "
            f"히스토 {vote.get('last_hist', 0):.0f}"
        )
    if "last_percent_b" in vote:
        return f"%B {vote['last_percent_b']:.3f}"
    if "last_long" in vote or "last_short" in vote:
        return f"단기 {vote.get('last_short', 0):,.0f} · 장기 {vote.get('last_long', 0):,.0f}"
    return ""


def votes_to_df(vote_meta: dict[str, Any] | None) -> pd.DataFrame:
    """``vote_meta`` 를 전략별 투표표(DataFrame)로 변환한다.

    컬럼: 전략 · 판정 · 신뢰도 · 핵심 지표. votes가 없으면 빈 DataFrame.
    """
    votes = (vote_meta or {}).get("votes") or []
    rows = []
    for vote in votes:
        rows.append(
            {
                "전략": vote.get("strategy", "?"),
                "판정": action_label(vote.get("action")),
                "신뢰도": round(float(vote.get("confidence", 0.0)), 3),
                "가드": "⚠" if vote.get("guard_triggered") else "",
                "핵심 지표": _indicator_summary(vote),
            }
        )
    return pd.DataFrame(rows)


def ensemble_summary(vote_meta: dict[str, Any] | None) -> str:
    """앙상블 메서드/최종 신뢰도 한 줄 요약."""
    meta = vote_meta or {}
    method = meta.get("method", "?")
    return f"방식: {method}"
