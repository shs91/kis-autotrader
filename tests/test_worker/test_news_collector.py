"""NewsCollectorWorker 테스트.

여러 collector를 주기적으로 실행하는 메인 루프. 한 collector의 실패가
다른 collector를 막지 않아야 한다.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.worker.collectors.base import CollectionResult
from src.worker.news_collector import NewsCollectorWorker


def _stub_collector(name: str, result: CollectionResult | Exception) -> MagicMock:
    c = MagicMock()
    c.source_name = name
    if isinstance(result, Exception):
        c.run_cycle = AsyncMock(side_effect=result)
    else:
        c.run_cycle = AsyncMock(return_value=result)
    return c


@pytest.mark.asyncio
class TestRunOnce:
    async def test_executes_all_collectors(self) -> None:
        c1 = _stub_collector("dart", CollectionResult("dart", 5, 10, 100))
        c2 = _stub_collector("rss", CollectionResult("rss", 3, 6, 80))
        worker = NewsCollectorWorker(collectors=[c1, c2])

        results = await worker.run_once()
        assert len(results) == 2
        c1.run_cycle.assert_awaited_once()
        c2.run_cycle.assert_awaited_once()

    async def test_failure_isolated(self) -> None:
        """한 collector가 예외를 던져도 다른 collector는 계속 실행."""
        c1 = _stub_collector("dart", RuntimeError("API down"))
        c2 = _stub_collector("rss", CollectionResult("rss", 3, 6, 80))
        worker = NewsCollectorWorker(collectors=[c1, c2])

        results = await worker.run_once()
        assert len(results) == 2
        c2.run_cycle.assert_awaited_once()
        # 실패한 collector의 결과는 error 필드 set
        dart_result = next(r for r in results if r.source_name == "dart")
        assert dart_result.error is not None


@pytest.mark.asyncio
class TestRunLoop:
    async def test_run_loop_stops_when_cancelled(self) -> None:
        """run()은 무한 루프이지만 cancel 시 정상 종료."""
        c = _stub_collector("dart", CollectionResult("dart", 0, 0, 10))
        worker = NewsCollectorWorker(collectors=[c], interval_sec=0.01)

        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)  # 몇 사이클 돌게
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # 최소 1회는 실행됨
        assert c.run_cycle.await_count >= 1
