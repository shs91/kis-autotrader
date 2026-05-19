"""pykrx 기반 공매도 잔고 + 투자자별 매매동향 RAG 적재.

KRX 정보데이터시스템(스크래핑)을 사용하므로 인증 불필요. T+2 지연:
오늘이 N일이면 N-2(영업일) 데이터가 가장 최신.

수집 대상: stocks.is_watchlist=True ∪ trades 최근 N일 거래 종목 (~수십개).

설계:
- pykrx 호출은 동기 → 일일 batch script에서 직접 실행. asyncio 미사용.
- 각 (ticker, 데이터타입) 페어를 NewsChunk 1개로 적재.
- source_type=NEWS, metadata={provider: "pykrx", category: "공매도잔고"|"투자자매매"}.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pandas as pd  # type: ignore[import-untyped]

from src.db.models import NewsChunk, NewsSourceType
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.db.repository import (
        NewsChunkRepository,
        StockRepository,
        TradeRepository,
    )
    from src.rag.embedder import Embedder

logger = setup_logger(__name__)

KST = timezone(timedelta(hours=9))

_PYKRX_STOCK: Any = None


def _get_pykrx_stock() -> Any:
    """pykrx.stock 모듈을 lazy-load. 테스트는 이 함수를 patch한다."""
    global _PYKRX_STOCK  # noqa: PLW0603
    if _PYKRX_STOCK is None:
        from pykrx import stock as _stock  # type: ignore[import-not-found]
        _PYKRX_STOCK = _stock
    return _PYKRX_STOCK


@dataclass
class MarketStatsResult:
    target_date: date
    tickers_processed: int
    chunks_inserted: int


def resolve_target_tickers(
    stock_repo: StockRepository,
    trade_repo: TradeRepository,
    days: int = 30,
) -> list[str]:
    """watchlist ∪ 최근 N일 거래 종목 (정렬된 unique 리스트)."""
    watchlist = [s.code for s in stock_repo.list_watchlist()]
    recent = trade_repo.distinct_codes_since(days)
    return sorted(set(watchlist) | set(recent))


def build_short_chunk_text(
    ticker: str, stat_date: date, row: dict[str, Any],
) -> str:
    """공매도 잔고 → 자연어 chunk."""
    qty = row.get("잔고") or 0
    value = row.get("잔고금액") or 0
    short = row.get("공매도") or 0
    short_value = row.get("공매도금액") or 0
    return (
        f"[공매도 잔고] {ticker} — {stat_date.isoformat()}\n"
        f"잔고 수량: {int(qty):,}주\n"
        f"잔고 금액: {int(value):,}원\n"
        f"당일 공매도 거래량: {int(short):,}주 ({int(short_value):,}원)"
    )


def build_investor_chunk_text(
    ticker: str, stat_date: date, df: pd.DataFrame,
) -> str:
    """투자자별 매매동향 → 자연어 chunk.

    DataFrame 행 = 투자자(외국인/기관/개인 등), 열 = 매도/매수/순매수.
    """
    lines = [f"[투자자별 매매] {ticker} — {stat_date.isoformat()}"]
    if "순매수" in df.columns:
        for investor, value in df["순매수"].items():
            try:
                amt = int(value)
            except (TypeError, ValueError):
                continue
            sign = "+" if amt >= 0 else ""
            lines.append(f"{investor} 순매수: {sign}{amt:,}원")
    return "\n".join(lines)


def _content_hash(ticker: str, source_id: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(ticker.encode("utf-8"))
    h.update(b"\x00")
    h.update(source_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def _event_time_for(stat_date: date) -> datetime:
    """데이터 일자의 KST 15:30(장 마감)을 UTC로 변환."""
    return datetime.combine(stat_date, time(15, 30, tzinfo=KST)).astimezone(UTC)


class MarketStatsCollector:
    """대상 종목에 대해 공매도 + 투자자 매매 chunk 적재."""

    def __init__(
        self,
        embedder: Embedder,
        repo: NewsChunkRepository,
        tickers: list[str],
        target_date: date,
    ) -> None:
        self._embedder = embedder
        self._repo = repo
        self._tickers = tickers
        self._target_date = target_date
        self._date_str = target_date.strftime("%Y%m%d")

    def collect(self) -> int:
        """수집 + 청크 변환 + 일괄 임베딩 + DB 적재. 적재 행 수 반환."""
        stock_mod = _get_pykrx_stock()
        chunks: list[NewsChunk] = []
        for ticker in self._tickers:
            chunks.extend(self._collect_short(ticker, stock_mod))
            chunks.extend(self._collect_investor(ticker, stock_mod))

        if not chunks:
            return 0

        texts = [c.chunk_text for c in chunks]
        vectors = self._embedder.encode(texts)
        for c, v in zip(chunks, vectors, strict=True):
            c.embedding = v.tolist()
        return self._repo.insert_chunks(chunks)

    def _collect_short(self, ticker: str, stock_mod: Any) -> list[NewsChunk]:
        try:
            df = stock_mod.get_shorting_status_by_date(
                self._date_str, self._date_str, ticker,
            )
        except Exception:  # noqa: BLE001 — ticker 단위 격리
            logger.exception("공매도 fetch 실패 ticker=%s", ticker)
            return []
        if df is None or df.empty:
            return []
        row = df.iloc[-1].to_dict()
        text = build_short_chunk_text(ticker, self._target_date, row)
        return [self._make_chunk(
            ticker=ticker, kind="short", title=f"공매도 잔고 {self._target_date}",
            text=text,
        )]

    def _collect_investor(self, ticker: str, stock_mod: Any) -> list[NewsChunk]:
        try:
            df = stock_mod.get_market_trading_value_by_investor(
                self._date_str, self._date_str, ticker,
            )
        except Exception:  # noqa: BLE001 — ticker 단위 격리
            logger.exception("투자자 매매 fetch 실패 ticker=%s", ticker)
            return []
        if df is None or df.empty:
            return []
        text = build_investor_chunk_text(ticker, self._target_date, df)
        return [self._make_chunk(
            ticker=ticker, kind="investor", title=f"투자자별 매매 {self._target_date}",
            text=text,
        )]

    def _make_chunk(
        self, ticker: str, kind: str, title: str, text: str,
    ) -> NewsChunk:
        source_id = f"pykrx_{kind}:{ticker}:{self._date_str}"
        category = "공매도잔고" if kind == "short" else "투자자매매"
        return NewsChunk(
            ticker=ticker,
            source_type=NewsSourceType.NEWS,
            source_id=source_id,
            title=title,
            chunk_text=text,
            chunk_index=0,
            content_hash=_content_hash(ticker, source_id, text),
            embedding=[],  # 호출자가 채움
            event_time=_event_time_for(self._target_date),
            chunk_metadata={
                "provider": "pykrx",
                "category": category,
            },
        )
