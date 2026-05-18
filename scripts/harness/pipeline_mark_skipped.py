#!/usr/bin/env python3
"""제안서를 SKIPPED 상태로 전이. reason 필수 (예: safety_gate_violation)."""

from __future__ import annotations

import argparse
import sys

from src.db.repository import ProposalRepository
from src.db.session import get_session


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", required=True)
    p.add_argument("--reason", required=True)
    args = p.parse_args(argv)
    with get_session() as session:
        repo = ProposalRepository(session)
        prop = repo.find_by_path(args.path)
        if prop is None:
            print(f"proposal not found: {args.path}", file=sys.stderr)
            return 1
        try:
            repo.mark_skipped(prop.id, reason=args.reason)
        except ValueError as e:
            print(f"state transition error: {e!s}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
