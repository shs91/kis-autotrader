"""ScreeningWorker 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.worker.screener import ScreeningWorker


def _make_ranked_item(code: str, name: str = "테스트") -> MagicMock:
    """ranked 리스트에 들어갈 mock item을 생성한다."""
    item = MagicMock()
    item.stock_code = code
    item.stock_name = name
    item.volume = 100_000
    item.change_rate = 1.0
    return item


class TestScreeningWorker:
    """ScreeningWorker 테스트."""

    def test_init(self):
        """ScreeningWorker 초기화가 정상 동작한다."""
        with patch("src.worker.screener.KISAuth"), \
             patch("src.worker.screener.KISClient"), \
             patch("src.worker.screener.QuoteAPI"), \
             patch("src.worker.screener.HybridRateLimiter"), \
             patch("src.worker.screener.StrategyRegistry"), \
             patch("src.worker.screener.StrategySelector"):
            worker = ScreeningWorker(interval=60)

        assert worker._interval == 60
        assert worker._running is False
        assert worker._cycle_count == 0

    def test_stop(self):
        """stop() 호출 시 _running이 False가 된다."""
        with patch("src.worker.screener.KISAuth"), \
             patch("src.worker.screener.KISClient"), \
             patch("src.worker.screener.QuoteAPI"), \
             patch("src.worker.screener.HybridRateLimiter"), \
             patch("src.worker.screener.StrategyRegistry"), \
             patch("src.worker.screener.StrategySelector"):
            worker = ScreeningWorker()

        worker._running = True
        worker.stop()
        assert worker._running is False

    @pytest.mark.asyncio()
    async def test_run_screening_empty_result(self):
        """거래량 순위 결과가 빈 경우 정상 종료한다."""
        with patch("src.worker.screener.KISAuth"), \
             patch("src.worker.screener.KISClient"), \
             patch("src.worker.screener.QuoteAPI"), \
             patch("src.worker.screener.HybridRateLimiter"), \
             patch("src.worker.screener.StrategyRegistry"), \
             patch("src.worker.screener.StrategySelector"):
            worker = ScreeningWorker()

        worker._quote.get_volume_rank = AsyncMock(return_value=[])

        # 매매시간/휴장 가드는 테스트 환경에서 임의 우회
        with patch.object(ScreeningWorker, "_is_trading_window", return_value=True):
            await worker._run_screening()
        assert worker._cycle_count == 1


class TestRecordToDbMetric:
    """`_record_to_db`에서 SCREENING_CANDIDATE 메트릭이 기록되는지 검증한다.

    proposal 2026-05-15: 룰 B 분해를 위해 워커가 자체 추천한 후보 수를
    system_metrics에 별도 카운터로 적재해야 한다.
    """

    def test_screening_candidate_metric_recorded(self):
        with patch("src.worker.screener.KISAuth"), \
             patch("src.worker.screener.KISClient"), \
             patch("src.worker.screener.QuoteAPI"), \
             patch("src.worker.screener.HybridRateLimiter"), \
             patch("src.worker.screener.StrategyRegistry"), \
             patch("src.worker.screener.StrategySelector"):
            worker = ScreeningWorker()
        worker._cycle_count = 7

        ranked = [
            _make_ranked_item("005930", "삼성전자"),
            _make_ranked_item("000660", "SK하이닉스"),
            _make_ranked_item("035720", "카카오"),
        ]
        new_candidates = ["005930", "035720"]

        mock_session = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch(
            "src.worker.screener.ScreeningFilter._is_etf_etn", return_value=False
        ), patch(
            "src.worker.screener.ScreeningResultRepository"
        ), patch(
            "src.worker.screener.SystemMetricRepository"
        ) as mock_metric_repo_cls, patch(
            "src.worker.screener.get_session", return_value=mock_ctx
        ):
            worker._record_to_db(ranked, new_candidates)

        mock_metric_repo_cls.assert_called_once_with(mock_session)
        instance = mock_metric_repo_cls.return_value
        instance.record_metric.assert_called_once()
        kwargs = instance.record_metric.call_args.kwargs
        assert kwargs["metric_type"] == "SCREENING_CANDIDATE"
        assert kwargs["detail"] == {
            "cycle": 7,
            "ranked_total": 3,
            "candidate_count": 2,
        }

    def test_metric_failure_does_not_break_screening(self):
        """SystemMetricRepository에서 예외 발생 시 본 흐름 유지."""
        with patch("src.worker.screener.KISAuth"), \
             patch("src.worker.screener.KISClient"), \
             patch("src.worker.screener.QuoteAPI"), \
             patch("src.worker.screener.HybridRateLimiter"), \
             patch("src.worker.screener.StrategyRegistry"), \
             patch("src.worker.screener.StrategySelector"):
            worker = ScreeningWorker()

        mock_session = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch(
            "src.worker.screener.ScreeningFilter._is_etf_etn", return_value=False
        ), patch(
            "src.worker.screener.ScreeningResultRepository"
        ), patch(
            "src.worker.screener.SystemMetricRepository"
        ) as mock_metric_repo_cls, patch(
            "src.worker.screener.get_session", return_value=mock_ctx
        ):
            mock_metric_repo_cls.return_value.record_metric.side_effect = (
                RuntimeError("기록 실패")
            )
            worker._record_to_db([_make_ranked_item("005930")], ["005930"])


def _make_worker() -> ScreeningWorker:
    with patch("src.worker.screener.KISAuth"), \
         patch("src.worker.screener.KISClient"), \
         patch("src.worker.screener.QuoteAPI"), \
         patch("src.worker.screener.HybridRateLimiter"), \
         patch("src.worker.screener.StrategyRegistry"), \
         patch("src.worker.screener.StrategySelector"):
        return ScreeningWorker()


def _session_ctx() -> MagicMock:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestRiskBlockedCodes:
    """`_load_risk_blocked_codes` — 위험종목 사전 배제 로직."""

    def test_market_action_and_disclosure_blocked(self):
        """시장조치 차단 종목과 치명 공시 종목이 모두 사유와 함께 반환된다."""
        worker = _make_worker()
        worker._cycle_count = 3

        # 001740: 시장조치(관리종목) 차단 / 230980: 정리매매 공시 / 005930: clean
        ma_blocked = MagicMock()
        ma_blocked.should_block_buy = True
        ma_blocked.block_reasons = ["administrative"]

        def ma_get(code: str):
            return ma_blocked if code == "001740" else None

        def disclosure_titles(code: str, since):  # noqa: ARG001
            if code == "230980":
                return ["주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)"]
            return ["단일판매ㆍ공급계약체결"]

        with patch("src.worker.screener.get_session", return_value=_session_ctx()), \
             patch("src.worker.screener.MarketActionRepository") as ma_cls, \
             patch("src.worker.screener.NewsChunkRepository") as news_cls:
            ma_cls.return_value.get.side_effect = ma_get
            news_cls.return_value.get_recent_disclosure_titles.side_effect = (
                disclosure_titles
            )
            blocked = worker._load_risk_blocked_codes({"001740", "230980", "005930"})

        assert blocked["001740"] == "administrative"
        assert "정리매매" in blocked["230980"]
        assert "005930" not in blocked

    def test_empty_codes_returns_empty(self):
        """후보가 없으면 DB 조회 없이 빈 dict."""
        worker = _make_worker()
        with patch("src.worker.screener.get_session") as gs:
            assert worker._load_risk_blocked_codes(set()) == {}
            gs.assert_not_called()

    def test_db_error_is_swallowed(self):
        """DB 조회 실패는 스크리닝을 막지 않고 빈 dict를 반환한다."""
        worker = _make_worker()
        with patch(
            "src.worker.screener.get_session", side_effect=RuntimeError("DB down")
        ):
            assert worker._load_risk_blocked_codes({"005930"}) == {}

    @pytest.mark.asyncio()
    async def test_run_screening_excludes_risk_codes(self):
        """_run_screening이 위험종목을 filter_candidates의 exclude_codes에 합친다."""
        worker = _make_worker()
        ranked = [_make_ranked_item("230980", "비유테크놀러지"),
                  _make_ranked_item("005930", "삼성전자")]
        worker._quote.get_volume_rank = AsyncMock(return_value=ranked)
        worker._screener.filter_candidates = MagicMock(return_value=[])

        with patch.object(ScreeningWorker, "_is_trading_window", return_value=True), \
             patch.object(worker, "_load_existing_screened_codes", return_value=set()), \
             patch.object(
                 worker, "_load_risk_blocked_codes",
                 return_value={"230980": "정리매매"},
             ), \
             patch.object(worker, "_record_risk_excluded_metric") as rec, \
             patch.object(worker, "_record_to_db"):
            await worker._run_screening()

        exclude_arg = worker._screener.filter_candidates.call_args.args[1]
        assert "230980" in exclude_arg
        rec.assert_called_once()
