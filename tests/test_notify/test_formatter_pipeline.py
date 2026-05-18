"""Telegram 사이클 결산 3섹션 카드 TDD."""

from __future__ import annotations

from src.notify.formatter import format_pipeline_summary


def test_format_with_all_sections() -> None:
    msg = format_pipeline_summary(
        cycle_id="auto-20260515-170000",
        applied=[{"title": "스크리닝 임계값 조정", "version": "0.2.5"}],
        recurrence_risks=[{"component": "code/strategy", "edit_count": 4}],
        prediction_misses=[{"category": "param_tuning", "metric": "win_rate_delta_pp"}],
    )
    assert "auto-20260515-170000" in msg
    assert "오늘 적용" in msg
    assert "스크리닝 임계값" in msg
    assert "회귀 위험" in msg
    assert "code/strategy" in msg
    assert "예측 미달" in msg


def test_format_with_empty_sections_shows_no_data() -> None:
    msg = format_pipeline_summary(
        cycle_id="c-x",
        applied=[],
        recurrence_risks=[],
        prediction_misses=[],
    )
    assert "변경 없음" in msg
    assert "회귀 위험 없음" in msg
    assert "예측 미달 없음" in msg


def test_truncates_long_lists() -> None:
    applied = [{"title": f"T{i}", "version": "0.0.0"} for i in range(20)]
    msg = format_pipeline_summary(
        cycle_id="c-y", applied=applied,
        recurrence_risks=[], prediction_misses=[],
    )
    # 상위 N개만 노출
    assert msg.count("T0") == 1
    # 너무 길어지지 않도록 절단 표시
    assert "외 " in msg or "and " in msg or "..." in msg
