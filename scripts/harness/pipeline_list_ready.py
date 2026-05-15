#!/usr/bin/env python3
"""READY 상태 제안서를 우선순위순 JSON list로 출력."""

from __future__ import annotations

import json
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main() -> int:
    """READY 제안서를 JSON list로 stdout에 출력한다."""
    with get_session() as session:
        repo = ProposalRepository(session)
        rows = repo.list_ready()
        payload = [
            {
                "id": r.id,
                "path": r.path,
                "title": r.title,
                "category": r.category.value,
                "state": r.state.value,
                "priority": r.priority.value,
            }
            for r in rows
        ]
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
