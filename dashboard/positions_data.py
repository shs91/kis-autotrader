"""positions 페이지 차트 데이터 구성(순수 함수 — 렌더와 분리해 테스트 가능)."""

from __future__ import annotations

import pandas as pd


def build_reference_levels(
    avg_price: float,
    peak_price: float | None,
    max_loss_rate: float,
    take_profit_ratio: float,
) -> dict[str, float]:
    """차트 수평 기준선 값들을 계산한다(평단가·손절선·익절선·peak)."""
    levels: dict[str, float] = {
        "평단가": avg_price,
        "손절선": avg_price * (1.0 - max_loss_rate),
        "익절선": avg_price * (1.0 + take_profit_ratio),
    }
    if peak_price is not None and peak_price > 0:
        levels["peak"] = peak_price
    return levels


def build_markers_df(trades: pd.DataFrame) -> pd.DataFrame:
    """trades(traded_at, price, trade_type, quantity)를 차트 마커 DataFrame으로.

    매수=▲, 매도=▼.
    """
    if trades.empty:
        return pd.DataFrame(
            columns=["traded_at", "price", "trade_type", "quantity", "marker"]
        )
    out = trades.copy()
    out["marker"] = out["trade_type"].map(lambda t: "▲" if t == "BUY" else "▼")
    return out
