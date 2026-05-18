"""제안서 독립 그룹 계산 TDD."""

from __future__ import annotations

from src.harness.dependency import compute_independent_groups


def test_disjoint_files_form_separate_groups() -> None:
    proposals = [
        {"path": "p1.md", "files": ["src/strategy/rsi.py"]},
        {"path": "p2.md", "files": ["src/strategy/macd.py"]},
        {"path": "p3.md", "files": ["src/api/auth.py"]},
    ]
    groups = compute_independent_groups(proposals)
    assert len(groups) == 3
    assert all(len(g) == 1 for g in groups)


def test_overlapping_files_collapse_into_one_group() -> None:
    proposals = [
        {"path": "p1.md", "files": ["src/engine.py", "src/db/repository.py"]},
        {"path": "p2.md", "files": ["src/engine.py"]},
        {"path": "p3.md", "files": ["src/api/auth.py"]},
    ]
    groups = compute_independent_groups(proposals)
    assert len(groups) == 2
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2]


def test_no_files_treated_as_serial() -> None:
    proposals = [
        {"path": "p1.md", "files": []},
        {"path": "p2.md", "files": []},
    ]
    groups = compute_independent_groups(proposals)
    # files 미지정 → 보수적으로 직렬 처리 (단일 그룹)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_returns_groups_in_deterministic_order() -> None:
    proposals = [
        {"path": "p_b.md", "files": ["src/x.py"]},
        {"path": "p_a.md", "files": ["src/y.py"]},
    ]
    groups = compute_independent_groups(proposals)
    # 그룹별로 첫 path 알파벳 정렬 (재현 가능성)
    first_paths = [g[0]["path"] for g in groups]
    assert first_paths == sorted(first_paths)
