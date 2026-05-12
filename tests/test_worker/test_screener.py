"""ScreeningWorker 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.worker.screener import ScreeningWorker


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
