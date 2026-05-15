"""ruff/pytest/mypy 출력 → 통합 검증 아티팩트 스키마 TDD."""

from __future__ import annotations

from src.harness.verifier.parsers import (
    parse_ruff_json,
)


def test_parse_ruff_empty() -> None:
    artifact = parse_ruff_json("[]")
    assert artifact.violations == []
    assert artifact.passed is True
    assert artifact.violation_count == 0


def test_parse_ruff_with_violations() -> None:
    raw = """[
      {
        "code": "DTZ005",
        "message": "datetime.now() without tz",
        "filename": "src/engine.py",
        "location": {"row": 217, "column": 15}
      },
      {
        "code": "F401",
        "message": "unused import",
        "filename": "src/x.py",
        "location": {"row": 3, "column": 1}
      }
    ]"""
    artifact = parse_ruff_json(raw)
    assert artifact.violation_count == 2
    assert artifact.passed is False
    codes = [v.code for v in artifact.violations]
    assert "DTZ005" in codes
    assert "F401" in codes


def test_ruff_jsonb_serializable() -> None:
    artifact = parse_ruff_json("[]")
    payload = artifact.to_jsonb()
    assert payload == {"passed": True, "violation_count": 0, "violations": []}


def test_parse_ruff_invalid_json_marks_fail() -> None:
    artifact = parse_ruff_json("not json")
    assert artifact.passed is False
    assert artifact.violation_count == 0
    assert artifact.parse_error is not None
