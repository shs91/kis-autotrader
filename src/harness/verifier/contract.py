"""Default-FAIL contract — 모든 증거가 갖춰지고 각자 pass일 때만 통과.

증거 4종: pytest / mypy / ruff / diff.
하나라도 None이거나 자체 passed=False면 contract FAIL.
diff.file_count가 임계값 초과면 통과+경고.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.harness.verifier.diff import DiffSummary
from src.harness.verifier.parsers import (
    MypyArtifact,
    PytestArtifact,
    RuffArtifact,
)

_DEFAULT_FILE_THRESHOLD = 5


@dataclass
class ContractResult:
    """Contract 평가 결과 — JSONB 직렬화 대상."""

    passed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_jsonb(self) -> dict[str, Any]:
        """`implementation_logs.verification` JSONB 페이로드로 변환."""
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "artifacts": self.artifacts,
        }


def evaluate_contract(
    *,
    pytest: PytestArtifact | None,
    mypy: MypyArtifact | None,
    ruff: RuffArtifact | None,
    diff: DiffSummary | None,
    file_count_threshold: int = _DEFAULT_FILE_THRESHOLD,
) -> ContractResult:
    """4종 아티팩트를 받아 Default-FAIL 규칙으로 평가한다.

    - 각 아티팩트가 None 또는 자체 ``passed=False``면 reason 추가.
    - diff가 비어 있으면(file_count==0) reason 추가.
    - diff.file_count가 threshold 초과면 warning만 추가 (통과는 유지).
    - 모든 reason이 비어야 ``passed=True``.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    if pytest is None:
        reasons.append("pytest artifact missing")
    elif not pytest.passed:
        reasons.append(
            f"pytest failed (failures={pytest.failures}, errors={pytest.errors})"
        )

    if mypy is None:
        reasons.append("mypy artifact missing")
    elif not mypy.passed:
        reasons.append(f"mypy failed (errors={mypy.error_count})")

    if ruff is None:
        reasons.append("ruff artifact missing")
    elif not ruff.passed:
        reasons.append(f"ruff failed (violations={ruff.violation_count})")

    if diff is None or diff.file_count == 0:
        reasons.append("diff artifact missing or empty")
    elif diff.exceeds_threshold(file_count_threshold):
        warnings.append(
            f"file_count={diff.file_count} exceeds threshold {file_count_threshold}"
        )

    artifacts: dict[str, Any] = {
        "pytest": pytest.to_jsonb() if pytest else None,
        "mypy": mypy.to_jsonb() if mypy else None,
        "ruff": ruff.to_jsonb() if ruff else None,
        "diff": diff.to_jsonb() if diff else None,
    }

    return ContractResult(
        passed=not reasons,
        reasons=reasons,
        warnings=warnings,
        artifacts=artifacts,
    )
