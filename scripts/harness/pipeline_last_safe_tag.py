#!/usr/bin/env python3
"""마지막 git tag(SemVer 정렬)를 출력. 없으면 exit 1."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    """최신 git tag(생성일 내림차순 첫 줄)를 stdout에 출력한다."""
    try:
        cp = subprocess.run(  # noqa: S603
            ["git", "tag", "--sort=-creatordate"],  # noqa: S607
            cwd=str(REPO_ROOT),
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"git failed: {e!s}", file=sys.stderr)
        return 1
    if cp.returncode != 0 or not cp.stdout.strip():
        return 1
    print(cp.stdout.strip().splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
