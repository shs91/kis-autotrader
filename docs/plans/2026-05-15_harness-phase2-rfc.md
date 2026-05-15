# 하네스 Phase 2 — Verifier 분리 + Default-FAIL contract + 골든 회귀 셋 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자동 구현 사이클의 검증 단계를 Implementer(=`claude -p`)에서 분리해 fresh-context Verifier가 pytest/mypy/ruff JSON 아티팩트 4종을 받아 Default-FAIL contract로 자동 채점하고, 그 결과로 `mark_implemented`/`mark_failed`와 service restart를 결정한다. 골든 회귀 셋 10건이 사이클 시작 직전 동일 카테고리 회귀를 사전 차단한다.

**Architecture:** 5계층 구조 — (1) **Parsers**(junit XML/mypy text/ruff JSON/git diff → 통합 JSON 스키마) (2) **Runner**(pytest/mypy/ruff/diff 실제 실행) (3) **Contract**(증거 4종 → Default-FAIL pass/fail) (4) **Verifier CLI**(`scripts/harness/run_verifier.py`, run_auto_implement.sh가 호출) (5) **Golden Set**(`tests/eval/golden_proposals/` + invariant 3 type: ruff_rule, regex_absent, pytest_passes). 외부 의존 추가 없음 (built-in stdlib + 기존 pytest/ruff/mypy만).

**Tech Stack:** Python 3.12 stdlib(`xml.etree`, `subprocess`, `json`, `re`), pytest 9.0.2 `--junitxml`, ruff 0.15.8 `--output-format=json`, mypy 1.19.1 text 출력 파싱, SQLAlchemy 2.0 (Repository 활용), 기존 src.harness.* 패키지 확장.

---

## Spec → Task 매핑

harness plan(`docs/plans/2026-05-14_harness-engineering-improvement.md`) §5 Phase 2 + phase1_completion.md §3 이관 항목.

| 진단/이관 | 해결 산출물 | Task |
|----------|-------------|------|
| D2 (자기보고 검증) | Verifier가 fresh-context로 채점 | T6, T7 |
| D6 (관측성: `changed_files` JSONB 0건) | git diff 파서가 자동 채움 | T1, T11 |
| D7 (골든 회귀 셋 부재) | `tests/eval/golden_proposals/` 10건 + runner | T8~T10 |
| Phase 1 §3 이관 (verification artifacts 강제) | Default-FAIL contract | T5 |
| Phase 1 §3 이관 (mark_implemented/failed 자동) | Verifier→Repository wiring | T11 |
| `run_auto_implement.sh` 의 `grep -q "implemented"` 휴리스틱 | Verifier exit code 기반 결정 | T12 |

---

## File Structure

### Create

| 파일 | 책임 |
|------|------|
| `src/harness/verifier/__init__.py` | 패키지 stub |
| `src/harness/verifier/diff.py` | git diff → `changed_files` JSONB 스키마 |
| `src/harness/verifier/parsers.py` | junit XML / mypy text / ruff JSON → 통합 스키마 |
| `src/harness/verifier/runner.py` | pytest/mypy/ruff/diff 실행 + 출력 캡처 + 통합 아티팩트 빌드 |
| `src/harness/verifier/contract.py` | Default-FAIL 평가기 |
| `src/harness/verifier/cycle.py` | Verifier→Repository wiring (mark_implemented/failed + verification JSONB 적재) |
| `src/harness/golden/__init__.py` | 패키지 stub |
| `src/harness/golden/loader.py` | 골든 케이스 디렉토리 로더 |
| `src/harness/golden/runner.py` | invariant 평가기 (3 type) |
| `scripts/harness/run_verifier.py` | CLI 진입점 (run_auto_implement.sh가 호출) |
| `tests/eval/__init__.py` | 패키지 stub |
| `tests/eval/test_golden_runner.py` | 골든 셋 회귀 통합 테스트 |
| `tests/eval/golden_proposals/G01_dtz_engine_queue/manifest.json` | 골든 케이스 1 |
| `tests/eval/golden_proposals/G02_dtz_timestamptz_listener/manifest.json` | 골든 케이스 2 |
| `tests/eval/golden_proposals/G03_dtz_repository_utcnow/manifest.json` | 골든 케이스 3 |
| `tests/eval/golden_proposals/G04_screening_query_kst/manifest.json` | 골든 케이스 4 |
| `tests/eval/golden_proposals/G05_engine_daily_threshold/manifest.json` | 골든 케이스 5 |
| `tests/eval/golden_proposals/G06_ma_nan_guard/manifest.json` | 골든 케이스 6 |
| `tests/eval/golden_proposals/G07_screener_etf_blocklist/manifest.json` | 골든 케이스 7 |
| `tests/eval/golden_proposals/G08_notify_error_signature/manifest.json` | 골든 케이스 8 |
| `tests/eval/golden_proposals/G09_daily_quote_pagination/manifest.json` | 골든 케이스 9 |
| `tests/eval/golden_proposals/G10_strategy_min_confidence/manifest.json` | 골든 케이스 10 |
| `tests/test_harness/test_verifier_diff.py` | T1 TDD |
| `tests/test_harness/test_verifier_parsers.py` | T2~T4 TDD |
| `tests/test_harness/test_verifier_contract.py` | T5 TDD |
| `tests/test_harness/test_verifier_runner.py` | T6 TDD |
| `tests/test_harness/test_verifier_cli.py` | T7 TDD (subprocess) |
| `tests/test_harness/test_verifier_cycle.py` | T11 TDD |
| `tests/test_harness/test_golden_loader.py` | T8 TDD |
| `tests/test_harness/test_golden_runner.py` | T10 TDD |

### Modify

| 파일 | 변경 |
|------|------|
| `scripts/run_auto_implement.sh` | `claude -p` 직후 골든 셋 회귀 사전 실행 + claude 완료 후 Verifier 호출. exit code 기반 service restart 결정 |
| `docs/harness/phase1_completion.md` | Phase 2 진입 안내 한 줄 추가 (T13에서) |

---

## Task 1: git diff 파서 + `changed_files` JSONB 스키마

**Files:**
- Create: `src/harness/verifier/__init__.py`, `src/harness/verifier/diff.py`
- Test: `tests/test_harness/test_verifier_diff.py`

- [ ] **Step 1: 실패 테스트**

