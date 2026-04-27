"""기존 CHANGELOG.md 엔트리를 implementation_logs 테이블에 적재하는 일회성 스크립트."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.models import ImplementationCategory
from src.db.repository import ImplementationLogRepository
from src.db.session import get_session

CHANGELOG_PATH = Path(__file__).resolve().parent.parent / "docs" / "CHANGELOG.md"

CATEGORY_MAP: dict[str, ImplementationCategory] = {
    "bug_fix": ImplementationCategory.BUG_FIX,
    "bug fix": ImplementationCategory.BUG_FIX,
    "refactor": ImplementationCategory.REFACTOR,
    "param_tuning": ImplementationCategory.PARAM_TUNING,
    "feature": ImplementationCategory.FEATURE,
    "enhancement": ImplementationCategory.ENHANCEMENT,
    "performance": ImplementationCategory.PERFORMANCE,
    "docs": ImplementationCategory.DOCS,
    "config": ImplementationCategory.CONFIG,
}


def parse_changelog(text: str) -> list[dict]:
    """CHANGELOG.md를 파싱하여 엔트리 목록을 반환한다."""
    entries: list[dict] = []
    # ## [날짜] 제목 또는 ## [날짜 시간] 제목 패턴
    sections = re.split(r"(?=^## \[)", text, flags=re.MULTILINE)

    for section in sections:
        header_m = re.match(
            r"## \[(\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2})?\]\s*(.+)", section
        )
        if not header_m:
            continue

        date_str = header_m.group(1)
        title = header_m.group(2).strip()

        # 카테고리 추출
        cat_m = re.search(r"카테고리:\s*(\S+)", section)
        cat_str = cat_m.group(1).strip().lower() if cat_m else "enhancement"
        # 괄호 안 부분 제거 (예: "bug_fix (observability)" -> "bug_fix")
        cat_str = re.sub(r"\s*\(.*\)", "", cat_str)
        category = CATEGORY_MAP.get(cat_str, ImplementationCategory.ENHANCEMENT)

        # 제안서 경로
        proposal_m = re.search(r"제안서:\s*(\S+)", section)
        proposal_path = proposal_m.group(1).strip() if proposal_m else None

        # 변경 파일 추출
        changed_files: dict[str, str] = {}
        file_matches = re.findall(
            r"^\s+-\s+(src/\S+|tests/\S+|dashboard/\S+|main\.py|\.env\S*|"
            r"config_overrides\.json|docker-compose\.yml|scripts/\S+|"
            r"alembic/\S+):\s*(.+)",
            section,
            re.MULTILINE,
        )
        for fpath, desc in file_matches:
            changed_files[fpath] = desc.strip()

        # 검증 결과
        verif_m = re.search(r"검증 결과:\s*(.+?)(?:\n|$)", section)
        verification = {"summary": verif_m.group(1).strip()} if verif_m else None

        # 배경
        bg_m = re.search(
            r"배경:\s*\n((?:\s+-.+\n?)+)", section
        )
        background = bg_m.group(1).strip() if bg_m else None

        # 기대 효과
        effect_m = re.search(r"기대 효과:\s*(.+?)(?:\n---|\n##|\Z)", section, re.DOTALL)
        expected_effect = effect_m.group(1).strip() if effect_m else None

        try:
            impl_dt = datetime(
                int(date_str[:4]),
                int(date_str[5:7]),
                int(date_str[8:10]),
                21, 0, 0,
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue

        entries.append({
            "title": title,
            "category": category,
            "implemented_at": impl_dt,
            "proposal_path": proposal_path,
            "changed_files": changed_files if changed_files else None,
            "verification": verification,
            "background": background,
            "expected_effect": expected_effect,
        })

    return entries


def main() -> None:
    """CHANGELOG 엔트리를 DB에 적재한다."""
    if not CHANGELOG_PATH.exists():
        print("CHANGELOG.md not found")
        sys.exit(1)

    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    entries = parse_changelog(text)

    if not entries:
        print("파싱된 엔트리 없음")
        return

    print(f"파싱된 엔트리: {len(entries)}건")

    with get_session() as session:
        repo = ImplementationLogRepository(session)
        existing = repo.count()
        if existing > 0:
            print(f"이미 {existing}건 존재 — 중복 방지를 위해 스킵")
            return

        for entry in entries:
            repo.create(**entry)
            print(f"  적재: {entry['title']}")

    print(f"완료: {len(entries)}건 적재")


if __name__ == "__main__":
    main()
