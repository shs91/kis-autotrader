#!/usr/bin/env python3
"""특정 path의 제안서 메타데이터를 JSON으로 출력. 없으면 exit 1."""

from __future__ import annotations

import argparse
import json
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    """주어진 --path 의 제안서 메타데이터를 JSON으로 출력한다."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True)
    args = p.parse_args(argv)
    with get_session() as session:
        repo = ProposalRepository(session)
        prop = repo.find_by_path(args.path)
        if prop is None:
            print(f"proposal not found: {args.path}", file=sys.stderr)
            return 1
        payload = {
            "id": prop.id,
            "path": prop.path,
            "title": prop.title,
            "category": prop.category.value,
            "state": prop.state.value,
            "priority": prop.priority.value,
            "failure_reason": prop.failure_reason,
            "skip_reason": prop.skip_reason,
            "cycle_id": prop.cycle_id,
        }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
