"""tests/eval/golden_proposals/<G##_*>/manifest.json 로더.

manifest 스키마:
    id, proposal_path, category, summary, invariant:{ type, ... type별 파라미터 }
지원 invariant.type:
    - regex_absent: file 경로 + pattern. 파일 내용에 pattern이 매칭되면 회귀
    - regex_present: file + pattern. 매칭이 없으면 회귀 (필요한 코드가 사라졌을 때)
    - ruff_rule: rule + target. target에서 rule 위반이 있으면 회귀
    - pytest_passes: nodeid. 해당 테스트가 실패하면 회귀
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class InvariantType(StrEnum):
    REGEX_ABSENT = "regex_absent"
    REGEX_PRESENT = "regex_present"
    RUFF_RULE = "ruff_rule"
    PYTEST_PASSES = "pytest_passes"


@dataclass(frozen=True)
class Invariant:
    """단일 invariant 명세 (type + 타입별 파라미터)."""

    type: InvariantType
    params: dict[str, Any]


@dataclass(frozen=True)
class GoldenCase:
    """골든 회귀 케이스 1건."""

    id: str
    proposal_path: str
    category: str
    summary: str
    invariant: Invariant


def _parse_invariant(raw: dict[str, Any], *, strict: bool) -> Invariant | None:
    """raw invariant dict → Invariant 객체. strict=True면 unknown type에 raise."""
    raw_type = raw.get("type", "")
    try:
        itype = InvariantType(raw_type)
    except ValueError:
        if strict:
            raise ValueError(f"unknown invariant type: {raw_type}") from None
        logger.warning("unknown invariant type %r, skipping", raw_type)
        return None
    params = {k: v for k, v in raw.items() if k != "type"}
    return Invariant(type=itype, params=params)


def load_cases(directory: Path, *, strict: bool = False) -> list[GoldenCase]:
    """디렉토리의 모든 골든 케이스를 로드. invalid 매니페스트는 strict=False 시 skip."""
    cases: list[GoldenCase] = []
    for case_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
        manifest = case_dir / "manifest.json"
        if not manifest.exists():
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            if strict:
                raise
            logger.warning("manifest invalid (%s): %s", manifest, e)
            continue
        inv_raw = raw.get("invariant") or {}
        if not isinstance(inv_raw, dict):
            continue
        inv = _parse_invariant(inv_raw, strict=strict)
        if inv is None:
            continue
        cases.append(
            GoldenCase(
                id=str(raw.get("id", case_dir.name)),
                proposal_path=str(raw.get("proposal_path", "")),
                category=str(raw.get("category", "")),
                summary=str(raw.get("summary", "")),
                invariant=inv,
            )
        )
    return cases