`tests/test_harness/test_verifier_diff.py`:
```python
"""git diff → changed_files JSONB 스키마 변환 TDD."""

from __future__ import annotations

from src.harness.verifier.diff import (
    ChangedFile,
    DiffSummary,
    parse_numstat,
)


def test_parse_numstat_basic():
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


def test_parse_numstat_ignores_binary():
    raw = "-\t-\tsrc/static/logo.png\n5\t3\tsrc/strategy/x.py\n"
    diff = parse_numstat(raw)
    assert len(diff.files) == 1  # binary 제외
    assert diff.files[0].path == "src/strategy/x.py"


def test_parse_numstat_empty():
    diff = parse_numstat("")
    assert diff.files == []
    assert diff.total_additions == 0


def test_jsonb_serializable():
    raw = "10\t5\tsrc/x.py\n"
    diff = parse_numstat(raw)
    payload = diff.to_jsonb()
    assert payload == {
        "files": [{"path": "src/x.py", "additions": 10, "deletions": 5}],
        "total_additions": 10,
        "total_deletions": 5,
        "file_count": 1,
    }


def test_changed_file_count_threshold():
    raw = "\n".join(f"1\t1\tsrc/f{i}.py" for i in range(6))
    diff = parse_numstat(raw)
    assert diff.file_count == 6
    assert diff.exceeds_threshold(5) is True
    assert diff.exceeds_threshold(10) is False
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_diff.py -v
```
Expected: `ModuleNotFoundError: src.harness.verifier.diff`

- [ ] **Step 3: 구현**

`src/harness/verifier/__init__.py`:
```python
"""Verifier 도메인 — fresh-context 검증 인프라."""
```

`src/harness/verifier/diff.py`:
```python
"""git diff → changed_files JSONB 변환.

`git diff --numstat <base>..<head>` 출력 한 줄당 `<additions>\\t<deletions>\\t<path>`.
binary 파일은 additions/deletions가 `-`로 표시되며 본 모듈은 무시한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChangedFile:
    path: str
    additions: int
    deletions: int


@dataclass
class DiffSummary:
    files: list[ChangedFile] = field(default_factory=list)

    @property
    def total_additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    @property
    def file_count(self) -> int:
        return len(self.files)

    def exceeds_threshold(self, threshold: int) -> bool:
        return self.file_count > threshold

    def to_jsonb(self) -> dict[str, Any]:
        return {
            "files": [
                {"path": f.path, "additions": f.additions, "deletions": f.deletions}
                for f in self.files
            ],
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "file_count": self.file_count,
        }


def parse_numstat(raw: str) -> DiffSummary:
    """git diff --numstat 출력을 DiffSummary로 변환."""
    files: list[ChangedFile] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        if add == "-" or dele == "-":
            continue
        try:
            files.append(ChangedFile(path=path, additions=int(add), deletions=int(dele)))
        except ValueError:
            continue
    return DiffSummary(files=files)
```

- [ ] **Step 4: 통과 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_diff.py -v
```
Expected: `5 passed`

- [ ] **Step 5: ruff/mypy**

```bash
.venv/bin/ruff check src/harness/verifier/ tests/test_harness/test_verifier_diff.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/diff.py
```

- [ ] **Step 6: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/__init__.py src/harness/verifier/diff.py tests/test_harness/test_verifier_diff.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): git diff → changed_files JSONB 파서 + TDD (Phase 2 T1)"
```

---

## Task 2: ruff JSON 파서

**Files:**
- Create: `src/harness/verifier/parsers.py`
- Test: `tests/test_harness/test_verifier_parsers.py`

> **참고:** parsers.py에는 T2(ruff), T3(pytest), T4(mypy) 세 파서가 차례로 추가된다. Task 2는 ruff 파서만 다룬다.

- [ ] **Step 1: 실패 테스트**

`tests/test_harness/test_verifier_parsers.py` 신설:
```python
"""ruff/pytest/mypy 출력 → 통합 검증 아티팩트 스키마 TDD."""

from __future__ import annotations

from src.harness.verifier.parsers import (
    RuffArtifact,
    parse_ruff_json,
)


def test_parse_ruff_empty():
    artifact = parse_ruff_json("[]")
    assert artifact.violations == []
    assert artifact.passed is True
    assert artifact.violation_count == 0


def test_parse_ruff_with_violations():
    raw = '''[
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
    ]'''
    artifact = parse_ruff_json(raw)
    assert artifact.violation_count == 2
    assert artifact.passed is False
    codes = [v.code for v in artifact.violations]
    assert "DTZ005" in codes
    assert "F401" in codes


def test_ruff_jsonb_serializable():
    artifact = parse_ruff_json("[]")
    payload = artifact.to_jsonb()
    assert payload == {"passed": True, "violation_count": 0, "violations": []}


def test_parse_ruff_invalid_json_marks_fail():
    artifact = parse_ruff_json("not json")
    assert artifact.passed is False
    assert artifact.violation_count == 0
    assert artifact.parse_error is not None
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_parsers.py -v
```
Expected: `ModuleNotFoundError: src.harness.verifier.parsers`

- [ ] **Step 3: 구현**

`src/harness/verifier/parsers.py`:
```python
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
    code: str
    message: str
    filename: str
    row: int
    column: int


@dataclass
class RuffArtifact:
    violations: list[RuffViolation] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def passed(self) -> bool:
        return self.parse_error is None and self.violation_count == 0

    def to_jsonb(self) -> dict[str, Any]:
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
```

- [ ] **Step 4: 통과 확인 + ruff/mypy**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_parsers.py -v
.venv/bin/ruff check src/harness/verifier/parsers.py tests/test_harness/test_verifier_parsers.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/parsers.py
```
Expected: `4 passed`, ruff/mypy clean

- [ ] **Step 5: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/parsers.py tests/test_harness/test_verifier_parsers.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): ruff JSON 파서 + TDD (Phase 2 T2)"
```

---

## Task 3: pytest junit XML 파서

**Files:**
- Modify: `src/harness/verifier/parsers.py` (append), `tests/test_harness/test_verifier_parsers.py` (append)

- [ ] **Step 1: 테스트 추가 (append)**

`tests/test_harness/test_verifier_parsers.py` 끝에 다음 추가:
```python
from src.harness.verifier.parsers import (
    PytestArtifact,
    parse_pytest_junit,
)


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


def test_parse_pytest_junit_basic():
    art = parse_pytest_junit(_SAMPLE_JUNIT)
    assert art.tests == 3
    assert art.failures == 1
    assert art.errors == 0
    assert art.skipped == 0
    assert art.passed is False
    assert art.duration_seconds > 0


def test_parse_pytest_junit_all_pass():
    raw = '<testsuites><testsuite name="x" tests="2" failures="0" errors="0" skipped="0" time="0.1"/></testsuites>'
    art = parse_pytest_junit(raw)
    assert art.tests == 2
    assert art.passed is True


def test_parse_pytest_junit_invalid():
    art = parse_pytest_junit("not xml")
    assert art.passed is False
    assert art.parse_error is not None


def test_pytest_jsonb_serializable():
    art = parse_pytest_junit(_SAMPLE_JUNIT)
    payload = art.to_jsonb()
    assert payload["tests"] == 3
    assert payload["failures"] == 1
    assert payload["passed"] is False
    assert "failed_tests" in payload
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_parsers.py -v
```
Expected: 새 4건 모두 ImportError 또는 동등 실패

