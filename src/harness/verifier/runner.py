"""Verifier Runner — pytest/mypy/ruff/git diff 실제 실행 + 아티팩트 통합.

각 명령의 raw 출력을 parsers.py로 변환해 RunnerResult로 묶는다.
subprocess 실패는 result.runner_error에 기록 (Default-FAIL이 처리).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from src.harness.verifier.diff import DiffSummary, parse_numstat
from src.harness.verifier.parsers import (
    MypyArtifact,
    PytestArtifact,
    RuffArtifact,
    parse_mypy_text,
    parse_pytest_junit,
    parse_ruff_json,
)


@dataclass
class RunnerResult:
    ruff: RuffArtifact | None = None
    mypy: MypyArtifact | None = None
    pytest: PytestArtifact | None = None
    diff: DiffSummary | None = None
    runner_error: str | None = None
    commands: list[str] = field(default_factory=list)


class VerifierRunner:
    """워크트리 루트에서 pytest/mypy/ruff/diff 명령을 실행하고 아티팩트를 모은다."""

    def __init__(
        self,
        repo_root: Path,
        src_target: str = "src/",
        test_target: str = "tests/",
    ) -> None:
        self.repo_root = repo_root
        self.src_target = src_target
        self.test_target = test_target
        self._junit_path: Path = repo_root / ".verifier-junit.xml"

    def run(self, *, base_ref: str = "HEAD~1", head_ref: str = "HEAD") -> RunnerResult:
        result = RunnerResult()
        try:
            result.ruff = self._run_ruff()
            result.mypy = self._run_mypy()
            result.pytest = self._run_pytest()
            result.diff = self._run_diff(base_ref=base_ref, head_ref=head_ref)
        except subprocess.SubprocessError as e:
            result.runner_error = f"subprocess: {e!s:.200}"
        return result

    def _exec(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            cmd,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )

    def _run_ruff(self) -> RuffArtifact:
        cp = self._exec(
            ["ruff", "check", self.src_target, "--output-format=json"]
        )
        return parse_ruff_json(cp.stdout)

    def _run_mypy(self) -> MypyArtifact:
        cp = self._exec(
            ["mypy", "--no-pretty", "--no-error-summary", self.src_target]
        )
        # mypy summary는 stderr 또는 stdout 끝에. 합쳐서 파싱
        return parse_mypy_text((cp.stdout or "") + "\n" + (cp.stderr or ""))

    def _run_pytest(self) -> PytestArtifact:
        self._exec(
            [
                "pytest",
                self.test_target,
                "-q",
                f"--junitxml={self._junit_path}",
            ]
        )
        if not self._junit_path.exists():
            return PytestArtifact(parse_error="junit file not produced")
        return parse_pytest_junit(self._junit_path.read_text(encoding="utf-8"))

    def _run_diff(self, *, base_ref: str, head_ref: str) -> DiffSummary:
        cp = self._exec(
            ["git", "diff", "--numstat", f"{base_ref}..{head_ref}"]
        )
        return parse_numstat(cp.stdout)
