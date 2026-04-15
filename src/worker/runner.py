"""Worker 메인 프로세스."""

from __future__ import annotations

import asyncio

from src.config import settings
from src.utils.logger import setup_logger
from src.worker.handlers import TaskHandler
from src.worker.queue import TaskQueueService

logger = setup_logger(__name__)


class WorkerRunner:
    """비동기 태스크 Worker.

    task_queue 테이블을 주기적으로 폴링하여 태스크를 실행한다.
    각 태스크 타입에 대해 등록된 핸들러를 호출하며,
    실패 시 자동 재시도(exponential backoff)를 지원한다.
    """

    def __init__(
        self,
        poll_interval: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        """WorkerRunner를 초기화한다.

        Args:
            poll_interval: 큐 폴링 간격 (초). 기본값: 설정값.
            batch_size: 배치 처리 크기. 기본값: 설정값.
        """
        self._queue = TaskQueueService()
        self._handlers: dict[str, TaskHandler] = {}
        self._poll_interval = poll_interval or settings.worker.poll_interval
        self._batch_size = batch_size or settings.worker.batch_size
        self._running = False

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        """태스크 타입별 핸들러를 등록한다.

        Args:
            task_type: 태스크 유형 문자열.
            handler: 해당 유형을 처리할 핸들러 인스턴스.
        """
        self._handlers[task_type] = handler
        logger.info("핸들러 등록: %s → %s", task_type, type(handler).__name__)

    async def run(self) -> None:
        """Worker 메인 루프.

        poll_interval 간격으로 큐를 확인하고 태스크를 실행한다.
        매 100회 폴링마다 완료된 태스크를 정리한다.
        """
        self._running = True
        poll_count = 0
        logger.info(
            "Worker 시작 (poll=%d초, batch=%d)",
            self._poll_interval,
            self._batch_size,
        )

        while self._running:
            try:
                tasks = self._queue.dequeue(self._batch_size)

                if tasks:
                    logger.info("태스크 %d건 처리 시작", len(tasks))
                    for task in tasks:
                        await self._process_task(task)

                poll_count += 1
                if poll_count % 100 == 0:
                    cleaned = self._queue.cleanup_old_tasks(days=7)
                    if cleaned > 0:
                        logger.info("태스크 정리: %d건 삭제", cleaned)

            except asyncio.CancelledError:
                logger.info("Worker 종료 요청 수신")
                break
            except Exception:
                logger.exception("Worker 폴링 중 에러 (다음 폴링에 영향 없음)")

            await asyncio.sleep(self._poll_interval)

        self._running = False
        logger.info("Worker 종료")

    async def _process_task(self, task: object) -> None:
        """단일 태스크를 처리한다.

        Args:
            task: TaskQueue ORM 인스턴스.
        """
        task_id = task.id
        task_type = task.task_type
        payload = task.payload

        handler = self._handlers.get(task_type)
        if handler is None:
            error_msg = f"미등록 핸들러: {task_type}"
            logger.error("태스크 처리 불가: id=%d, %s", task_id, error_msg)
            self._queue.mark_failed(task_id, error_msg)
            return

        try:
            await handler.execute(payload)
            self._queue.mark_completed(task_id)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            is_dead = self._queue.mark_failed(task_id, error_msg)
            if is_dead:
                await self._notify_dead_task(task_id, task_type, error_msg)

    async def _notify_dead_task(
        self, task_id: int, task_type: str, error: str,
    ) -> None:
        """DEAD 태스크 발생 시 Telegram으로 직접 알림을 전송한다."""
        try:
            from src.notify.telegram import TelegramNotifier

            notifier = TelegramNotifier()
            await notifier.notify_error(
                f"[Worker DEAD] 태스크 영구 실패\n"
                f"id={task_id}, type={task_type}\n"
                f"error: {error[:200]}"
            )
        except Exception:
            logger.exception("DEAD 태스크 알림 전송 실패 (매매에 영향 없음)")

    def stop(self) -> None:
        """Worker를 정지한다."""
        self._running = False
