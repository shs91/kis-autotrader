"""ruff/pytest/mypy 출력 → 통합 검증 아티팩트 스키마.

각 파서는 raw 출력을 받아 `<Tool>Artifact` 객체를 반환.
스키마는 `.to_jsonb()`로 직렬화되며 `implementation_logs.verification` JSONB에 저장.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET


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


@dataclass(frozen=True)
class PytestFailure:
    """pytest 단일 실패 케이스."""

    classname: str
    name: str
    message: str


@dataclass
class PytestArtifact:
    """pytest 검증 결과 아티팩트."""

    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    failed_tests: list[PytestFailure] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def passed(self) -> bool:
        """파싱 성공 + 실패/에러 0건일 때만 통과."""
        return (
            self.parse_error is None
            and self.failures == 0
            and self.errors == 0
        )

    def to_jsonb(self) -> dict[str, Any]:
        """JSONB 직렬화 — parse_error는 있을 때만 포함."""
        return {
            "passed": self.passed,
            "tests": self.tests,
            "failures": self.failures,
            "errors": self.errors,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "failed_tests": [
                {"classname": f.classname, "name": f.name, "message": f.message}
                for f in self.failed_tests
            ],
            **({"parse_error": self.parse_error} if self.parse_error else {}),
        }


def parse_pytest_junit(raw: str) -> PytestArtifact:
    """pytest `--junitxml` 출력 파일 내용을 PytestArtifact로 변환."""
    try:
        root = ET.fromstring(raw)  # noqa: S314  # pytest 자체가 생성한 신뢰 가능 출력
    except ET.ParseError as e:
        return PytestArtifact(parse_error=f"xml parse: {e!s:.100}")

    # 최상위가 testsuites 이면 첫 testsuite 사용, 아니면 root 자체
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        return PytestArtifact(parse_error="no testsuite element")

    def _int(attr: str) -> int:
        try:
            return int(suite.attrib.get(attr, "0"))
        except (TypeError, ValueError):
            return 0

    def _float(attr: str) -> float:
        try:
            return float(suite.attrib.get(attr, "0"))
        except (TypeError, ValueError):
            return 0.0

    failed: list[PytestFailure] = []
    for tc in suite.findall("testcase"):
        f_elem = tc.find("failure")
        if f_elem is not None:
            failed.append(
                PytestFailure(
                    classname=tc.attrib.get("classname", ""),
                    name=tc.attrib.get("name", ""),
                    message=(f_elem.attrib.get("message") or "")[:200],
                )
            )

    return PytestArtifact(
        tests=_int("tests"),
        failures=_int("failures"),
        errors=_int("errors"),
        skipped=_int("skipped"),
        duration_seconds=_float("time"),
        failed_tests=failed,
    )


_MYPY_ERROR_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):\s*error:\s*(?P<msg>.*?)(?:\s+\[(?P<code>[^\]]+)\])?$"
)
_MYPY_SUMMARY_FAIL = re.compile(
    r"Found\s+(\d+)\s+errors?\s+in\s+\d+\s+files?\s+\(checked\s+(\d+)"
)
_MYPY_SUMMARY_OK = re.compile(r"Success:\s*no issues found in\s+(\d+)\s+source files?")


@dataclass(frozen=True)
class MypyError:
    """mypy 단일 에러."""

    file: str
    line: int
    message: str
    code: str


@dataclass
class MypyArtifact:
    """mypy 검증 결과 아티팩트."""

    errors: list[MypyError] = field(default_factory=list)
    files_checked: int = 0
    parse_error: str | None = None
    _passed_override: bool | None = None

    @property
    def error_count(self) -> int:
        """에러 개수."""
        return len(self.errors)

    @property
    def passed(self) -> bool:
        """파싱 성공 + 에러 0건 + files_checked > 0 일 때만 통과."""
        if self._passed_override is not None:
            return self._passed_override
        return (
            self.parse_error is None
            and self.error_count == 0
            and self.files_checked > 0
        )

    def to_jsonb(self) -> dict[str, Any]:
        """JSONB 직렬화 — parse_error는 있을 때만 포함."""
        return {
            "passed": self.passed,
            "error_count": self.error_count,
            "files_checked": self.files_checked,
            "errors": [
                {"file": e.file, "line": e.line, "message": e.message, "code": e.code}
                for e in self.errors
            ],
            **({"parse_error": self.parse_error} if self.parse_error else {}),
        }


def parse_mypy_text(raw: str) -> MypyArtifact:
    """mypy stdout(text)을 MypyArtifact로 변환."""
    raw = raw.strip()
    if not raw:
        return MypyArtifact(parse_error="empty output")

    errors: list[MypyError] = []
    files_checked = 0
    for line_raw in raw.splitlines():
        line = line_raw.strip()
        m = _MYPY_ERROR_RE.match(line)
        if m:
            errors.append(
                MypyError(
                    file=m.group("file"),
                    line=int(m.group("line")),
                    message=m.group("msg").strip(),
                    code=m.group("code") or "",
                )
            )
            continue
        m_ok = _MYPY_SUMMARY_OK.match(line)
        if m_ok:
            files_checked = int(m_ok.group(1))
            continue
        m_fail = _MYPY_SUMMARY_FAIL.search(line)
        if m_fail:
            files_checked = int(m_fail.group(2))
            continue

    # 에러도 없고 summary 라인도 없는 경우 (오래된 mypy / 잘못된 출력)
    if not files_checked and not errors:
        return MypyArtifact(parse_error="no mypy summary found")
    return MypyArtifact(errors=errors, files_checked=files_checked)
