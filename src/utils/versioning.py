"""프로젝트 버저닝(SemVer) 유틸리티.

- SemVer `MAJOR.MINOR.PATCH` 포맷을 유지한다.
- `ImplementationCategory`별 자동 bump 매핑을 제공한다.
- 단일 버전 출처: `src/__version__.py` ↔ `pyproject.toml` 양쪽을 동시 갱신한다.

자동 파이프라인 흐름:
  pytest/mypy/ruff 전부 pass → `apply_bump()` 호출 → version 파일 갱신 →
  `git commit`(파이프라인) → `git tag v0.1.x`(파이프라인).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.db.models import ImplementationCategory

BumpType = Literal["major", "minor", "patch", "none"]

# 카테고리별 bump 매핑
# - breaking 카테고리는 현재 모델에 없음 → major bump는 수동 (BRIDGE_SPEC 참조)
# - feature/enhancement는 새 기능/개선 → minor
# - bug_fix/param_tuning/refactor/performance/config → patch
# - docs는 코드 영향 없음 → bump 없음
_CATEGORY_BUMP: dict[ImplementationCategory, BumpType] = {
    ImplementationCategory.BUG_FIX: "patch",
    ImplementationCategory.PARAM_TUNING: "patch",
    ImplementationCategory.REFACTOR: "patch",
    ImplementationCategory.PERFORMANCE: "patch",
    ImplementationCategory.CONFIG: "patch",
    ImplementationCategory.FEATURE: "minor",
    ImplementationCategory.ENHANCEMENT: "minor",
    ImplementationCategory.DOCS: "none",
}

# bump 우선순위 (큰 값이 우선)
_BUMP_RANK: dict[BumpType, int] = {"none": 0, "patch": 1, "minor": 2, "major": 3}

_SEMVER_RE: re.Pattern[str] = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$")

# 프로젝트 루트
_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_VERSION_FILE: Path = _ROOT / "src" / "__version__.py"
_PYPROJECT_FILE: Path = _ROOT / "pyproject.toml"


@dataclass(frozen=True)
class BumpResult:
    """bump 적용 결과."""

    previous: str  # 이전 버전 (예: "0.1.2")
    new: str  # 새 버전 (예: "0.1.3")
    bump_type: BumpType  # 적용된 bump 유형


def category_to_bump(category: ImplementationCategory) -> BumpType:
    """카테고리를 bump 유형으로 변환한다.

    Args:
        category: 구현 카테고리

    Returns:
        bump 유형 ("major"/"minor"/"patch"/"none")
    """
    return _CATEGORY_BUMP.get(category, "patch")


def merge_bumps(bumps: list[BumpType]) -> BumpType:
    """여러 bump 후보 중 가장 큰 것을 선택한다.

    Args:
        bumps: bump 후보 목록

    Returns:
        가장 큰 bump 유형 (빈 목록이면 "none")
    """
    if not bumps:
        return "none"
    return max(bumps, key=lambda b: _BUMP_RANK[b])


def parse_semver(version: str) -> tuple[int, int, int]:
    """SemVer 문자열을 (major, minor, patch) 튜플로 파싱한다.

    Args:
        version: "MAJOR.MINOR.PATCH" 문자열 ("v" 접두사는 사전 제거)

    Returns:
        (major, minor, patch) 튜플

    Raises:
        ValueError: 포맷이 SemVer가 아닐 때
    """
    s = version.strip().lstrip("v")
    match = _SEMVER_RE.match(s)
    if not match:
        raise ValueError(f"SemVer 파싱 실패: {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_version(current: str, bump_type: BumpType) -> str:
    """현재 버전에 bump를 적용한다.

    Args:
        current: 현재 버전 ("0.1.2")
        bump_type: bump 유형

    Returns:
        bump 적용된 새 버전. bump_type=="none"이면 current 그대로 반환.
    """
    major, minor, patch = parse_semver(current)
    if bump_type == "major":
        return f"{major + 1}.0.0"
    if bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    if bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return current


def read_current_version() -> str:
    """`src/__version__.py`에서 현재 버전을 읽는다.

    Returns:
        현재 버전 문자열

    Raises:
        ValueError: 파일에서 버전을 추출할 수 없을 때
    """
    text = _VERSION_FILE.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*:\s*str\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError(f"버전 추출 실패: {_VERSION_FILE}")
    return match.group(1)


def write_version_files(new_version: str) -> None:
    """`src/__version__.py`와 `pyproject.toml`을 새 버전으로 갱신한다.

    Args:
        new_version: 새 버전 ("0.1.3")
    """
    # 형식 검증 (잘못된 값으로 파일 쓰기 방지)
    parse_semver(new_version)

    # src/__version__.py
    text = _VERSION_FILE.read_text(encoding="utf-8")
    new_text = re.sub(
        r'(__version__\s*:\s*str\s*=\s*")[^"]+(")',
        rf'\g<1>{new_version}\g<2>',
        text,
        count=1,
    )
    _VERSION_FILE.write_text(new_text, encoding="utf-8")

    # pyproject.toml: `version = "0.1.0"` 라인 (project 섹션 내 첫 매칭)
    pp_text = _PYPROJECT_FILE.read_text(encoding="utf-8")
    new_pp = re.sub(
        r'(^version\s*=\s*")[^"]+(")',
        rf'\g<1>{new_version}\g<2>',
        pp_text,
        count=1,
        flags=re.MULTILINE,
    )
    _PYPROJECT_FILE.write_text(new_pp, encoding="utf-8")


def apply_bump(category: ImplementationCategory) -> BumpResult:
    """카테고리에 따라 버전을 bump하고 파일을 갱신한다.

    Args:
        category: 구현 카테고리

    Returns:
        bump 결과 (이전/새 버전 + bump 유형). bump_type=="none"이면
        파일은 갱신되지 않으며 previous == new.
    """
    bump_type = category_to_bump(category)
    previous = read_current_version()
    if bump_type == "none":
        return BumpResult(previous=previous, new=previous, bump_type="none")
    new = bump_version(previous, bump_type)
    write_version_files(new)
    return BumpResult(previous=previous, new=new, bump_type=bump_type)