- [ ] **Step 3: 구현 (`src/harness/verifier/parsers.py` 끝에 추가)**

```python
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class PytestFailure:
    classname: str
    name: str
    message: str


@dataclass
class PytestArtifact:
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    failed_tests: list[PytestFailure] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.parse_error is None
            and self.failures == 0
            and self.errors == 0
        )

    def to_jsonb(self) -> dict[str, Any]:
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
        root = ET.fromstring(raw)
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
```

- [ ] **Step 4: 통과 확인 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_parsers.py -v
.venv/bin/ruff check src/harness/verifier/parsers.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/parsers.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/parsers.py tests/test_harness/test_verifier_parsers.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): pytest junit XML 파서 + TDD (Phase 2 T3)"
```
Expected: `8 passed` (T2 4건 + T3 4건)

---

## Task 4: mypy text 파서

**Files:**
- Modify: `src/harness/verifier/parsers.py` (append), test file (append)

- [ ] **Step 1: 테스트 추가**

```python
from src.harness.verifier.parsers import (
    MypyArtifact,
    parse_mypy_text,
)


def test_parse_mypy_success():
    raw = "Success: no issues found in 12 source files"
    art = parse_mypy_text(raw)
    assert art.passed is True
    assert art.error_count == 0
    assert art.files_checked == 12


def test_parse_mypy_errors():
    raw = '''src/db/repository.py:705: error: Missing type parameters for generic type "dict"  [type-arg]
src/db/repository.py:875: error: Missing type parameters for generic type "dict"  [type-arg]
Found 2 errors in 1 file (checked 11 source files)'''
    art = parse_mypy_text(raw)
    assert art.passed is False
    assert art.error_count == 2
    assert art.files_checked == 11
    assert len(art.errors) == 2
    assert art.errors[0].file == "src/db/repository.py"
    assert art.errors[0].line == 705
    assert art.errors[0].code == "type-arg"


def test_parse_mypy_empty():
    art = parse_mypy_text("")
    assert art.passed is False
    assert art.parse_error is not None


def test_mypy_jsonb_serializable():
    art = parse_mypy_text("Success: no issues found in 5 source files")
    p = art.to_jsonb()
    assert p["passed"] is True
    assert p["error_count"] == 0
```

- [ ] **Step 2: 구현 (parsers.py 끝에 추가)**

```python
import re


_MYPY_ERROR_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):\s*error:\s*(?P<msg>.*?)(?:\s+\[(?P<code>[^\]]+)\])?$"
)
_MYPY_SUMMARY_FAIL = re.compile(r"Found\s+(\d+)\s+errors?\s+in\s+\d+\s+files?\s+\(checked\s+(\d+)")
_MYPY_SUMMARY_OK = re.compile(r"Success:\s*no issues found in\s+(\d+)\s+source files?")


@dataclass(frozen=True)
class MypyError:
    file: str
    line: int
    message: str
    code: str


@dataclass
class MypyArtifact:
    errors: list[MypyError] = field(default_factory=list)
    files_checked: int = 0
    parse_error: str | None = None
    _passed_override: bool | None = None

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def passed(self) -> bool:
        if self._passed_override is not None:
            return self._passed_override
        return self.parse_error is None and self.error_count == 0 and self.files_checked > 0

    def to_jsonb(self) -> dict[str, Any]:
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
    for line in raw.splitlines():
        line = line.strip()
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

    # error 라인은 잡았지만 summary 라인이 없는 경우 (오래된 mypy)
    if not files_checked and not errors:
        return MypyArtifact(parse_error="no mypy summary found")
    return MypyArtifact(errors=errors, files_checked=files_checked)
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_parsers.py -v
.venv/bin/ruff check src/harness/verifier/parsers.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/parsers.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/parsers.py tests/test_harness/test_verifier_parsers.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): mypy text 파서 + TDD (Phase 2 T4)"
```
Expected: 12 passed

---

## Task 5: Default-FAIL 평가기

**Files:**
- Create: `src/harness/verifier/contract.py`
- Test: `tests/test_harness/test_verifier_contract.py`

- [ ] **Step 1: 실패 테스트**

```python
"""Default-FAIL contract 평가기 TDD."""

from __future__ import annotations

from src.harness.verifier.contract import (
    ContractResult,
    evaluate_contract,
)
from src.harness.verifier.diff import ChangedFile, DiffSummary
from src.harness.verifier.parsers import (
    MypyArtifact,
    PytestArtifact,
    RuffArtifact,
)


def _ok_pytest() -> PytestArtifact:
    return PytestArtifact(tests=10, failures=0, errors=0, skipped=0, duration_seconds=0.5)


def _ok_mypy() -> MypyArtifact:
    return MypyArtifact(files_checked=5)


def _ok_ruff() -> RuffArtifact:
    return RuffArtifact()


def _ok_diff() -> DiffSummary:
    return DiffSummary(files=[ChangedFile(path="src/x.py", additions=3, deletions=1)])


def test_all_present_and_pass_means_pass():
    res = evaluate_contract(
        pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff(),
    )
    assert res.passed is True
    assert res.reasons == []


def test_missing_any_artifact_fails():
    res = evaluate_contract(pytest=None, mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff())
    assert res.passed is False
    assert any("pytest" in r for r in res.reasons)


def test_failing_pytest_fails_contract():
    bad = PytestArtifact(tests=10, failures=2, errors=0)
    res = evaluate_contract(pytest=bad, mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff())
    assert res.passed is False
    assert any("pytest" in r for r in res.reasons)


def test_failing_ruff_fails_contract():
    bad = RuffArtifact(parse_error="boom")
    res = evaluate_contract(pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=bad, diff=_ok_diff())
    assert res.passed is False


def test_diff_empty_fails():
    empty = DiffSummary()
    res = evaluate_contract(pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=_ok_ruff(), diff=empty)
    assert res.passed is False
    assert any("diff" in r for r in res.reasons)


def test_excessive_file_count_warns_not_fails():
    big = DiffSummary(files=[ChangedFile(path=f"src/f{i}.py", additions=1, deletions=0) for i in range(8)])
    res = evaluate_contract(
        pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=_ok_ruff(), diff=big,
        file_count_threshold=5,
    )
    assert res.passed is True  # 통과는 함
    assert res.warnings  # 단 경고
    assert any("file_count" in w or "8" in w for w in res.warnings)


