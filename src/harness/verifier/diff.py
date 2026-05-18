"""git diff → changed_files JSONB 변환.

`git diff --numstat <base>..<head>` 출력 한 줄당 `<additions>\\t<deletions>\\t<path>`.
binary 파일은 additions/deletions가 `-`로 표시되며 본 모듈은 무시한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChangedFile:
    """변경된 파일 한 건 — 경로 + 추가/삭제 라인 수."""

    path: str
    additions: int
    deletions: int


@dataclass
class DiffSummary:
    """git diff 결과 요약 — 변경 파일 목록 + 합계 프로퍼티."""

    files: list[ChangedFile] = field(default_factory=list)

    @property
    def total_additions(self) -> int:
        """전체 추가 라인 합계."""
        return sum(f.additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        """전체 삭제 라인 합계."""
        return sum(f.deletions for f in self.files)

    @property
    def file_count(self) -> int:
        """변경된 파일 개수."""
        return len(self.files)

    def exceeds_threshold(self, threshold: int) -> bool:
        """파일 개수가 임계값을 초과하는지 여부."""
        return self.file_count > threshold

    def to_jsonb(self) -> dict[str, Any]:
        """`implementation_logs.changed_files` JSONB 컬럼용 직렬화.

        각 파일에 component 분류를 자동으로 채워, Phase 4의 재발률/대시보드
        분석이 모듈 단위로 동작하도록 한다. 순환 import 회피를 위해
        `classify_component` import는 함수 내부에서 수행한다.
        """
        from src.harness.observability.components import classify_component

        return {
            "files": [
                {
                    "path": f.path,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "component": classify_component(f.path),
                }
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
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("\t")
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
