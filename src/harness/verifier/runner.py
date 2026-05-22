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
        """diff을 먼저 수집해 변경된 .py 파일만 ruff/mypy/pytest로 검증한다.

        Phase 3 hotfix D2: 변경분 외 사전 존재 위반이 contract FAIL을 유발하던
        디자인 결함 해결. 변경된 파일에 한정해 검증함으로써 cycle의 신호 정합성을
        높인다. .py 파일이 전혀 변경되지 않은 사이클은 ruff/mypy/pytest 모두
        PASS로 처리 (검증할 대상 없음 = 회귀 없음).
        """
        result = RunnerResult()
        try:
            # 1. diff 먼저 — scope 결정
            result.diff = self._run_diff(base_ref=base_ref, head_ref=head_ref)
            py_files = [
                f.path for f in result.diff.files if f.path.endswith(".py")
            ]
            src_files = [p for p in py_files if not p.startswith("tests/")]
            test_files = [p for p in py_files if p.startswith("tests/")]
            # 2. 변경된 파일에 한정해 검사
            result.ruff = self._run_ruff(py_files)
            result.mypy = self._run_mypy(src_files)
            result.pytest = self._run_pytest(test_files)
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

    def _run_ruff(self, files: list[str]) -> RuffArtifact:
        if not files:
            return RuffArtifact()  # 변경된 .py 파일 없음 → 위반 0건 = PASS
        cp = self._exec(
            ["ruff", "check", *files, "--output-format=json"]
        )
        return parse_ruff_json(cp.stdout)

    def _run_mypy(self, files: list[str]) -> MypyArtifact:
        if not files:
            # 변경된 src .py 없음 → 검사할 대상 없음. files_checked=0이라
            # 기본 passed=False이지만 _passed_override로 PASS 처리
            return MypyArtifact(files_checked=0, _passed_override=True)
        # --no-error-summary는 summary 라인을 제거해 parser가 fail로 인식하므로 제외
        cp = self._exec(
            ["mypy", "--no-pretty", *files]
        )
        # mypy summary는 stderr 또는 stdout 끝에. 합쳐서 파싱
        artifact = parse_mypy_text((cp.stdout or "") + "\n" + (cp.stderr or ""))
        # Phase 3 hotfix D2 완성: mypy는 변경 파일만 타깃해도 import 그래프를 따라
        # 미변경 의존 파일(pandas import-untyped 등 baseline 에러)까지 보고한다.
        # 검증 대상은 '이 diff가 일으킨 회귀'이므로 변경된 파일에서 발생한 에러만
        # 센다. (전역 baseline 에러가 게이트를 구조적으로 항상 FAIL시키던 결함 해결)
        if artifact.parse_error is None and artifact.errors:
            changed = set(files)
            artifact.errors = [e for e in artifact.errors if e.file in changed]
        return artifact

    def _run_pytest(self, files: list[str]) -> PytestArtifact:
        if not files:
            # 변경된 test 파일 없음 → 회귀 검사 대상 없음. 기본 PytestArtifact는
            # tests=0/failures=0이라 passed=True
            return PytestArtifact()
        self._exec(
            [
                "pytest",
                *files,
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