def test_to_jsonb_round_trip():
    res = evaluate_contract(
        pytest=_ok_pytest(), mypy=_ok_mypy(), ruff=_ok_ruff(), diff=_ok_diff(),
    )
    payload = res.to_jsonb()
    assert payload["passed"] is True
    assert "artifacts" in payload
    assert set(payload["artifacts"].keys()) == {"pytest", "mypy", "ruff", "diff"}
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_contract.py -v
```

- [ ] **Step 3: 구현**

`src/harness/verifier/contract.py`:
```python
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
    passed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_jsonb(self) -> dict[str, Any]:
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
    reasons: list[str] = []
    warnings: list[str] = []

    if pytest is None:
        reasons.append("pytest artifact missing")
    elif not pytest.passed:
        reasons.append(f"pytest failed (failures={pytest.failures}, errors={pytest.errors})")

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
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_contract.py -v
.venv/bin/ruff check src/harness/verifier/contract.py tests/test_harness/test_verifier_contract.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/contract.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/contract.py tests/test_harness/test_verifier_contract.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): Default-FAIL contract 평가기 + TDD 7건 (Phase 2 T5)"
```

---

## Task 6: Verifier Runner — 명령 실행 + 아티팩트 통합

**Files:**
- Create: `src/harness/verifier/runner.py`
- Test: `tests/test_harness/test_verifier_runner.py`

- [ ] **Step 1: 실패 테스트** (subprocess를 mock하여 결정적 테스트)

```python
"""Verifier Runner TDD — pytest/mypy/ruff/diff 실행 + 아티팩트 통합."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.harness.verifier.runner import (
    RunnerResult,
    VerifierRunner,
)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_runner_collects_all_artifacts(repo_root: Path):
    junit = '<testsuites><testsuite name="x" tests="1" failures="0" errors="0" skipped="0" time="0.1"/></testsuites>'
    runner = VerifierRunner(repo_root=repo_root)
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        # 호출 순서: ruff, mypy, pytest (junit 파일 작성), git diff numstat
        r.side_effect = [
            _proc(0, stdout="[]"),  # ruff
            _proc(0, stdout="Success: no issues found in 5 source files"),  # mypy
            _proc(0, stdout=""),  # pytest (--junitxml로 파일 작성. side effect로 파일 생성)
            _proc(0, stdout="5\t1\tsrc/x.py\n"),  # git diff
        ]
        junit_file = repo_root / "junit.xml"
        junit_file.write_text(junit, encoding="utf-8")
        runner._junit_path = junit_file  # 테스트용 주입
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert isinstance(result, RunnerResult)
    assert result.ruff is not None
    assert result.mypy is not None
    assert result.pytest is not None
    assert result.diff is not None
    assert result.diff.file_count == 1


def test_runner_marks_failures_when_subprocess_errors(repo_root: Path):
    runner = VerifierRunner(repo_root=repo_root)
    with patch("src.harness.verifier.runner.subprocess.run") as r:
        r.side_effect = subprocess.SubprocessError("pytest binary missing")
        result = runner.run(base_ref="HEAD~1", head_ref="HEAD")
    assert result.ruff is None or result.ruff.parse_error is not None
    assert result.runner_error is not None


def test_runner_default_paths(repo_root: Path):
    runner = VerifierRunner(repo_root=repo_root)
    assert runner.src_target == "src/"
    assert runner.test_target == "tests/"
```

- [ ] **Step 2: 실패 확인**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_runner.py -v
```

- [ ] **Step 3: 구현**

`src/harness/verifier/runner.py`:
```python
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
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_runner.py -v
.venv/bin/ruff check src/harness/verifier/runner.py tests/test_harness/test_verifier_runner.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/runner.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/runner.py tests/test_harness/test_verifier_runner.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): Runner — pytest/mypy/ruff/diff 통합 실행 + TDD (Phase 2 T6)"
```

---

## Task 7: Verifier CLI — `scripts/harness/run_verifier.py`

**Files:**
- Create: `scripts/harness/run_verifier.py`
- Test: `tests/test_harness/test_verifier_cli.py`

- [ ] **Step 1: 실패 테스트 (subprocess 호출)**

```python
"""Verifier CLI subprocess 진입점 TDD."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "harness" / "run_verifier.py"


def _run(args: list[str]) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(WRAPPER.parents[2])}
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_cli_help_lists_options():
    code, out, _ = _run(["--help"])
    assert code == 0
    assert "--base-ref" in out
    assert "--out" in out


def test_cli_writes_artifact_json(tmp_path: Path):
    out = tmp_path / "verifier.json"
    # --self-test 옵션이 실제 명령을 돌리지 않고 더미 결과를 출력하도록 함
    code, _, _ = _run(["--self-test", "--out", str(out)])
    assert code in (0, 2)  # contract pass(0) 또는 fail(2)
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "passed" in payload
    assert "artifacts" in payload
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과**

`scripts/harness/run_verifier.py`:
```python
#!/usr/bin/env python3
"""Verifier 사이클 CLI 진입점.

run_auto_implement.sh가 `claude -p` 직후 호출한다. 사용:
    python -m scripts.harness.run_verifier --base-ref <tag> --head-ref HEAD --out path.json

exit code:
    0  contract pass
    2  contract fail (artifact 부재 또는 검증 실패)
    3  runner internal error

--self-test 옵션은 실제 명령 호출 없이 가짜 통과 결과를 출력한다 (CLI smoke test 용).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.harness.verifier.contract import ContractResult, evaluate_contract
from src.harness.verifier.diff import ChangedFile, DiffSummary
from src.harness.verifier.parsers import (
    MypyArtifact,
    PytestArtifact,
    RuffArtifact,
)
from src.harness.verifier.runner import VerifierRunner

REPO_ROOT = Path(__file__).resolve().parents[2]


def _self_test() -> ContractResult:
    return evaluate_contract(
        pytest=PytestArtifact(tests=1, failures=0, errors=0),
        mypy=MypyArtifact(files_checked=1),
        ruff=RuffArtifact(),
        diff=DiffSummary(files=[ChangedFile(path="self-test", additions=0, deletions=0)]),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-ref", default="HEAD~1", help="git diff 시작 ref")
    p.add_argument("--head-ref", default="HEAD", help="git diff 종료 ref")
    p.add_argument("--out", type=Path, required=True, help="결과 JSON 출력 경로")
    p.add_argument("--self-test", action="store_true", help="실제 명령 호출 없이 통과 결과")
    args = p.parse_args(argv)

    if args.self_test:
        result = _self_test()
    else:
        runner_result = VerifierRunner(repo_root=REPO_ROOT).run(
            base_ref=args.base_ref, head_ref=args.head_ref,
        )
        if runner_result.runner_error:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(
                    {"passed": False, "runner_error": runner_result.runner_error},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            print(f"runner error: {runner_result.runner_error}", file=sys.stderr)
            return 3
        result = evaluate_contract(
            pytest=runner_result.pytest,
            mypy=runner_result.mypy,
            ruff=runner_result.ruff,
            diff=runner_result.diff,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result.to_jsonb(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not result.passed:
        for reason in result.reasons:
            print(f"[verifier] FAIL: {reason}", file=sys.stderr)
        return 2
    if result.warnings:
        for w in result.warnings:
            print(f"[verifier] WARN: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 권한 + 통과 + 검증 + 커밋**

```bash
chmod +x scripts/harness/run_verifier.py
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_cli.py -v
.venv/bin/ruff check scripts/harness/run_verifier.py tests/test_harness/test_verifier_cli.py
PYTHONPATH=. .venv/bin/python -m mypy --strict scripts/harness/run_verifier.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/harness/run_verifier.py tests/test_harness/test_verifier_cli.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): CLI 진입점 + --self-test + TDD (Phase 2 T7)"
```

---

## Task 8: 골든 회귀 셋 manifest 스키마 + loader

**Files:**
- Create: `src/harness/golden/__init__.py`, `src/harness/golden/loader.py`
- Test: `tests/test_harness/test_golden_loader.py`

- [ ] **Step 1: 실패 테스트**

```python
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
    _write_case(tmp_path, "G01_x", {"type": "regex_absent", "file": "src/x.py", "pattern": r"datetime\.utcnow\("})
    cases = load_cases(tmp_path)
    assert len(cases) == 1
    c = cases[0]
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
```

- [ ] **Step 2: 구현 (실패 확인 후)**

`src/harness/golden/__init__.py`:
```python
"""골든 회귀 셋 도메인."""
```

`src/harness/golden/loader.py`:
```python
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
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class InvariantType(str, Enum):
    REGEX_ABSENT = "regex_absent"
    REGEX_PRESENT = "regex_present"
    RUFF_RULE = "ruff_rule"
    PYTEST_PASSES = "pytest_passes"


