"""ruff/pytest/mypy 출력 → 통합 검증 아티팩트 스키마.

각 파서는 raw 출력을 받아 `<Tool>Artifact` 객체를 반환.
스키마는 `.to_jsonb()`로 직렬화되며 `implementation_logs.verification` JSONB에 저장.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuffViolation:
    """ruff 단일 위반 사항."""

    code: str
    message: str
    filename: str
    row: int
    column: int


@dataclass
class RuffArtifact:
    """ruff 검증 결과 아티팩트."""

    violations: list[RuffViolation] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def violation_count(self) -> int:
        """위반 개수."""
        return len(self.violations)

    @property
    def passed(self) -> bool:
        """파싱 성공 + 위반 0건일 때만 통과."""
        return self.parse_error is None and self.violation_count == 0

    def to_jsonb(self) -> dict[str, Any]:
        """JSONB 직렬화 — parse_error는 있을 때만 포함."""
        return {
            "passed": self.passed,
            "violation_count": self.violation_count,
            "violations": [
                {
                    "code": v.code,
                    "message": v.message,
                    "filename": v.filename,
                    "row": v.row,
                    "column": v.column,
                }
                for v in self.violations
            ],
            **({"parse_error": self.parse_error} if self.parse_error else {}),
        }


def parse_ruff_json(raw: str) -> RuffArtifact:
    """`ruff check --output-format=json` 출력을 RuffArtifact로 변환."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return RuffArtifact(parse_error=f"json decode: {e!s:.100}")
    if not isinstance(data, list):
        return RuffArtifact(parse_error="expected top-level array")
    violations: list[RuffViolation] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        loc = item.get("location") or {}
        violations.append(
            RuffViolation(
                code=str(item.get("code", "")),
                message=str(item.get("message", "")),
                filename=str(item.get("filename", "")),
                row=int(loc.get("row", 0) or 0),
                column=int(loc.get("column", 0) or 0),
            )
        )
    return RuffArtifact(violations=violations)
