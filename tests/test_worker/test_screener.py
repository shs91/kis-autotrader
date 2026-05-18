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
             patch("src.worker.screener.QuoteAPI") as mock_quote_cls, \
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
