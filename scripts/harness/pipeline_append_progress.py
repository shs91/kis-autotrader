#!/usr/bin/env python3
"""claude-progress.json에 상태 전이 1건을 추가한다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.harness.progress import load_progress, save_progress


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리: progress 파일에 상태 전이 한 건 append."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--progress", required=True, type=Path)
    p.add_argument("--proposal", required=True)
    p.add_argument("--from-state", required=True)
    p.add_argument("--to-state", required=True)
    p.add_argument("--reason", default=None)
    args = p.parse_args(argv)

    progress = load_progress(args.progress)
    if progress is None:
        print(f"progress not found: {args.progress}", file=sys.stderr)
        return 1
    progress.transition(
        args.proposal,
        from_state=args.from_state,
        to_state=args.to_state,
        reason=args.reason,
    )
    save_progress(args.progress, progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
