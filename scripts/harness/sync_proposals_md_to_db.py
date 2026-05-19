"""기존 docs/proposals/*.md를 proposals 테이블로 일괄 동기화.

상태/우선순위/카테고리를 markdown 메타데이터에서 추출하고, path UNIQUE 위반은 skip한다.
한 번 실행하고 끝나는 일회성 스크립트.

CLI:
    python -m scripts.harness.sync_proposals_md_to_db [--dir docs/proposals]
    python -m scripts.harness.sync_proposals_md_to_db --backfill-prediction
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import ImplementationCategory, ProposalPriority, ProposalState
from src.db.repository import ProposalRepository
from src.db.session import get_session
from src.harness.observability.prediction import parse_prediction

REPO_ROOT = Path(__file__).resolve().parents[2]
META_LINE = re.compile(r"^-\s*([^:]+?)\s*:\s*(.+?)\s*$")
TITLE_LINE = re.compile(r"^#\s+(.+?)\s*$")

# 한글 키 → 코드 키
_KEY_MAP = {
    "상태": "state",
    "우선순위": "priority",
    "카테고리": "category",
    "일자": "date",
    "작성": "author",
}

# 알 수 없는 값은 기본값으로 매핑
_STATE_DEFAULT = "draft"
_PRIORITY_DEFAULT = "medium"
_CATEGORY_DEFAULT = "enhancement"


def parse_proposal(path: Path) -> dict[str, Any]:
    """제안서 markdown에서 title + 메타데이터를 추출한다."""
    title = path.stem
    meta: dict[str, str] = {}
    in_meta = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        tm = TITLE_LINE.match(line)
        if tm and title == path.stem:
            title = tm.group(1)
        if line.startswith("## 메타데이터") or line.startswith("## 메타 정보"):
            in_meta = True
            continue
        if in_meta:
            if line.startswith("## "):
                break
            m = META_LINE.match(line)
            if m:
                korean_key = m.group(1)
                code_key = _KEY_MAP.get(korean_key)
                if code_key:
                    meta[code_key] = m.group(2)
    return {
        "title": title[:300],
        "state": meta.get("state", _STATE_DEFAULT),
        "priority": meta.get("priority", _PRIORITY_DEFAULT),
        "category": meta.get("category", _CATEGORY_DEFAULT),
    }


def _coerce_state(raw: str) -> ProposalState:
    try:
        return ProposalState(raw)
    except ValueError:
        return ProposalState.DRAFT


def _coerce_priority(raw: str) -> ProposalPriority:
    try:
        return ProposalPriority(raw)
    except ValueError:
        return ProposalPriority.MEDIUM


def _coerce_category(raw: str) -> ImplementationCategory:
    try:
        return ImplementationCategory(raw)
    except ValueError:
        return ImplementationCategory.ENHANCEMENT


def sync_directory(directory: Path, session: Session) -> tuple[int, int]:
    """디렉토리 내 모든 *.md를 proposals 테이블로 INSERT. (inserted, skipped) 반환."""
    repo = ProposalRepository(session)
    inserted = skipped = 0
    for md in sorted(directory.glob("*.md")):
        path_str = str(md.resolve())
        if repo.find_by_path(path_str) is not None:
            skipped += 1
            continue
        parsed = parse_proposal(md)
        proposal = repo.create(
            path=path_str,
            title=parsed["title"],
            category=_coerce_category(parsed["category"]),
            state=_coerce_state(parsed["state"]),
            priority=_coerce_priority(parsed["priority"]),
        )
        pred = parse_prediction(md)
        if pred:
            repo.set_prediction(proposal.id, pred)
        inserted += 1
    return inserted, skipped


def backfill_predictions(directory: Path, session: Session) -> tuple[int, int]:
    """기존 proposals row의 prediction을 markdown에서 재파싱해 갱신.

    insert는 하지 않고 이미 등록된 path만 대상으로 한다. ``## 기대 효과`` 섹션이
    없거나 파싱 결과가 비면 skip. (updated, skipped) 반환.
    """
    repo = ProposalRepository(session)
    updated = skipped = 0
    for md in sorted(directory.glob("*.md")):
        path_str = str(md.resolve())
        existing = repo.find_by_path(path_str)
        if existing is None:
            skipped += 1
            continue
        pred = parse_prediction(md)
        if not pred:
            skipped += 1
            continue
        repo.set_prediction(existing.id, pred)
        updated += 1
    return updated, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=REPO_ROOT / "docs" / "proposals",
        help="제안서 디렉토리",
    )
    parser.add_argument(
        "--backfill-prediction",
        action="store_true",
        help="기존 row의 prediction 컬럼만 markdown에서 재파싱하여 갱신",
    )
    args = parser.parse_args(argv)

    with get_session() as session:
        if args.backfill_prediction:
            updated, skipped = backfill_predictions(args.dir, session)
            print(f"backfilled={updated}, skipped={skipped}")
        else:
            inserted, skipped = sync_directory(args.dir, session)
            print(f"inserted={inserted}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
