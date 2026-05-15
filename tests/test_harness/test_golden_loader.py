"""Golden set loader TDD."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.harness.golden.loader import (
    GoldenCase,
    InvariantType,
    load_cases,
)


def _write_case(parent: Path, cid: str, invariant: dict) -> Path:
    case = parent / cid
    case.mkdir()
    (case / "manifest.json").write_text(
        json.dumps(
            {
                "id": cid,
                "proposal_path": f"docs/proposals/x_{cid}.md",
                "category": "bug_fix",
                "summary": f"summary for {cid}",
                "invariant": invariant,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return case


def test_load_single_case(tmp_path: Path):
    _write_case(
        tmp_path,
        "G01_x",
        {"type": "regex_absent", "file": "src/x.py", "pattern": r"datetime\.utcnow\("},
    )
    cases = load_cases(tmp_path)
    assert len(cases) == 1
    c: GoldenCase = cases[0]
    assert c.id == "G01_x"
    assert c.invariant.type == InvariantType.REGEX_ABSENT
    assert c.invariant.params["file"] == "src/x.py"


def test_load_three_invariant_types(tmp_path: Path):
    _write_case(tmp_path, "G01", {"type": "regex_absent", "file": "src/a.py", "pattern": "X"})
    _write_case(tmp_path, "G02", {"type": "ruff_rule", "rule": "DTZ005", "target": "src/"})
    _write_case(tmp_path, "G03", {"type": "pytest_passes", "nodeid": "tests/x.py::test_y"})
    cases = load_cases(tmp_path)
    assert {c.invariant.type for c in cases} == {
        InvariantType.REGEX_ABSENT,
        InvariantType.RUFF_RULE,
        InvariantType.PYTEST_PASSES,
    }


def test_load_invalid_manifest_skipped_with_warning(tmp_path: Path):
    bad = tmp_path / "G99_bad"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json}", encoding="utf-8")
    cases = load_cases(tmp_path)
    assert cases == []


def test_unknown_invariant_type_raises(tmp_path: Path):
    _write_case(tmp_path, "Gxx", {"type": "made_up", "x": 1})
    with pytest.raises(ValueError):
        load_cases(tmp_path, strict=True)