@dataclass(frozen=True)
class Invariant:
    type: InvariantType
    params: dict[str, Any]


@dataclass(frozen=True)
class GoldenCase:
    id: str
    proposal_path: str
    category: str
    summary: str
    invariant: Invariant


def _parse_invariant(raw: dict[str, Any], *, strict: bool) -> Invariant | None:
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
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_golden_loader.py -v
.venv/bin/ruff check src/harness/golden/ tests/test_harness/test_golden_loader.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/golden/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/golden/ tests/test_harness/test_golden_loader.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(golden): manifest 스키마 + loader + TDD (Phase 2 T8)"
```

---

## Task 9: 골든 셋 10건 등록

**Files:**
- Create: `tests/eval/__init__.py`, `tests/eval/golden_proposals/__init__.py`
- Create: 10개 디렉토리 + `manifest.json`

각 케이스는 과거 implemented 제안서에서 회귀 위험이 큰 영역을 발췌. invariant 3 type 다양하게 사용.

- [ ] **Step 1: 디렉토리 stub**

`tests/eval/__init__.py`:
```python
"""eval 패키지 — 골든 회귀 셋."""
```

`tests/eval/golden_proposals/__init__.py`:
```python
"""골든 케이스 디렉토리 — pytest 인식용 stub."""
```

- [ ] **Step 2: G01 — engine.py 큐 적재 naive datetime 차단**

`tests/eval/golden_proposals/G01_dtz_engine_queue/manifest.json`:
```json
{
  "id": "G01_dtz_engine_queue",
  "proposal_path": "docs/proposals/2026-05-13_engine-metric-signal-naive-timestamp-fix.md",
  "category": "bug_fix",
  "summary": "engine.py가 system_metrics/signals 큐에 naive timestamp을 적재하지 않아야 한다",
  "invariant": {
    "type": "regex_absent",
    "file": "src/engine.py",
    "pattern": "datetime\\.now\\(\\)(?!.*tz)"
  }
}
```

- [ ] **Step 3: G02 — TIMESTAMPTZ naive 차단 listener**

`tests/eval/golden_proposals/G02_dtz_timestamptz_listener/manifest.json`:
```json
{
  "id": "G02_dtz_timestamptz_listener",
  "proposal_path": "docs/proposals/2026-05-12_timestamp-naive-to-aware-utc.md",
  "category": "bug_fix",
  "summary": "session에 validate_timezone_aware listener가 등록되어 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "src/db/session.py",
    "pattern": "validate_timezone_aware"
  }
}
```

- [ ] **Step 4: G03 — repository.py datetime.utcnow() 제거**

`tests/eval/golden_proposals/G03_dtz_repository_utcnow/manifest.json`:
```json
{
  "id": "G03_dtz_repository_utcnow",
  "proposal_path": "docs/proposals/2026-05-12_repository-datetime-utcnow-deprecation.md",
  "category": "refactor",
  "summary": "repository.py가 datetime.utcnow()를 호출하지 않아야 한다",
  "invariant": {
    "type": "regex_absent",
    "file": "src/db/repository.py",
    "pattern": "datetime\\.utcnow\\("
  }
}
```

- [ ] **Step 5: G04 — screening query KST**

`tests/eval/golden_proposals/G04_screening_query_kst/manifest.json`:
```json
{
  "id": "G04_screening_query_kst",
  "proposal_path": "docs/proposals/2026-04-30_screening-query-timezone-fix.md",
  "category": "bug_fix",
  "summary": "screening 조회 시 KST 명시가 코드에 남아 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "src/db/repository.py",
    "pattern": "KST|Asia/Seoul"
  }
}
```

- [ ] **Step 6: G05 — engine daily data threshold**

`tests/eval/golden_proposals/G05_engine_daily_threshold/manifest.json`:
```json
{
  "id": "G05_engine_daily_threshold",
  "proposal_path": "docs/proposals/2026-05-06_engine-daily-data-threshold-reduction.md",
  "category": "bug_fix",
  "summary": "engine.py에 일봉 데이터 최소 요구량 가드가 남아 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "src/engine.py",
    "pattern": "min_daily_data|MIN_DAILY|일봉 데이터 부족"
  }
}
```

- [ ] **Step 7: G06 — moving_average NaN 가드**

`tests/eval/golden_proposals/G06_ma_nan_guard/manifest.json`:
```json
{
  "id": "G06_ma_nan_guard",
  "proposal_path": "docs/proposals/2026-04-06_moving-average-nan-guard.md",
  "category": "bug_fix",
  "summary": "moving_average.py에 NaN 가드가 남아 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "src/strategy/moving_average.py",
    "pattern": "isnan|np\\.isnan|pd\\.isna"
  }
}
```

- [ ] **Step 8: G07 — screener ETF 블록리스트**

`tests/eval/golden_proposals/G07_screener_etf_blocklist/manifest.json`:
```json
{
  "id": "G07_screener_etf_blocklist",
  "proposal_path": "docs/proposals/2026-05-09_screener-etf-code-blocklist.md",
  "category": "bug_fix",
  "summary": "screener에 ETF/Q-code 필터 블록리스트가 코드에 남아 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "src/worker/screener.py",
    "pattern": "ETF|blocklist|등록 코드"
  }
}
```

- [ ] **Step 9: G08 — notify_error 시그니처**

`tests/eval/golden_proposals/G08_notify_error_signature/manifest.json`:
```json
{
  "id": "G08_notify_error_signature",
  "proposal_path": "docs/proposals/2026-05-12_notify-error-signature-fix.md",
  "category": "bug_fix",
  "summary": "notify_error의 시그니처가 (title, message) 형태로 정의되어 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "src/notify/telegram.py",
    "pattern": "notify_error.*\\(.*title.*,.*message.*\\)"
  }
}
```

- [ ] **Step 10: G09 — DTZ ruff 룰셋 활성**

`tests/eval/golden_proposals/G09_dtz_ruleset_active/manifest.json`:
```json
{
  "id": "G09_dtz_ruleset_active",
  "proposal_path": "docs/harness/phase0_baseline.md",
  "category": "config",
  "summary": "pyproject.toml의 ruff select에 DTZ가 남아 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "pyproject.toml",
    "pattern": "\"DTZ\""
  }
}
```

- [ ] **Step 11: G10 — proposals 테이블 마이그레이션 head**

`tests/eval/golden_proposals/G10_proposals_table_migrated/manifest.json`:
```json
{
  "id": "G10_proposals_table_migrated",
  "proposal_path": "docs/harness/phase1_completion.md",
  "category": "config",
  "summary": "Alembic 최신 마이그레이션에 proposals 테이블 생성이 남아 있어야 한다",
  "invariant": {
    "type": "regex_present",
    "file": "alembic/versions/ecdd397b8238_add_proposals_table.py",
    "pattern": "create_table.*proposals"
  }
}
```

- [ ] **Step 12: 로더가 10건을 모두 인식하는지 확인 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -c "
from pathlib import Path
from src.harness.golden.loader import load_cases
cases = load_cases(Path('tests/eval/golden_proposals'), strict=True)
print(f'loaded {len(cases)} cases:')
for c in cases:
    print(f'  {c.id} ({c.invariant.type.value})')
"
```
Expected: `loaded 10 cases:`

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add tests/eval/
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(golden): 골든 회귀 셋 10건 등록 (Phase 2 T9)"
```

---

## Task 10: Golden Runner + pytest 통합

**Files:**
- Create: `src/harness/golden/runner.py`, `tests/eval/test_golden_runner.py`
- Test: `tests/test_harness/test_golden_runner.py`

- [ ] **Step 1: 실패 테스트 (단위)**

`tests/test_harness/test_golden_runner.py`:
```python
"""Golden runner invariant 평가기 TDD."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.golden.loader import GoldenCase, Invariant, InvariantType
from src.harness.golden.runner import (
    InvariantResult,
    evaluate_case,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


def _case(itype: InvariantType, **params) -> GoldenCase:
    return GoldenCase(
        id="Gtest", proposal_path="x.md", category="bug_fix", summary="t",
        invariant=Invariant(type=itype, params=params),
    )


def test_regex_absent_passes_when_pattern_not_found(repo: Path):
    (repo / "src" / "x.py").write_text("a = 1\n", encoding="utf-8")
    case = _case(InvariantType.REGEX_ABSENT, file="src/x.py", pattern=r"datetime\.utcnow\(")
    r = evaluate_case(case, repo_root=repo)
    assert r.passed is True


def test_regex_absent_fails_when_pattern_found(repo: Path):
    (repo / "src" / "x.py").write_text("import datetime\nx = datetime.utcnow()\n", encoding="utf-8")
    case = _case(InvariantType.REGEX_ABSENT, file="src/x.py", pattern=r"datetime\.utcnow\(")
    r = evaluate_case(case, repo_root=repo)
    assert r.passed is False
    assert "matched" in r.detail.lower() or "found" in r.detail.lower()


def test_regex_present_passes_when_pattern_found(repo: Path):
    (repo / "src" / "x.py").write_text("def safe(): return tz=UTC\n", encoding="utf-8")
    case = _case(InvariantType.REGEX_PRESENT, file="src/x.py", pattern=r"tz=UTC")
    r = evaluate_case(case, repo_root=repo)
    assert r.passed is True


def test_regex_present_fails_when_pattern_missing(repo: Path):
    (repo / "src" / "x.py").write_text("def unsafe(): pass\n", encoding="utf-8")
    case = _case(InvariantType.REGEX_PRESENT, file="src/x.py", pattern=r"tz=UTC")
    r = evaluate_case(case, repo_root=repo)
    assert r.passed is False


def test_missing_file_fails(repo: Path):
    case = _case(InvariantType.REGEX_PRESENT, file="src/nope.py", pattern="x")
    r = evaluate_case(case, repo_root=repo)
    assert r.passed is False
    assert "not found" in r.detail.lower() or "exist" in r.detail.lower()
```

- [ ] **Step 2: 구현**

`src/harness/golden/runner.py`:
```python
"""Golden case invariant 평가기.

