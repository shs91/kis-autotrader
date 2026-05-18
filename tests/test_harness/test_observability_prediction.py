"""제안서 prediction 파싱 TDD."""

from __future__ import annotations

from pathlib import Path

from src.harness.observability.prediction import parse_prediction


def test_parse_full_prediction_block(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    f.write_text(
        "# 제목\n\n## 기대 효과\n"
        "- win_rate_delta_pp: +2.0\n"
        "- error_count_delta_ratio: -0.30\n"
        "- signal_count_delta: +50\n\n"
        "## 본문\n…",
        encoding="utf-8",
    )
    pred = parse_prediction(f)
    assert pred == {
        "win_rate_delta_pp": 2.0,
        "error_count_delta_ratio": -0.30,
        "signal_count_delta": 50.0,
    }


def test_parse_missing_section_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "y.md"
    f.write_text("# 제목\n\n## 메타데이터\n- 상태: ready\n", encoding="utf-8")
    assert parse_prediction(f) == {}


def test_parse_ignores_non_numeric_lines(tmp_path: Path) -> None:
    f = tmp_path / "z.md"
    f.write_text(
        "# X\n\n## 기대 효과\n"
        "- win_rate_delta_pp: +1.5\n"
        "- 안정성 개선 (정성)\n"
        "- error_count_delta_ratio: not measured\n",
        encoding="utf-8",
    )
    pred = parse_prediction(f)
    assert pred == {"win_rate_delta_pp": 1.5}
