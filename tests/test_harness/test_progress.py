"""claude-progress.json 스키마 TDD."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.harness.progress import (
    CycleProgress,
    InitializerCheck,
    InitializerCheckResult,
    load_progress,
    save_progress,
)


def test_create_minimal_cycle():
    c = CycleProgress(
        cycle_id="c-1",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
    )
    assert c.cycle_id == "c-1"
    assert c.initializer_checks == []
    assert c.pending == []
    assert c.history == []


def test_roundtrip_save_load(tmp_path: Path):
    c = CycleProgress(
        cycle_id="c-2",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
        last_safe_tag="v0.2.4",
    )
    c.initializer_checks.append(
        InitializerCheck(name="alembic_head", result=InitializerCheckResult.PASS)
    )
    c.pending.append("docs/proposals/x.md")
    p = tmp_path / "claude-progress.json"
    save_progress(p, c)
    loaded = load_progress(p)
    assert loaded.cycle_id == "c-2"
    assert loaded.last_safe_tag == "v0.2.4"
    assert loaded.initializer_checks[0].name == "alembic_head"


def test_transition_records_history():
    c = CycleProgress(
        cycle_id="c-3",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
    )
    c.transition("docs/proposals/a.md", from_state="pending", to_state="in_flight")
    assert len(c.history) == 1
    assert c.history[0].path == "docs/proposals/a.md"
    assert c.history[0].to_state == "in_flight"


def _fresh() -> CycleProgress:
    return CycleProgress(
        cycle_id="c-x",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="virtual",
    )


def test_transition_moves_into_in_flight_list():
    """ready→in_flight 전이가 in_flight 리스트를 채운다."""
    c = _fresh()
    c.transition("docs/proposals/a.md", from_state="ready", to_state="in_flight")
    assert c.in_flight == ["docs/proposals/a.md"]


def test_transition_implemented_counts_as_completed():
    """in_flight→implemented는 completed 리스트로 집계되고 in_flight에서 빠진다."""
    c = _fresh()
    c.transition("docs/proposals/a.md", from_state="ready", to_state="in_flight")
    c.transition("docs/proposals/a.md", from_state="in_flight", to_state="implemented")
    assert c.in_flight == []
    assert c.completed == ["docs/proposals/a.md"]


def test_transition_failed_list():
    """in_flight→failed는 failed 리스트로 이동."""
    c = _fresh()
    c.transition("docs/proposals/a.md", from_state="ready", to_state="in_flight")
    c.transition(
        "docs/proposals/a.md", from_state="in_flight", to_state="failed",
        reason="verify fail",
    )
    assert c.in_flight == []
    assert c.failed == ["docs/proposals/a.md"]


def test_transition_skipped_list():
    """ready→skipped는 skipped 리스트를 채운다(안전 게이트 거절 경로)."""
    c = _fresh()
    c.transition(
        "docs/proposals/a.md", from_state="ready", to_state="skipped",
        reason="safety_gate_violation",
    )
    assert c.skipped == ["docs/proposals/a.md"]


def test_transition_no_duplicate_on_repeat():
    """동일 to 전이를 반복해도 리스트에 중복 적재되지 않는다."""
    c = _fresh()
    c.transition("docs/proposals/a.md", from_state="ready", to_state="skipped")
    c.transition("docs/proposals/a.md", from_state="ready", to_state="skipped")
    assert c.skipped == ["docs/proposals/a.md"]


def test_transition_unknown_state_only_history():
    """미지의 상태 라벨은 리스트를 건드리지 않고 history만 남긴다."""
    c = _fresh()
    c.transition("docs/proposals/a.md", from_state="ready", to_state="weird")
    assert c.completed == [] and c.failed == [] and c.skipped == []
    assert len(c.history) == 1


def test_transition_counts_reflect_mixed_cycle():
    """한 사이클의 혼합 결과가 카운트(리스트 길이)에 정확히 반영된다."""
    c = _fresh()
    # a: 구현 성공
    c.transition("a.md", from_state="ready", to_state="in_flight")
    c.transition("a.md", from_state="in_flight", to_state="implemented")
    # b: 실패
    c.transition("b.md", from_state="ready", to_state="in_flight")
    c.transition("b.md", from_state="in_flight", to_state="failed")
    # c, d: 안전 게이트 스킵
    c.transition("c.md", from_state="ready", to_state="skipped")
    c.transition("d.md", from_state="ready", to_state="skipped")
    assert len(c.completed) == 1
    assert len(c.failed) == 1
    assert len(c.skipped) == 2
    assert c.in_flight == []


def test_load_missing_file_returns_none(tmp_path: Path):
    assert load_progress(tmp_path / "nope.json") is None


def test_save_creates_parent_dir(tmp_path: Path):
    target = tmp_path / "deep" / "deeper" / "progress.json"
    c = CycleProgress(
        cycle_id="c-4",
        started_at=datetime(2026, 5, 14, 19, 0, tzinfo=UTC),
        env="real",
    )
    save_progress(target, c)
    assert target.exists()
