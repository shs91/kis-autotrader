"""Trajectory 적재 헬퍼.

`append_entry`는 단발 호출용. `time_step`은 with-context로 시간 측정 + 예외 처리.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.db.models import TrajectoryStatus, TrajectoryStep


def append_entry(
    *,
    repo: Any,
    cycle_id: str,
    step: TrajectoryStep,
    status: TrajectoryStatus,
    started_at: datetime,
    completed_at: datetime,
    proposal_path: str | None = None,
    agent: str | None = None,
    input_summary: str | None = None,
    result_summary: str | None = None,
    token_usage_input: int | None = None,
    token_usage_output: int | None = None,
    meta: dict[str, Any] | None = None,
) -> Any:
    """trajectory entry 1건을 repo.append로 위임."""
    return repo.append(
        cycle_id=cycle_id,
        step=step,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        proposal_path=proposal_path,
        agent=agent,
        input_summary=input_summary,
        result_summary=result_summary,
        token_usage_input=token_usage_input,
        token_usage_output=token_usage_output,
        meta=meta,
    )


@dataclass
class TimeStepContext:
    """time_step with-context의 부속 객체.

    호출자가 set_status/set_result_summary로 결과를 표시한다.
    """

    cycle_id: str
    step: TrajectoryStep
    started_at: datetime
    status: TrajectoryStatus = TrajectoryStatus.OK
    result_summary: str | None = None
    proposal_path: str | None = None
    agent: str | None = None

    def set_status(self, status: TrajectoryStatus) -> None:
        """status 설정."""
        self.status = status

    def set_result_summary(self, summary: str) -> None:
        """result_summary 설정."""
        self.result_summary = summary

    def set_proposal_path(self, path: str) -> None:
        """proposal_path 설정."""
        self.proposal_path = path

    def set_agent(self, agent: str) -> None:
        """agent 설정."""
        self.agent = agent


@contextmanager
def time_step(
    *,
    repo: Any,
    cycle_id: str,
    step: TrajectoryStep,
) -> Iterator[TimeStepContext]:
    """with-context로 trajectory entry 시간 측정.

    예외 발생 시 status=FAIL + 예외 메시지를 result_summary에 기록 후 re-raise.
    """
    started = datetime.now(UTC)
    perf_start = time.perf_counter()
    ctx = TimeStepContext(cycle_id=cycle_id, step=step, started_at=started)
    raised: BaseException | None = None
    try:
        yield ctx
    except BaseException as exc:
        ctx.status = TrajectoryStatus.FAIL
        ctx.result_summary = (
            (ctx.result_summary + " | " if ctx.result_summary else "")
            + f"exception: {exc!s:.200}"
        )
        raised = exc
    completed = datetime.now(UTC)
    duration = time.perf_counter() - perf_start
    repo.append(
        cycle_id=cycle_id,
        step=step,
        status=ctx.status,
        started_at=started,
        completed_at=completed,
        proposal_path=ctx.proposal_path,
        agent=ctx.agent,
        result_summary=ctx.result_summary,
        duration_seconds=duration,
    )
    if raised is not None:
        raise raised
