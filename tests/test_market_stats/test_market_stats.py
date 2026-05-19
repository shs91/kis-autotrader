"""pykrx 기반 공매도 잔고 + 투자자별 매매 RAG 적재 테스트.

pykrx 모듈 자체는 mock — 실제 호출은 통합 테스트에서.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.market_stats import (
    MarketStatsCollector,
    build_investor_chunk_text,
    build_short_chunk_text,
    resolve_target_tickers,
)


def _mock_embedder(dim: int = 1024) -> MagicMock:
    e = MagicMock()
    e.encode.side_effect = lambda texts, **kw: np.zeros((len(texts), dim), dtype=np.float32)
    return e


def _mock_repo() -> MagicMock:
    r = MagicMock()
    r.insert_chunks.side_effect = lambda chunks: len(chunks)
    return r


def _pykrx_short_df(qty: int = 1_234_567, value: int = 89_012_000_000) -> pd.DataFrame:
    return pd.DataFrame(
        {"공매도": [10000], "잔고": [qty], "공매도금액": [50_000_000], "잔고금액": [value]},
        index=pd.DatetimeIndex(["2026-05-17"]),
    )


def _pykrx_investor_df() -> pd.DataFrame:
    """행=투자자, 열=매도/매수/순매수."""
    return pd.DataFrame(
        {
            "매도": [100, 200, 300],
            "매수": [434, 80, 175],
            "순매수": [334, -120, -125],
        },
        index=pd.Index(["외국인", "기관합계", "개인"], name="투자자구분"),
    )


class TestChunkText:
    def test_short_chunk_text_includes_ticker_and_date(self) -> None:
        text = build_short_chunk_text(
            ticker="005930", stat_date=date(2026, 5, 17),
            row={"잔고": 1234567, "잔고금액": 89_012_000_000},
        )
        assert "005930" in text
        assert "2026-05-17" in text
        assert "잔고" in text

    def test_investor_chunk_text_lists_all_investors(self) -> None:
        text = build_investor_chunk_text(
            ticker="005930", stat_date=date(2026, 5, 17),
            df=_pykrx_investor_df(),
        )
        assert "외국인" in text
        assert "기관" in text
        assert "개인" in text
        assert "005930" in text


class TestResolveTargetTickers:
    def test_unions_watchlist_and_recent_trades(self) -> None:
        stock_repo = MagicMock()
        trade_repo = MagicMock()
        stock_repo.list_all.return_value = [
            MagicMock(code="005930", market="KOSPI"),
            MagicMock(code="000660", market="KOSPI"),
            MagicMock(code="035420", market="KOSPI"),
        ]
        stock_repo.list_watchlist.return_value = [
            MagicMock(code="005930"), MagicMock(code="000660"),
        ]
        trade_repo.distinct_codes_since.return_value = ["000660", "035420"]
        tickers = resolve_target_tickers(
            stock_repo=stock_repo, trade_repo=trade_repo, days=30,
        )
        assert sorted(tickers) == ["000660", "005930", "035420"]

    def test_skips_non_6digit_codes(self) -> None:
        stock_repo = MagicMock()
        trade_repo = MagicMock()
        stock_repo.list_all.return_value = [MagicMock(code="005930", market="KOSPI")]
        stock_repo.list_watchlist.return_value = [
            MagicMock(code="005930"),
            MagicMock(code="Q760027"),
            MagicMock(code="F70100026"),
        ]
        trade_repo.distinct_codes_since.return_value = ["12345", "1234567"]
        tickers = resolve_target_tickers(
            stock_repo=stock_repo, trade_repo=trade_repo, days=30,
        )
        assert tickers == ["005930"]

    def test_skips_trades_only_codes_not_in_stocks(self) -> None:
        """trades에만 있고 stocks에 없는 ETF/잔존 코드 자동 skip."""
        stock_repo = MagicMock()
        trade_repo = MagicMock()
        stock_repo.list_all.return_value = [
            MagicMock(code="005930", market="KOSPI"),
            MagicMock(code="000660", market="KOSPI"),
        ]
        stock_repo.list_watchlist.return_value = []
        trade_repo.distinct_codes_since.return_value = ["005930", "114800", "000660"]
        tickers = resolve_target_tickers(
            stock_repo=stock_repo, trade_repo=trade_repo, days=30,
        )
        assert tickers == ["000660", "005930"]

    def test_skips_unknown_market(self) -> None:
        """market='UNKNOWN' 은 KIS 마스터에서 분류 못한 종목 — skip."""
        stock_repo = MagicMock()
        trade_repo = MagicMock()
        stock_repo.list_all.return_value = [
            MagicMock(code="005930", market="KOSPI"),
            MagicMock(code="274090", market="UNKNOWN"),
        ]
        stock_repo.list_watchlist.return_value = [
            MagicMock(code="005930"), MagicMock(code="274090"),
        ]
        trade_repo.distinct_codes_since.return_value = []
        tickers = resolve_target_tickers(
            stock_repo=stock_repo, trade_repo=trade_repo, days=30,
        )
        assert tickers == ["005930"]


class TestNearestBusinessDay:
    def test_weekday_returns_same(self) -> None:
        from src.market_stats import _nearest_krx_business_day
        # 2026-05-19 = 화요일
        result = _nearest_krx_business_day(date(2026, 5, 21), lookback_days=2)
        # 5/21(목) - 2 = 5/19(화) → 평일이라 그대로
        assert result == date(2026, 5, 19)

    def test_sunday_rolls_back_to_friday(self) -> None:
        from src.market_stats import _nearest_krx_business_day
        # 2026-05-19(화) - 2 = 5/17(일) → 5/15(금)으로 보정
        result = _nearest_krx_business_day(date(2026, 5, 19), lookback_days=2)
        assert result == date(2026, 5, 15)
        assert result.weekday() == 4  # 금요일


@pytest.mark.parametrize("kind", ["short", "investor"])
class TestCollectorIntegration:
    def test_collect_inserts_chunks(self, kind: str) -> None:
        embedder = _mock_embedder()
        repo = _mock_repo()

        # pykrx 두 함수 mock
        mock_stock = MagicMock()
        mock_stock.get_shorting_status_by_date.return_value = _pykrx_short_df()
        mock_stock.get_market_trading_value_by_investor.return_value = _pykrx_investor_df()

        with patch("src.market_stats._get_pykrx_stock", return_value=mock_stock):
            collector = MarketStatsCollector(
                embedder=embedder, repo=repo,
                tickers=["005930"], target_date=date(2026, 5, 17),
            )
            inserted = collector.collect()

        # 두 종류(short + investor) chunk가 동시에 적재
        assert inserted == 2
        chunks = repo.insert_chunks.call_args.args[0]
        assert any(c.chunk_metadata.get("category") == "공매도잔고" for c in chunks)
        assert any(c.chunk_metadata.get("category") == "투자자매매" for c in chunks)
        # 메타 provider = pykrx
        assert all(c.chunk_metadata.get("provider") == "pykrx" for c in chunks)
        # event_time = target_date 15:30 KST → UTC
        for c in chunks:
            assert c.event_time.tzinfo is not None


class TestCollectorErrorIsolation:
    def test_empty_dataframe_skipped(self) -> None:
        """pykrx가 빈 DataFrame 반환 시 chunk 0 (예: 영업일 외 호출)."""
        mock_stock = MagicMock()
        mock_stock.get_shorting_status_by_date.return_value = pd.DataFrame()
        mock_stock.get_market_trading_value_by_investor.return_value = pd.DataFrame()

        embedder = _mock_embedder()
        repo = _mock_repo()

        with patch("src.market_stats._get_pykrx_stock", return_value=mock_stock):
            collector = MarketStatsCollector(
                embedder=embedder, repo=repo,
                tickers=["005930"], target_date=date(2026, 5, 17),
            )
            inserted = collector.collect()
        assert inserted == 0

    def test_pykrx_exception_skips_ticker(self) -> None:
        """한 종목 pykrx 에러가 다음 종목 처리를 막지 않는다."""
        mock_stock = MagicMock()
        mock_stock.get_shorting_status_by_date.side_effect = [
            RuntimeError("KRX 사이트 오류"),
            _pykrx_short_df(),
        ]
        mock_stock.get_market_trading_value_by_investor.return_value = pd.DataFrame()

        embedder = _mock_embedder()
        repo = _mock_repo()

        with patch("src.market_stats._get_pykrx_stock", return_value=mock_stock):
            collector = MarketStatsCollector(
                embedder=embedder, repo=repo,
                tickers=["005930", "000660"], target_date=date(2026, 5, 17),
            )
            inserted = collector.collect()
        # 두 번째 종목의 short만 적재
        assert inserted == 1


def _isoformat_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()
