"""NewsCollectorWorker — 여러 collector를 주기적으로 실행하는 메인 루프.

매매 메인 프로세스와 별도 프로세스로 띄운다 (계획서 §4.5):
- 임베딩 모델이 메모리 ~2GB
- 한 collector 실패가 매매 outbox에 영향 없음
- 재시작 비용 격리

통신은 DB 공유만 — 매매 엔진은 news_chunks를 read-only로 조회한다.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from src.utils.logger import setup_logger
from src.worker.collectors.base import CollectionResult

if TYPE_CHECKING:
    from src.worker.collectors.base import BaseCollector

logger = setup_logger(__name__)


class NewsCollectorWorker:
    """여러 collector를 순차 실행하며 일정 간격으로 반복한다."""

    def __init__(
        self,
        collectors: list[BaseCollector],
        interval_sec: float = 300.0,
    ) -> None:
        """
        Args:
            collectors: 실행할 collector 인스턴스 리스트.
            interval_sec: 사이클 사이 대기. 기본 5분.
        """
        self._collectors = collectors
        self._interval_sec = interval_sec

    async def run(self) -> None:
        """무한 루프. cancel/keyboard interrupt로 종료."""
        logger.info(
            "NewsCollectorWorker 시작: collectors=%s interval=%.1fs",
            [c.source_name for c in self._collectors],
            self._interval_sec,
        )
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_sec)

    async def run_once(self) -> list[CollectionResult]:
        """모든 collector를 한 번씩 실행하고 결과를 반환한다.

        한 collector의 예외는 다른 collector를 막지 않는다 (failure isolation).
        """
        results: list[CollectionResult] = []
        for collector in self._collectors:
            start = time.monotonic()
            try:
                result = await collector.run_cycle()
            except Exception as e:  # noqa: BLE001 — collector 실패 격리
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.exception(
                    "collector %s 사이클 실패", collector.source_name,
                )
                result = CollectionResult(
                    source_name=collector.source_name,
                    documents_fetched=0,
                    chunks_inserted=0,
                    elapsed_ms=elapsed_ms,
                    error=str(e),
                )
            results.append(result)
        return results
