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

import pandas as pd

from src.db.models import NewsChunk, NewsSourceType
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.db.repository import (
        NewsChunkRepository,
        StockRepository,
        SystemMetricRepository,
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
        from pykrx import stock as _stock  # type: ignore[import-untyped]
        _PYKRX_STOCK = _stock
    return _PYKRX_STOCK


@dataclass
class MarketStatsResult:
    target_date: date
    tickers_processed: int
    chunks_inserted: int


_ETF_BRAND_PREFIXES = (
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "SOL",
    "ACE", "PLUS", "KOSEF", "TIMEFOLIO", "SMART", "FOCUS",
    "WOORI", "히어로즈",
)


def _is_etf_like(name: str | None) -> bool:
    """이름이 ETF/ETN 운용사 brand로 시작하면 True."""
    if not name:
        return False
    upper = name.upper()
    return any(upper.startswith(p.upper()) for p in _ETF_BRAND_PREFIXES)


def resolve_target_tickers(
    stock_repo: StockRepository,
    trade_repo: TradeRepository,
    days: int = 30,
) -> list[str]:
    """watchlist ∪ 최근 N일 거래 종목 (정렬된 unique 리스트).

    필터:
    - 6자리 숫자 코드만 (Q760027 등 ELW/파생 제외)
    - stocks 테이블에 존재 + market in ('KOSPI','KOSDAQ')
    - KIS 마스터가 KODEX 인버스 등 ETF를 KOSPI ST로 잘못 분류하므로
      stocks.name이 ETF/ETN 운용사 brand로 시작하면 skip
    """
    import re
    valid_stocks = {
        s.code for s in stock_repo.list_all()
        if s.market in ("KOSPI", "KOSDAQ") and not _is_etf_like(s.name)
    }
    watchlist = [s.code for s in stock_repo.list_watchlist()]
    recent = trade_repo.distinct_codes_since(days)
    candidates = set(watchlist) | set(recent)
    return sorted(
        c for c in candidates
        if re.fullmatch(r"\d{6}", c) and c in valid_stocks
    )


def _nearest_krx_business_day(reference: date, lookback_days: int = 2) -> date:
    """reference에서 lookback_days만큼 과거의 가장 가까운 KRX 영업일.

    KRX는 토/일/한국 공휴일 휴장. 우리 시스템의 `src/scheduler/holidays.py`
    (holidays.json 기반)를 활용해 공휴일도 보정한다.

    pykrx 내장 helper는 KRX 사이트를 호출하므로 일요일/공휴일에 fail —
    의존 안 함.
    """
    from src.scheduler.holidays import is_market_closed

    candidate = reference - timedelta(days=lookback_days)
    # 토/일/공휴일이면 평일로 거슬러 이동
    while is_market_closed(candidate):
        candidate -= timedelta(days=1)
    return candidate


def build_short_chunk_text(
    ticker: str, stat_date: date, row: dict[str, Any],
) -> str:
    """공매도 잔고 → 자연어 chunk.

    pykrx 응답 컬럼명 호환: '잔고'/'잔고수량', '공매도'/'거래량', '공매도금액'/'거래대금'.
    """
    qty = row.get("잔고수량") or row.get("잔고") or 0
    value = row.get("잔고금액") or 0
    short = row.get("거래량") or row.get("공매도") or 0
    short_value = row.get("거래대금") or row.get("공매도금액") or 0
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
        metric_repo: SystemMetricRepository | None = None,
    ) -> None:
        self._embedder = embedder
        self._repo = repo
        self._tickers = tickers
        self._target_date = target_date
        self._date_str = target_date.strftime("%Y%m%d")
        self._metric_repo = metric_repo

    def collect(self) -> int:
        """수집 + 청크 변환 + 일괄 임베딩 + DB 적재. 적재 행 수 반환."""
        import time as _time
        start = _time.monotonic()
        stock_mod = _get_pykrx_stock()
        chunks: list[NewsChunk] = []
        for ticker in self._tickers:
            chunks.extend(self._collect_short(ticker, stock_mod))
            chunks.extend(self._collect_investor(ticker, stock_mod))

        if not chunks:
            self._record_metric(0, int((_time.monotonic() - start) * 1000))
            return 0

        texts = [c.chunk_text for c in chunks]
        vectors = self._embedder.encode(texts)
        for c, v in zip(chunks, vectors, strict=True):
            c.embedding = v.tolist()
        inserted = self._repo.insert_chunks(chunks)
        self._record_metric(inserted, int((_time.monotonic() - start) * 1000))
        return inserted

    def _record_metric(self, inserted: int, elapsed_ms: int) -> None:
        if self._metric_repo is None:
            return
        try:
            # 별도 session으로 commit 보장
            from src.db.repository import SystemMetricRepository
            from src.db.session import get_session
            with get_session() as session:
                SystemMetricRepository(session).record_metric(
                    "NEWS_COLLECTED",
                    {
                        "source": "pykrx",
                        "documents": len(self._tickers),
                        "chunks_inserted": inserted,
                        "elapsed_ms": elapsed_ms,
                        "target_date": self._target_date.isoformat(),
                    },
                )
        except Exception:  # noqa: BLE001
            logger.exception("NEWS_COLLECTED 메트릭 기록 실패 (pykrx)")

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
        # 정상 응답은 한글 컬럼. ETF brand 필터를 통과한 잔존 ETF 등 비정상
        # 응답(영문 컬럼 CVSRTSELL_TRDVOL 등)은 skip.
        if "잔고수량" not in df.columns and "잔고" not in df.columns:
            logger.warning(
                "공매도 비정상 응답 ticker=%s cols=%s", ticker, list(df.columns),
            )
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
