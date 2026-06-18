"""positions 차트 데이터 구성 테스트."""

from __future__ import annotations

import pandas as pd

from dashboard.positions_data import build_markers_df, build_reference_levels


def test_reference_levels_computes_stop_take() -> None:
    levels = build_reference_levels(
        avg_price=100.0, peak_price=120.0,
        max_loss_rate=0.03, take_profit_ratio=0.05,
    )
    assert levels["평단가"] == 100.0
    assert levels["손절선"] == 97.0   # 100*(1-0.03)
    assert levels["익절선"] == 105.0  # 100*(1+0.05)
    assert levels["peak"] == 120.0


def test_reference_levels_omits_peak_when_none() -> None:
    levels = build_reference_levels(
        avg_price=100.0, peak_price=None,
        max_loss_rate=0.03, take_profit_ratio=0.05,
    )
    assert "peak" not in levels


def test_markers_dataframe_from_trades() -> None:
    trades = pd.DataFrame({
        "traded_at": pd.to_datetime(["2026-06-18 10:00", "2026-06-18 12:00"]),
        "price": [98.0, 103.0],
        "trade_type": ["BUY", "SELL"],
        "quantity": [10, 10],
    })
    markers = build_markers_df(trades)
    assert list(markers["marker"]) == ["▲", "▼"]
    assert markers.loc[markers["trade_type"] == "BUY", "price"].iloc[0] == 98.0


def test_markers_empty_trades_returns_empty() -> None:
    empty = pd.DataFrame(columns=["traded_at", "price", "trade_type", "quantity"])
    markers = build_markers_df(empty)
    assert markers.empty
    assert "marker" in markers.columns