regex_absent/regex_present/ruff_rule/pytest_passes 4 type 지원.
ruff_rule과 pytest_passes는 subprocess 실행이 필요하므로 외부 명령에 의존.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.harness.golden.loader import GoldenCase, InvariantType


@dataclass(frozen=True)
class InvariantResult:
    case_id: str
    passed: bool
    detail: str


def _eval_regex(
    case: GoldenCase, repo_root: Path, *, expect_match: bool
) -> InvariantResult:
    params = case.invariant.params
    rel_path = params.get("file", "")
    pattern = params.get("pattern", "")
    target = repo_root / rel_path
    if not target.exists():
        return InvariantResult(case.id, False, f"file not found: {rel_path}")
    content = target.read_text(encoding="utf-8")
    try:
        rx = re.compile(pattern, re.MULTILINE)
    except re.error as e:
        return InvariantResult(case.id, False, f"regex error: {e!s:.80}")
    found = rx.search(content) is not None
    if expect_match:
        return InvariantResult(
            case.id, found, "pattern present" if found else f"pattern missing: {pattern!r}",
        )
    return InvariantResult(
        case.id, not found, "pattern absent" if not found else f"pattern matched: {pattern!r}",
    )


def _eval_ruff_rule(case: GoldenCase, repo_root: Path) -> InvariantResult:
    params = case.invariant.params
    rule = params.get("rule", "")
    target = params.get("target", "src/")
    cp = subprocess.run(  # noqa: S603
        ["ruff", "check", target, "--select", rule, "--output-format=concise"],
        cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=120,
    )
    passed = cp.returncode == 0
    return InvariantResult(
        case.id, passed,
        f"ruff {rule} {'pass' if passed else 'fail'}: {cp.stdout.strip().splitlines()[0] if cp.stdout else ''}",
    )


