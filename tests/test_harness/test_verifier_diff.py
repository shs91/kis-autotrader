"""git diff → changed_files JSONB 스키마 변환 TDD."""

from __future__ import annotations

from src.harness.verifier.diff import (
    DiffSummary,
    parse_numstat,
)


def test_parse_numstat_basic() -> None:
    raw = "10\t5\tsrc/strategy/rsi.py\n0\t12\tdocs/old.md\n"
    diff = parse_numstat(raw)
    assert isinstance(diff, DiffSummary)
    assert len(diff.files) == 2
    f0 = diff.files[0]
    assert f0.path == "src/strategy/rsi.py"
    assert f0.additions == 10
    assert f0.deletions == 5
    assert diff.total_additions == 10
    assert diff.total_deletions == 17


def test_parse_numstat_ignores_binary() -> None:
    raw = "-\t-\tsrc/static/logo.png\n5\t3\tsrc/strategy/x.py\n"
    diff = parse_numstat(raw)
    assert len(diff.files) == 1  # binary 제외
    assert diff.files[0].path == "src/strategy/x.py"


def test_parse_numstat_empty() -> None:
    diff = parse_numstat("")
    assert diff.files == []
    assert diff.total_additions == 0


def test_jsonb_serializable() -> None:
    raw = "10\t5\tsrc/strategy/rsi.py\n"
    diff = parse_numstat(raw)
    payload = diff.to_jsonb()
    assert payload == {
        "files": [
            {
                "path": "src/strategy/rsi.py",
                "additions": 10,
                "deletions": 5,
                "component": "code/strategy",
            }
        ],
        "total_additions": 10,
        "total_deletions": 5,
        "file_count": 1,
    }


def test_changed_file_count_threshold() -> None:
    raw = "\n".join(f"1\t1\tsrc/f{i}.py" for i in range(6))
    diff = parse_numstat(raw)
    assert diff.file_count == 6
    assert diff.exceeds_threshold(5) is True
    assert diff.exceeds_threshold(10) is False
