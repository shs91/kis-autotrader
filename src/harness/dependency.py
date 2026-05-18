"""제안서 changed_files 비교로 독립 그룹 계산.

Union-Find 패턴: 두 제안서가 공통 파일을 1개라도 공유하면 같은 그룹.
files가 비어 있는 제안서들은 보수적으로 모두 한 그룹(직렬).
"""

from __future__ import annotations

from typing import Any


def _find(parent: dict[int, int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict[int, int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def compute_independent_groups(
    proposals: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """proposals = [{"path": str, "files": list[str]}, ...] → groups."""
    n = len(proposals)
    if n == 0:
        return []
    parent: dict[int, int] = {i: i for i in range(n)}
    # files 빈 인덱스들을 한 그룹으로 묶기
    empty_indices = [i for i, p in enumerate(proposals) if not p.get("files")]
    for i in range(1, len(empty_indices)):
        _union(parent, empty_indices[0], empty_indices[i])

    # 파일 공유 그래프 union
    file_to_idx: dict[str, int] = {}
    for i, p in enumerate(proposals):
        for f in p.get("files", []):
            if f in file_to_idx:
                _union(parent, file_to_idx[f], i)
            else:
                file_to_idx[f] = i

    groups: dict[int, list[dict[str, Any]]] = {}
    for i, p in enumerate(proposals):
        root = _find(parent, i)
        groups.setdefault(root, []).append(p)

    # 결정적 정렬: 그룹 내 path 정렬, 그룹 간 첫 path 기준 정렬
    ordered = [sorted(g, key=lambda x: x["path"]) for g in groups.values()]
    ordered.sort(key=lambda g: g[0]["path"])
    return ordered
