"""ruff/pytest/mypy 출력 → 통합 검증 아티팩트 스키마 TDD."""

from __future__ import annotations

from src.harness.verifier.parsers import (
    parse_pytest_junit,
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


_SAMPLE_JUNIT = '''<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="1" skipped="0" tests="3" time="0.42">
    <testcase classname="tests.test_x" name="test_pass1" time="0.01"/>
    <testcase classname="tests.test_x" name="test_pass2" time="0.01"/>
    <testcase classname="tests.test_y" name="test_fail" time="0.02">
      <failure message="assert 1 == 2">FAIL traceback</failure>
    </testcase>
  </testsuite>
</testsuites>'''


def test_parse_pytest_junit_basic() -> None:
    art = parse_pytest_junit(_SAMPLE_JUNIT)
    assert art.tests == 3
    assert art.failures == 1
    assert art.errors == 0
    assert art.skipped == 0
    assert art.passed is False
    assert art.duration_seconds > 0


def test_parse_pytest_junit_all_pass() -> None:
    raw = (
        '<testsuites><testsuite name="x" tests="2" failures="0" '
        'errors="0" skipped="0" time="0.1"/></testsuites>'
    )
    art = parse_pytest_junit(raw)
    assert art.tests == 2
    assert art.passed is True


def test_parse_pytest_junit_invalid() -> None:
    art = parse_pytest_junit("not xml")
    assert art.passed is False
    assert art.parse_error is not None


def test_pytest_jsonb_serializable() -> None:
    art = parse_pytest_junit(_SAMPLE_JUNIT)
    payload = art.to_jsonb()
    assert payload["tests"] == 3
    assert payload["failures"] == 1
    assert payload["passed"] is False
    assert "failed_tests" in payload