def _eval_pytest(case: GoldenCase, repo_root: Path) -> InvariantResult:
    params = case.invariant.params
    nodeid = params.get("nodeid", "")
    cp = subprocess.run(  # noqa: S603
        ["pytest", nodeid, "-q", "--no-header"],
        cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=120,
    )
    return InvariantResult(
        case.id, cp.returncode == 0, f"pytest {nodeid} exit={cp.returncode}",
    )


def evaluate_case(case: GoldenCase, *, repo_root: Path) -> InvariantResult:
    if case.invariant.type == InvariantType.REGEX_ABSENT:
        return _eval_regex(case, repo_root, expect_match=False)
    if case.invariant.type == InvariantType.REGEX_PRESENT:
        return _eval_regex(case, repo_root, expect_match=True)
    if case.invariant.type == InvariantType.RUFF_RULE:
        return _eval_ruff_rule(case, repo_root)
    if case.invariant.type == InvariantType.PYTEST_PASSES:
        return _eval_pytest(case, repo_root)
    return InvariantResult(case.id, False, f"unsupported invariant type: {case.invariant.type}")
```

- [ ] **Step 3: pytest 통합 테스트 (실제 10건 회귀 검증)**

`tests/eval/test_golden_runner.py`:
```python
"""골든 셋 10건이 현재 워크트리에서 모두 통과해야 한다.

이 테스트가 실패하면 동일 카테고리 회귀가 들어왔다는 신호.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.golden.loader import load_cases
from src.harness.golden.runner import evaluate_case

GOLDEN_DIR = Path(__file__).resolve().parent / "golden_proposals"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cases():
    return load_cases(GOLDEN_DIR, strict=True)


def test_golden_set_has_at_least_10_cases(cases):
    assert len(cases) >= 10


@pytest.mark.parametrize("case_id", [
    "G01_dtz_engine_queue",
    "G02_dtz_timestamptz_listener",
    "G03_dtz_repository_utcnow",
    "G04_screening_query_kst",
    "G05_engine_daily_threshold",
    "G06_ma_nan_guard",
    "G07_screener_etf_blocklist",
    "G08_notify_error_signature",
    "G09_dtz_ruleset_active",
    "G10_proposals_table_migrated",
])
def test_golden_case_passes(cases, case_id: str):
    case = next((c for c in cases if c.id == case_id), None)
    assert case is not None, f"case {case_id} not loaded"
    result = evaluate_case(case, repo_root=REPO_ROOT)
    assert result.passed, f"{case_id}: {result.detail}"
```

- [ ] **Step 4: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_golden_runner.py tests/eval/test_golden_runner.py -v
.venv/bin/ruff check src/harness/golden/runner.py tests/test_harness/test_golden_runner.py tests/eval/test_golden_runner.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/golden/runner.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/golden/runner.py tests/test_harness/test_golden_runner.py tests/eval/test_golden_runner.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(golden): invariant runner + 10건 통합 회귀 (Phase 2 T10)"
```
Expected: `5 + 11 passed` (단위 5건 + 통합 11건). 만약 어떤 골든 케이스가 실패하면 invariant pattern을 실제 파일과 맞춰 조정.

---

## Task 11: Verifier → Repository wiring

**Files:**
- Create: `src/harness/verifier/cycle.py`
- Test: `tests/test_harness/test_verifier_cycle.py`

- [ ] **Step 1: 실패 테스트**

```python
"""Verifier 결과 → proposals/implementation_logs wiring TDD."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import (
    Base,
    ImplementationCategory,
    ProposalPriority,
    ProposalState,
)
from src.db.repository import ProposalRepository
from src.harness.verifier.contract import ContractResult
from src.harness.verifier.cycle import apply_verification_result


@pytest.fixture
def session():
    # SQLite JSONB workaround
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON  # type: ignore[attr-defined]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _make_in_flight(repo: ProposalRepository, path: str, cycle_id: str):
    p = repo.create(
        path=path, title="t", category=ImplementationCategory.BUG_FIX,
        state=ProposalState.READY, priority=ProposalPriority.HIGH,
    )
    repo.mark_in_flight(p.id, cycle_id=cycle_id)
    return p


def test_apply_pass_marks_implemented(session):
    repo = ProposalRepository(session)
    p = _make_in_flight(repo, "docs/proposals/x.md", "c-1")
    session.commit()
    contract = ContractResult(passed=True, artifacts={"pytest": {"passed": True}, "mypy": {"passed": True}, "ruff": {"passed": True}, "diff": {"file_count": 1}})
    apply_verification_result(
        session=session,
        cycle_id="c-1",
        contract=contract,
    )
    session.commit()
    refreshed = repo.find_by_path("docs/proposals/x.md")
    assert refreshed.state == ProposalState.IMPLEMENTED


def test_apply_fail_marks_failed_with_reason(session):
    repo = ProposalRepository(session)
    p = _make_in_flight(repo, "docs/proposals/y.md", "c-2")
    session.commit()
    contract = ContractResult(passed=False, reasons=["pytest failed (failures=2, errors=0)"], artifacts={})
    apply_verification_result(session=session, cycle_id="c-2", contract=contract)
    session.commit()
    refreshed = repo.find_by_path("docs/proposals/y.md")
    assert refreshed.state == ProposalState.FAILED
    assert "pytest" in refreshed.failure_reason


def test_apply_only_affects_in_flight_for_given_cycle(session):
    repo = ProposalRepository(session)
    _make_in_flight(repo, "docs/proposals/a.md", "c-X")
    _make_in_flight(repo, "docs/proposals/b.md", "c-Y")
    session.commit()
    contract = ContractResult(passed=True, artifacts={})
    apply_verification_result(session=session, cycle_id="c-X", contract=contract)
    session.commit()
    assert repo.find_by_path("docs/proposals/a.md").state == ProposalState.IMPLEMENTED
    assert repo.find_by_path("docs/proposals/b.md").state == ProposalState.IN_FLIGHT
