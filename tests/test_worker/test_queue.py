"""TaskQueueService 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, TaskQueue, TaskStatus
from src.worker.queue import TaskQueueService


@pytest.fixture()
def session() -> Session:
    """SQLite in-memory 세션을 생성한다."""
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.close()
    engine.dispose()


@pytest.fixture()
def queue_service(session, monkeypatch):
    """TaskQueueService를 테스트 세션으로 패치한다."""
    from src.worker import queue as queue_mod

    # get_session을 테스트 세션 반환하는 컨텍스트매니저로 교체
    class _FakeCtx:
        def __enter__(self_ctx):
            return session

        def __exit__(self_ctx, *args):
            session.commit()

    monkeypatch.setattr(queue_mod, "get_session", lambda: _FakeCtx())
    return TaskQueueService()


class TestEnqueue:
    """enqueue 메서드 테스트."""

    def test_enqueue_basic(self, queue_service, session):
        """기본 태스크 등록이 정상 동작한다."""
        task_id = queue_service.enqueue(
            task_type="calendar_event",
            payload={"trade_date": "2026-04-15"},
            priority=1,
        )
        assert task_id is not None
        assert task_id > 0

        task = session.get(TaskQueue, task_id)
        assert task is not None
        assert task.task_type == "calendar_event"
        assert task.status == TaskStatus.PENDING
        assert task.priority == 1
        assert task.retry_count == 0

    def test_enqueue_idempotency(self, queue_service, session):
        """동일 idempotency_key로 중복 등록이 방지된다."""
        id1 = queue_service.enqueue(
            task_type="calendar_event",
            payload={"date": "2026-04-15"},
            idempotency_key="cal_2026-04-15",
        )
        id2 = queue_service.enqueue(
            task_type="calendar_event",
            payload={"date": "2026-04-15"},
            idempotency_key="cal_2026-04-15",
        )
        assert id1 is not None
        assert id2 is None


class TestDequeue:
    """dequeue 메서드 테스트."""

    def test_dequeue_pending(self, queue_service, session):
        """PENDING 태스크가 정상적으로 dequeue된다."""
        queue_service.enqueue("test_task", {"key": "val"})

        tasks = queue_service.dequeue(batch_size=5)
        assert len(tasks) == 1
        assert tasks[0].task_type == "test_task"
        assert tasks[0].status == TaskStatus.RUNNING

    def test_dequeue_priority_order(self, queue_service, session):
        """우선순위가 높은 태스크가 먼저 dequeue된다."""
        queue_service.enqueue("low", {"p": "low"}, priority=1)
        queue_service.enqueue("high", {"p": "high"}, priority=10)

        tasks = queue_service.dequeue(batch_size=5)
        assert len(tasks) == 2
        assert tasks[0].task_type == "high"
        assert tasks[1].task_type == "low"


class TestMarkCompleted:
    """mark_completed 메서드 테스트."""

    def test_mark_completed(self, queue_service, session):
        """태스크를 COMPLETED로 변경할 수 있다."""
        task_id = queue_service.enqueue("test", {"k": "v"})
        queue_service.mark_completed(task_id)

        task = session.get(TaskQueue, task_id)
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None


class TestMarkFailed:
    """mark_failed 메서드 테스트."""

    def test_mark_failed_with_retry(self, queue_service, session):
        """실패 시 retry_count가 증가하고 FAILED 상태가 된다."""
        task_id = queue_service.enqueue(
            "test", {"k": "v"}, max_retries=3
        )
        queue_service.mark_failed(task_id, "네트워크 에러")

        task = session.get(TaskQueue, task_id)
        assert task.status == TaskStatus.FAILED
        assert task.retry_count == 1
        assert "네트워크 에러" in task.error_message

    def test_mark_dead_on_max_retries(self, queue_service, session):
        """max_retries 초과 시 DEAD 상태가 된다."""
        task_id = queue_service.enqueue(
            "test", {"k": "v"}, max_retries=1
        )
        queue_service.mark_failed(task_id, "에러1")

        task = session.get(TaskQueue, task_id)
        assert task.status == TaskStatus.DEAD
        assert task.retry_count == 1
