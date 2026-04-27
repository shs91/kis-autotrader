"""자동 구현 이력을 implementation_logs DB에 기록하는 CLI 스크립트.

Claude Code auto-implement 과정에서 호출한다.

사용법:
    .venv/bin/python scripts/record_implementation.py \
        --title "버그 수정 — 종목명 누락" \
        --category bug_fix \
        --proposal "docs/proposals/2026-04-14_stock-name-fix.md" \
        --files '{"src/engine.py": "fallback 로직 추가"}' \
        --verification "pytest ✅ | mypy ✅ | ruff ✅" \
        --background "종목명이 빈 문자열로 저장되는 문제" \
        --effect "종목명 정상 표시"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.models import ImplementationCategory
from src.db.repository import ImplementationLogRepository
from src.db.session import get_session

VALID_CATEGORIES = [c.value for c in ImplementationCategory]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="구현 이력을 implementation_logs DB에 기록한다.",
    )
    parser.add_argument(
        "--title", required=True,
        help="변경 제목 (예: '버그 수정 — 종목명 누락')",
    )
    parser.add_argument(
        "--category", required=True, choices=VALID_CATEGORIES,
        help=f"카테고리: {', '.join(VALID_CATEGORIES)}",
    )
    parser.add_argument(
        "--proposal", default=None,
        help="제안서 경로 (예: docs/proposals/2026-04-14_xxx.md)",
    )
    parser.add_argument(
        "--files", default=None,
        help='변경 파일 JSON (예: \'{"src/engine.py": "변경 요약"}\')',
    )
    parser.add_argument(
        "--verification", default=None,
        help="검증 결과 요약 (예: 'pytest ✅ | mypy ✅ | ruff ✅')",
    )
    parser.add_argument(
        "--background", default=None,
        help="배경 설명",
    )
    parser.add_argument(
        "--effect", default=None,
        help="기대 효과",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """구현 이력을 DB에 기록한다."""
    args = parse_args(argv)

    # 카테고리 변환
    category = ImplementationCategory(args.category)

    # 변경 파일 JSON 파싱
    changed_files = None
    if args.files:
        try:
            changed_files = json.loads(args.files)
        except json.JSONDecodeError as e:
            print(f"오류: --files JSON 파싱 실패: {e}", file=sys.stderr)
            sys.exit(1)

    # 검증 결과
    verification = None
    if args.verification:
        verification = {"summary": args.verification}

    with get_session() as session:
        repo = ImplementationLogRepository(session)
        log = repo.create(
            title=args.title,
            category=category,
            implemented_at=datetime.now(UTC),
            proposal_path=args.proposal,
            changed_files=changed_files,
            verification=verification,
            background=args.background,
            expected_effect=args.effect,
        )
        print(f"구현 이력 기록 완료: id={log.id}, title={log.title}")


if __name__ == "__main__":
    main()
