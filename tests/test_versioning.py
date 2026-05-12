"""src.utils.versioning 모듈 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db.models import ImplementationCategory
from src.utils import versioning

# ── 카테고리 → bump 매핑 ───────────────────────────────────


class TestCategoryToBump:
    """category_to_bump 매핑 검증."""

    def test_bug_fix_is_patch(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.BUG_FIX) == "patch"

    def test_param_tuning_is_patch(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.PARAM_TUNING) == "patch"

    def test_refactor_is_patch(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.REFACTOR) == "patch"

    def test_performance_is_patch(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.PERFORMANCE) == "patch"

    def test_config_is_patch(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.CONFIG) == "patch"

    def test_feature_is_minor(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.FEATURE) == "minor"

    def test_enhancement_is_minor(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.ENHANCEMENT) == "minor"

    def test_docs_is_none(self) -> None:
        assert versioning.category_to_bump(ImplementationCategory.DOCS) == "none"


# ── bump 병합 ─────────────────────────────────────────────


class TestMergeBumps:
    """merge_bumps — 여러 bump 중 가장 큰 것 선택."""

    def test_empty_list(self) -> None:
        assert versioning.merge_bumps([]) == "none"

    def test_single_patch(self) -> None:
        assert versioning.merge_bumps(["patch"]) == "patch"

    def test_patch_and_minor_returns_minor(self) -> None:
        assert versioning.merge_bumps(["patch", "minor"]) == "minor"

    def test_all_three_returns_major(self) -> None:
        assert versioning.merge_bumps(["patch", "minor", "major"]) == "major"

    def test_none_and_patch_returns_patch(self) -> None:
        assert versioning.merge_bumps(["none", "patch"]) == "patch"


# ── SemVer 파싱 ──────────────────────────────────────────


class TestParseSemver:
    def test_basic(self) -> None:
        assert versioning.parse_semver("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self) -> None:
        assert versioning.parse_semver("v1.2.3") == (1, 2, 3)

    def test_with_whitespace(self) -> None:
        assert versioning.parse_semver("  0.1.0  ") == (0, 1, 0)

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError):
            versioning.parse_semver("1.2")

    def test_non_numeric(self) -> None:
        with pytest.raises(ValueError):
            versioning.parse_semver("a.b.c")


# ── 버전 bump ─────────────────────────────────────────────


class TestBumpVersion:
    def test_patch_bump(self) -> None:
        assert versioning.bump_version("0.1.2", "patch") == "0.1.3"

    def test_minor_bump_resets_patch(self) -> None:
        assert versioning.bump_version("0.1.5", "minor") == "0.2.0"

    def test_major_bump_resets_minor_and_patch(self) -> None:
        assert versioning.bump_version("0.3.7", "major") == "1.0.0"

    def test_none_returns_same(self) -> None:
        assert versioning.bump_version("0.1.2", "none") == "0.1.2"


# ── 파일 읽기/쓰기 (격리 환경에서) ──────────────────────────


class TestVersionFileRoundtrip:
    """`__version__.py` + `pyproject.toml` 동시 갱신 검증."""

    def test_write_then_read(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 가짜 프로젝트 구조 구성
        (tmp_path / "src").mkdir()
        version_file = tmp_path / "src" / "__version__.py"
        version_file.write_text(
            '"""docstring."""\n\n__version__: str = "0.1.0"\n',
            encoding="utf-8",
        )
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "x"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )

        monkeypatch.setattr(versioning, "_VERSION_FILE", version_file)
        monkeypatch.setattr(versioning, "_PYPROJECT_FILE", pyproject)

        assert versioning.read_current_version() == "0.1.0"

        versioning.write_version_files("0.2.3")

        assert versioning.read_current_version() == "0.2.3"
        assert 'version = "0.2.3"' in pyproject.read_text(encoding="utf-8")

    def test_apply_bump_updates_files(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "src").mkdir()
        version_file = tmp_path / "src" / "__version__.py"
        version_file.write_text(
            '__version__: str = "0.1.0"\n', encoding="utf-8",
        )
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nversion = "0.1.0"\n', encoding="utf-8",
        )

        monkeypatch.setattr(versioning, "_VERSION_FILE", version_file)
        monkeypatch.setattr(versioning, "_PYPROJECT_FILE", pyproject)

        result = versioning.apply_bump(ImplementationCategory.BUG_FIX)
        assert result.previous == "0.1.0"
        assert result.new == "0.1.1"
        assert result.bump_type == "patch"
        assert versioning.read_current_version() == "0.1.1"

    def test_apply_bump_docs_no_change(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "src").mkdir()
        version_file = tmp_path / "src" / "__version__.py"
        version_file.write_text(
            '__version__: str = "0.5.7"\n', encoding="utf-8",
        )
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nversion = "0.5.7"\n', encoding="utf-8",
        )

        monkeypatch.setattr(versioning, "_VERSION_FILE", version_file)
        monkeypatch.setattr(versioning, "_PYPROJECT_FILE", pyproject)

        result = versioning.apply_bump(ImplementationCategory.DOCS)
        assert result.previous == "0.5.7"
        assert result.new == "0.5.7"
        assert result.bump_type == "none"
        # docs는 파일도 갱신되지 않음
        assert versioning.read_current_version() == "0.5.7"
