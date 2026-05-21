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
class TestPerCycleCommit:
    """워커가 들고 있는 session을 collector 사이클마다 commit/rollback 해야 한다.

    단일 장기 session이 무한 루프를 감싸면 사이클별 변경이 flush만 되고
    graceful 종료 시 1회만 commit → 크래시/PendingRollbackError 시 state 유실.
    """

    async def test_commits_session_after_each_successful_cycle(self) -> None:
        session = MagicMock()
        c1 = _stub_collector("dart", CollectionResult("dart", 5, 10, 100))
        c2 = _stub_collector("rss", CollectionResult("rss", 3, 6, 80))
        worker = NewsCollectorWorker(collectors=[c1, c2], session=session)

        await worker.run_once()
        assert session.commit.call_count == 2
        session.rollback.assert_not_called()

    async def test_rolls_back_session_on_cycle_failure(self) -> None:
        """예외 사이클은 rollback으로 session을 정상화하고, 다음 collector는 commit."""
        session = MagicMock()
        c1 = _stub_collector("dart", RuntimeError("API down"))
        c2 = _stub_collector("rss", CollectionResult("rss", 3, 6, 80))
        worker = NewsCollectorWorker(collectors=[c1, c2], session=session)

        results = await worker.run_once()
        assert len(results) == 2
        session.rollback.assert_called_once()
        session.commit.assert_called_once()

    async def test_no_session_means_no_commit(self) -> None:
        """session 미주입(기존 호환) 시 commit/rollback을 호출하지 않는다."""
        c = _stub_collector("dart", CollectionResult("dart", 1, 1, 10))
        worker = NewsCollectorWorker(collectors=[c])
        # session이 없어도 예외 없이 동작
        results = await worker.run_once()
        assert len(results) == 1


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
