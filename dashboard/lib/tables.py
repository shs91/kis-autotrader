"""조회 결과 → 표시용 DataFrame 변환(한글 헤더·네이티브 통화·사유 한글).

입력 DataFrame은 ``market`` 컬럼을 포함해야 시장별 통화 포맷이 적용된다.
overview/매매 페이지가 공유한다.
"""

from __future__ import annotations

import pandas as pd
from lib import fmt, reasons

_MARKET_FLAG = {"KRX": "🇰🇷", "US": "🇺🇸"}


def _stock_label(df: pd.DataFrame) -> pd.Series:
    name = df["stock_name"].fillna(df["stock_code"]) if "stock_name" in df else df["stock_code"]
    return name.astype(str) + " (" + df["stock_code"].astype(str) + ")"


def _trade_reason(row: pd.Series) -> str:
    if row.get("trade_type") == "BUY":
        return reasons.buy_label(row.get("buy_reason"))
    return reasons.sell_label(row.get("sell_reason"))


def trades_display(df: pd.DataFrame, *, show_market: bool = True) -> pd.DataFrame:
    """trades 조회 결과를 표시용 DataFrame으로 변환한다."""
    if df.empty:
        return df
    markets = df["market"].fillna("KRX")
    out = pd.DataFrame(index=df.index)
    out["시각"] = pd.to_datetime(df["traded_at"]).dt.strftime("%m-%d %H:%M")
    if show_market:
        out["시장"] = markets.map(_MARKET_FLAG).fillna(markets)
    out["종목"] = _stock_label(df)
    out["구분"] = df["trade_type"].map({"BUY": "매수", "SELL": "매도"}).fillna(df["trade_type"])
    out["수량"] = [fmt.num(q) for q in df["quantity"]]
    out["가격"] = [fmt.money(p, mk) for p, mk in zip(df["price"], markets, strict=False)]
    if "total_amount" in df:
        out["체결금액"] = [
            fmt.money(a, mk) for a, mk in zip(df["total_amount"], markets, strict=False)
        ]
    out["사유"] = df.apply(_trade_reason, axis=1)
    if "confidence" in df:
        out["신뢰도"] = [fmt.num(c, decimals=2) if pd.notna(c) else "-" for c in df["confidence"]]
    if "profit_loss_pct" in df:
        out["수익률"] = [fmt.pct(v) if pd.notna(v) else "-" for v in df["profit_loss_pct"]]
    if "profit_loss_amount" in df:
        out["손익"] = [
            fmt.money(v, mk, signed=True) if pd.notna(v) else "-"
            for v, mk in zip(df["profit_loss_amount"], markets, strict=False)
        ]
    return out


def portfolio_display(df: pd.DataFrame, *, show_market: bool = True) -> pd.DataFrame:
    """portfolios 조회 결과를 표시용 DataFrame으로 변환한다."""
    if df.empty:
        return df
    markets = df["market"].fillna("KRX")
    out = pd.DataFrame(index=df.index)
    if show_market:
        out["시장"] = markets.map(_MARKET_FLAG).fillna(markets)
    out["종목"] = _stock_label(df)
    out["수량"] = [fmt.num(q) for q in df["quantity"]]
    out["평균가"] = [fmt.money(p, mk) for p, mk in zip(df["avg_price"], markets, strict=False)]
    out["현재가"] = [fmt.money(p, mk) for p, mk in zip(df["current_price"], markets, strict=False)]
    out["수익률"] = [fmt.pct(v) for v in df["profit_rate"]]
    out["평가손익"] = [
        fmt.money(v, mk, signed=True) for v, mk in zip(df["profit_loss"], markets, strict=False)
    ]
    return out
