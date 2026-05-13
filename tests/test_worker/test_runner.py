"""WorkerRunner 단위 테스트."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.worker.handlers import TaskHandler
from src.worker.runner import WorkerRunner


class _DummyHandler(TaskHandler):
    """테스트용 더미 핸들러."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_payload: dict | None = None

    async def execute(self, payload: dict) -> None:
        self.call_count += 1
        self.last_payload = payload


class _FailingHandler(TaskHandler):
    """항상 실패하는 더미 핸들러."""

    async def execute(self, payload: dict) -> None:
        raise RuntimeError("테스트 에러")


class TestWorkerRunner:
    """WorkerRunner 테스트."""

    def test_register_handler(self):
        """핸들러 등록이 정상 동작한다."""
        runner = WorkerRunner(poll_interval=1)
        handler = _DummyHandler()
        runner.register_handler("test_task", handler)

        assert "test_task" in runner._handlers

    @pytest.mark.asyncio()
    async def test_process_task_success(self):
        """태스크 처리 성공 시 mark_completed가 호출된다."""
        runner = WorkerRunner(poll_interval=1)
        handler = _DummyHandler()
        runner.register_handler("test_task", handler)

        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.task_type = "test_task"
        mock_task.payload = {"key": "value"}

        with patch.object(runner._queue, "mark_completed") as mock_complete:
            await runner._process_task(mock_task)

        assert handler.call_count == 1
        assert handler.last_payload == {"key": "value"}
        mock_complete.assert_called_once_with(1)

    @pytest.mark.asyncio()
    async def test_process_task_failure(self):
        """태스크 처리 실패 시 mark_failed가 호출된다."""
        runner = WorkerRunner(poll_interval=1)
        handler = _FailingHandler()
        runner.register_handler("fail_task", handler)

        mock_task = MagicMock()
        mock_task.id = 2
        mock_task.task_type = "fail_task"
        mock_task.payload = {}

        with patch.object(runner._queue, "mark_failed") as mock_fail:
            await runner._process_task(mock_task)

        mock_fail.assert_called_once()
        call_args = mock_fail.call_args
        assert call_args[0][0] == 2
        assert "RuntimeError" in call_args[0][1]

    @pytest.mark.asyncio()
    async def test_process_task_unknown_type(self):
        """미등록 태스크 타입은 mark_failed로 처리된다."""
        runner = WorkerRunner(poll_interval=1)

        mock_task = MagicMock()
        mock_task.id = 3
        mock_task.task_type = "unknown"
        mock_task.payload = {}

        with patch.object(runner._queue, "mark_failed") as mock_fail:
            await runner._process_task(mock_task)

        mock_fail.assert_called_once()
        assert "미등록 핸들러" in mock_fail.call_args[0][1]

    def test_stop(self):
        """stop() 호출 시 _running이 False가 된다."""
        runner = WorkerRunner(poll_interval=1)
        runner._running = True
        runner.stop()
        assert runner._running is False

    @pytest.mark.asyncio()
    async def test_notify_dead_task_uses_correct_signature(self):
        """DEAD 태스크 알림이 notify_error를 (context, error) 두 인자로 호출한다."""
        runner = WorkerRunner(poll_interval=1)

        mock_notifier = AsyncMock()
        mock_notifier.notify_error = AsyncMock()
        with patch(
            "src.notify.telegram.TelegramNotifier", return_value=mock_notifier
        ):
            await runner._notify_dead_task(
                task_id=42,
                task_type="record_trade",
                error="DB connection lost",
            )

        mock_notifier.notify_error.assert_called_once()
        args, kwargs = mock_notifier.notify_error.call_args
        all_params = tuple(args) + tuple(kwargs.values())
        assert len(all_params) == 2
        joined = " | ".join(str(p) for p in all_params)
        assert "Worker DEAD" in joined
        assert "id=42" in joined
        assert "record_trade" in joined
        assert "DB connection lost" in joined
