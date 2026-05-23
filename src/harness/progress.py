"""claude-progress.json v1 스키마와 load/save 헬퍼.

매 사이클의 단일 상태 파일. Initializer가 생성하고 모든 워커가 읽는다.
스키마 변경 시 v1 → v2로 bump하고 본 모듈을 호환 어댑터로 만든다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class InitializerCheckResult(StrEnum):
    PASS = "pass"  # noqa: S105  # 상태값(점검 결과)이며 자격증명 아님
    FAIL = "fail"
    SKIP = "skip"


class InitializerCheck(BaseModel):
    """환경 점검 항목 1건."""

    name: str
    result: InitializerCheckResult
    detail: str | None = None


class StateTransition(BaseModel):
    """제안서 상태 전이 1건."""

    path: str
    from_state: str
    to_state: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = None


# 상태 라벨 → CycleProgress의 현재 상태 리스트 필드명.
# 제안서 상태 머신은 implemented를 쓰지만 집계 리스트는 completed이며,
# ready는 아직 큐에 적재 전이라 pending 리스트로 묶는다.
_STATE_LIST_FIELD: dict[str, str] = {
    "pending": "pending",
    "ready": "pending",
    "in_flight": "in_flight",
    "implemented": "completed",
    "completed": "completed",
    "failed": "failed",
    "skipped": "skipped",
}


class CycleProgress(BaseModel):
    """단일 사이클의 진행 상태."""

    schema_version: int = SCHEMA_VERSION
    cycle_id: str
    started_at: datetime
    env: Literal["virtual", "real"]
    last_safe_tag: str | None = None
    initializer_checks: list[InitializerCheck] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    in_flight: list[str] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    history: list[StateTransition] = Field(default_factory=list)

    def transition(
        self,
        path: str,
        *,
        from_state: str,
        to_state: str,
        reason: str | None = None,
    ) -> None:
        """제안서 상태 전이를 기록한다.

        history에 1건 append하고, 현재 상태 리스트(pending/in_flight/completed/
        failed/skipped)도 from→to로 이동시킨다. 리스트를 유지해야 orchestrator·
        텔레그램 상태가 카운트를 정확히 산출한다(과거엔 history만 남기고 리스트는
        비어 있어 completed/failed/skipped가 항상 0으로 보고됐다).
        """
        self.history.append(
            StateTransition(
                path=path,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
            )
        )
        from_field = _STATE_LIST_FIELD.get(from_state)
        if from_field is not None:
            from_list: list[str] = getattr(self, from_field)
            if path in from_list:
                from_list.remove(path)
        to_field = _STATE_LIST_FIELD.get(to_state)
        if to_field is not None:
            to_list: list[str] = getattr(self, to_field)
            if path not in to_list:
                to_list.append(path)


def load_progress(path: Path) -> CycleProgress | None:
    """파일이 없거나 비어 있으면 None."""
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return CycleProgress.model_validate_json(raw)


def save_progress(path: Path, progress: CycleProgress) -> None:
    """JSON으로 저장. 상위 디렉토리는 자동 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        progress.model_dump_json(indent=2),
        encoding="utf-8",
    )