```

- [ ] **Step 2: 구현**

`src/harness/verifier/cycle.py`:
```python
"""Verifier 결과를 proposals 상태 머신에 반영.

contract.passed이면 IN_FLIGHT → IMPLEMENTED, 아니면 → FAILED(reason 첨부).
호출자는 cycle_id로 영향 범위를 좁힌다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.repository import ProposalRepository
from src.harness.verifier.contract import ContractResult
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def apply_verification_result(
    *,
    session: Session,
    cycle_id: str,
    contract: ContractResult,
) -> None:
    """contract 결과로 cycle_id의 모든 IN_FLIGHT 제안서 상태 전이."""
    repo = ProposalRepository(session)
    in_flights = repo.list_in_flight_for_cycle(cycle_id)
    if not in_flights:
        logger.info("cycle %s: no IN_FLIGHT proposals to update", cycle_id)
        return

    if contract.passed:
        for p in in_flights:
            repo.mark_implemented(p.id)
        logger.info(
            "cycle %s: %d proposals → IMPLEMENTED", cycle_id, len(in_flights),
        )
        return

    reason = "; ".join(contract.reasons) or "contract failed without reasons"
    for p in in_flights:
        repo.mark_failed(p.id, reason=reason[:1000])
    logger.warning(
        "cycle %s: %d proposals → FAILED — %s",
        cycle_id, len(in_flights), reason[:200],
    )
```

- [ ] **Step 3: 통과 + 검증 + 커밋**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/test_verifier_cycle.py -v
.venv/bin/ruff check src/harness/verifier/cycle.py tests/test_harness/test_verifier_cycle.py
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/cycle.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add src/harness/verifier/cycle.py tests/test_harness/test_verifier_cycle.py
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(verifier): contract → proposals state wiring + TDD 3건 (Phase 2 T11)"
```

---

## Task 12: `run_auto_implement.sh` wiring

**Files:**
- Modify: `scripts/run_auto_implement.sh`

- [ ] **Step 1: claude -p 후 골든 회귀 + Verifier 호출 삽입**

`scripts/run_auto_implement.sh`에서 `echo "=== Auto-implement finished at ..."` 라인을 찾아 그 직전(=claude -p 완료 직후)에 다음 블록 추가:

```bash
# Phase 2: 골든 회귀 셋 사전 검증
echo "=== Golden regression check started at $(date) ===" >> "$LOG_FILE"
"$PROJECT_DIR/.venv/bin/python" -m pytest "$PROJECT_DIR/tests/eval/test_golden_runner.py" \
  -q --no-header >> "$LOG_FILE" 2>&1
GOLDEN_EXIT=$?
echo "=== Golden regression check finished at $(date) — exit=$GOLDEN_EXIT ===" >> "$LOG_FILE"

# Phase 2: Verifier 실행 (변경 사항이 있을 때만)
if git -C "$PROJECT_DIR" diff --quiet HEAD; then
  echo "[verifier] no diff vs HEAD — skip verifier" >> "$LOG_FILE"
  VERIFIER_EXIT=0
else
  VERIFIER_OUT="$PROJECT_DIR/logs/verifier_$(date +%Y-%m-%d_%H%M%S).json"
  PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" \
    -m scripts.harness.run_verifier \
    --base-ref HEAD~1 --head-ref HEAD --out "$VERIFIER_OUT" \
    >> "$LOG_FILE" 2>&1
  VERIFIER_EXIT=$?
  echo "[verifier] exit=$VERIFIER_EXIT artifact=$VERIFIER_OUT" >> "$LOG_FILE"
fi
```

그리고 기존의 `if grep -q "implemented" "$LOG_FILE"...` 라인을 다음으로 교체:

```bash
# Verifier + Golden 모두 통과해야 서비스 재시작
if [[ "$GOLDEN_EXIT" == "0" && "$VERIFIER_EXIT" == "0" ]] && grep -q "implemented" "$LOG_FILE" 2>/dev/null; then
```

- [ ] **Step 2: 문법 + 가짜 환경 dry-run**

```bash
bash -n scripts/run_auto_implement.sh && echo "syntax OK"
```
Expected: `syntax OK`

- [ ] **Step 3: 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add scripts/run_auto_implement.sh
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "feat(harness): run_auto_implement.sh — 골든 + Verifier 통과만 서비스 재시작 (Phase 2 T12)"
```

---

## Task 13: Phase 2 통합 검증 + 완료 리포트

**Files:**
- Create: `docs/harness/phase2_completion.md`

- [ ] **Step 1: 전체 pytest / ruff / mypy (신규 모듈)**

```bash
cd /Users/songhansu/IdeaProjects/kis-autotrader-harness
PYTHONPATH=. .venv/bin/python -m pytest tests/test_harness/ tests/eval/ -q
.venv/bin/ruff check src/harness/verifier/ src/harness/golden/ scripts/harness/run_verifier.py tests/test_harness/ tests/eval/
PYTHONPATH=. .venv/bin/python -m mypy --strict src/harness/verifier/ src/harness/golden/ scripts/harness/run_verifier.py
```
Expected: 모든 신규 테스트 통과, ruff/mypy 깨끗함

- [ ] **Step 2: end-to-end self-test**

```bash
PYTHONPATH=. .venv/bin/python -m scripts.harness.run_verifier --self-test --out /tmp/verifier_selftest.json
cat /tmp/verifier_selftest.json | python -m json.tool | head -20
echo "exit=$?"
```
Expected: `passed: true`, exit 0

- [ ] **Step 3: 골든 셋 실측 통과 (실제 워크트리에서)**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/eval/test_golden_runner.py -v
```
Expected: 11 passed (1 has-at-least-10 + 10 parametrized cases)

- [ ] **Step 4: 완료 리포트 작성**

`docs/harness/phase2_completion.md`에 다음 섹션 포함:
- 13 task 봉인 결과 표
- Phase 1 §3 이관 항목 충족 매핑 (changed_files JSONB 적재 + verification 자동 채움)
- 신규 테스트 카운트 (Verifier ~25건 + Golden ~5건 + 통합 ~11건 = ~41건)
- 운영 영향: `run_auto_implement.sh`가 메인 repo에 머지될 때까지는 워크트리에만 적용
- Phase 3 진입 준비: Initializer, 5계층 ADK, Pipeline MCP

- [ ] **Step 5: 최종 커밋**

```bash
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness add docs/harness/phase2_completion.md
git -C /Users/songhansu/IdeaProjects/kis-autotrader-harness commit -m "docs(harness): Phase 2 완료 리포트 (Phase 2 T13)"
```

---

## 운영 영향 / 머지 시 주의

본 Phase 2 작업도 워크트리에 한정. 메인 repo의 `scripts/run_auto_implement.sh`에는 골든/Verifier wiring이 없으므로 머지 시점에 다음을 결정:

1. 골든 회귀 + Verifier wiring을 메인 repo에 머지할지 (권장 — 안전 강화)
2. 머지 후 다음 평일 17:00 cron이 도착하기 전 `launchctl unload`로 한 번 잠시 멈추고 sanity check 후 reload
3. `verifier_*.json` 아티팩트 누적 경로(`logs/verifier_*.json`)의 로테이션 정책 — Phase 3에서 trajectory 테이블로 옮길 때 함께 정리
