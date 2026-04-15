"""PostgreSQL 기반 태스크 큐 서비스."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from src.config import settings
from src.db.models import TaskQueue, TaskStatus
from src.db.session import get_session
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class TaskQueueService:
    """PostgreSQL Outbox 패턴 태스크 큐.

    매매 엔진에서 enqueue()로 태스크를 적재하고,
    Worker가 dequeue()로 가져와 실행한다.
    """

    def enqueue(
        self,
        task_type: str,
        payload: dict,
        priority: int = 0,
        idempotency_key: str | None = None,
        max_retries: int | None = None,
        scheduled_at: datetime | None = None,
    ) -> int | None:
        """태스크를 큐에 추가한다.

        Args:
            task_type: 태스크 유형 (calendar_event, telegram_notify 등).
            payload: JSON 직렬화 가능한 태스크 데이터.
            priority: 우선순위 (높을수록 먼저 실행).
            idempotency_key: 중복 방지 키.
            max_retries: 최대 재시도 횟수 (기본값: 설정값).
            scheduled_at: 예약 실행 시각 (기본값: 즉시).

        Returns:
            생성된 태스크 ID. 중복 키로 스킵 시 None.
        """
        if max_retries is None:
            max_retries = settings.worker.max_retries
        if scheduled_at is None:
            scheduled_at = datetime.now(UTC)

        try:
            with get_session() as session:
                if idempotency_key:
                    existing = session.execute(
                        select(TaskQueue.id).where(
                            TaskQueue.idempotency_key == idempotency_key
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        logger.debug(
                            "중복 태스크 스킵: key=%s, existing_id=%d",
                            idempotency_key,
                            existing,
                        )
                        return None

                task = TaskQueue(
                    task_type=task_type,
                    payload=payload,
                    status=TaskStatus.PENDING,
                    priority=priority,
                    idempotency_key=idempotency_key,
                    max_retries=max_retries,
                    scheduled_at=scheduled_at,
                )
                session.add(task)
                session.flush()
                task_id = task.id
                logger.info(
                    "태스크 등록: id=%d, type=%s, priority=%d",
                    task_id,
                    task_type,
                    priority,
                )
                return task_id

        except Exception:
            logger.exception("태스크 등록 실패: type=%s", task_type)
            return None

    def dequeue(self, batch_size: int | None = None) -> list[TaskQueue]:
        """실행 가능한 태스크를 가져온다.

        FOR UPDATE SKIP LOCKED로 동시 Worker 안전성을 보장한다.

        Args:
            batch_size: 가져올 태스크 수 (기본값: 설정값).

        Returns:
            실행 대상 태스크 목록.
        """
        if batch_size is None:
            batch_size = settings.worker.batch_size

        now = datetime.now(UTC)

        with get_session() as session:
            stmt = (
                select(TaskQueue)
                .where(
                    TaskQueue.status.in_([TaskStatus.PENDING, TaskStatus.FAILED]),
                    TaskQueue.scheduled_at <= now,
                    TaskQueue.retry_count < TaskQueue.max_retries,
                )
                .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            tasks = list(session.execute(stmt).scalars().all())

            for task in tasks:
                task.status = TaskStatus.RUNNING
                task.started_at = now

            session.flush()

            # 세션 밖에서도 접근 가능하도록 속성을 detach 전 읽어둠
            result = []
            for task in tasks:
                session.expunge(task)
                result.append(task)

            return result

    def mark_completed(self, task_id: int) -> None:
        """태스크를 완료 상태로 변경한다."""
        with get_session() as session:
            session.execute(
                update(TaskQueue)
                .where(TaskQueue.id == task_id)
                .values(
                    status=TaskStatus.COMPLETED,
                    completed_at=datetime.now(UTC),
                    error_message=None,
                )
            )
        logger.info("태스크 완료: id=%d", task_id)

    def mark_failed(self, task_id: int, error: str) -> bool:
        """태스크를 실패 상태로 변경하고 재시도를 예약한다.

        max_retries 초과 시 DEAD 상태로 변경한다.

        Returns:
            DEAD 상태로 전환되었으면 True.
        """
        with get_session() as session:
            task = session.execute(
                select(TaskQueue).where(TaskQueue.id == task_id)
            ).scalar_one_or_none()

            if task is None:
                return False

            task.retry_count += 1
            task.error_message = error[:1000]

            is_dead = task.retry_count >= task.max_retries
            if is_dead:
                task.status = TaskStatus.DEAD
                logger.error(
                    "태스크 DEAD (재시도 한도 초과): id=%d, type=%s, retries=%d",
                    task_id,
                    task.task_type,
                    task.retry_count,
                )
            else:
                task.status = TaskStatus.FAILED
                delay = settings.worker.retry_base_delay * (2 ** (task.retry_count - 1))
                task.scheduled_at = datetime.now(UTC) + timedelta(seconds=delay)
                logger.warning(
                    "태스크 실패 (재시도 예약): id=%d, type=%s, retry=%d/%d, "
                    "다음 시도=%d초 후, error=%s",
                    task_id,
                    task.task_type,
                    task.retry_count,
                    task.max_retries,
                    delay,
                    error[:200],
                )

            session.flush()
            return is_dead

    def cleanup_old_tasks(self, days: int = 7) -> int:
        """완료/DEAD 태스크 중 N일 이상 지난 것을 삭제한다.

        Returns:
            삭제된 행 수.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        with get_session() as session:
            result = session.execute(
                TaskQueue.__table__.delete().where(
                    TaskQueue.status.in_([TaskStatus.COMPLETED, TaskStatus.DEAD]),
                    TaskQueue.created_at < cutoff,
                )
            )
            count = result.rowcount
            if count > 0:
                logger.info("오래된 태스크 %d건 삭제 (기준: %d일)", count, days)
            return count
