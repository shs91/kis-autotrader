"""자동 구현 완료 후 패치노트를 Google Calendar에 등록하는 스크립트.

cron 스크립트(run_auto_implement.sh)에서 Claude Code 실행 후 호출된다.
오늘 날짜로 implemented된 제안서를 수집하여 패치노트 이벤트를 생성한다.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.calendar.google_auth import GoogleCalendarAuth
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

PROPOSALS_DIR = PROJECT_ROOT / "docs" / "proposals"
CHANGELOG_PATH = PROJECT_ROOT / "docs" / "CHANGELOG.md"

# 패치노트 이벤트 시간 (17:30~18:00, 자동 구현 완료 후)
PATCH_START_HOUR = 17
PATCH_START_MINUTE = 30
PATCH_END_HOUR = 18
PATCH_END_MINUTE = 0
TIMEZONE = "Asia/Seoul"


def find_today_implementations(today: str) -> list[dict[str, str]]:
    """오늘 implemented된 제안서를 수집한다.

    제안서 파일명 날짜와 구현 실행 날짜가 다를 수 있으므로(예: 금요일 작성 → 월요일 구현),
    파일명 대신 상태(implemented) + 파일 수정일이 오늘인지를 기준으로 판별한다.
    """
    results: list[dict[str, str]] = []

    if not PROPOSALS_DIR.exists():
        return results

    for f in sorted(PROPOSALS_DIR.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        if not re.search(r"상태:\s*implemented", content, re.IGNORECASE):
            continue

        # 파일 수정일이 오늘인지 확인 (오늘 implemented로 변경된 제안서만 대상)
        modified_date = date.fromtimestamp(f.stat().st_mtime).isoformat()
        if modified_date != today:
            continue

        # 제목 추출
        title_m = re.search(r"^#\s+(.+)", content, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else f.stem

        # 카테고리 추출
        cat_m = re.search(r"카테고리:\s*(\S+)", content, re.IGNORECASE)
        category = cat_m.group(1) if cat_m else "개선"

        # 변경 파일 추출
        changed_files = re.findall(r"`(src/\S+)`:", content)

        # 기대 효과 추출
        effect_m = re.search(
            r"(?:기대\s*효과|예상\s*효과)[:\s]*(.+?)(?:\n#|\n\n|\Z)",
            content, re.DOTALL,
        )
        effect = effect_m.group(1).strip()[:200] if effect_m else ""

        results.append({
            "title": title,
            "category": category,
            "files": ", ".join(changed_files) if changed_files else "-",
            "effect": effect,
            "filename": f.name,
        })

    return results


def build_patch_note_summary(today: str, patches: list[dict[str, str]]) -> str:
    """캘린더 이벤트 제목을 생성한다."""
    return f"[패치노트] {today} ({len(patches)}건 적용)"


def build_patch_note_description(today: str, patches: list[dict[str, str]]) -> str:
    """캘린더 이벤트 본문을 생성한다."""
    lines: list[str] = [
        "\U0001f527 자동 개선 패치노트",
        "",
        f"날짜: {today}",
        f"적용 건수: {len(patches)}건",
        f"적용 방식: Cowork 제안 → Claude Code 자동 구현",
        "",
        "--- 변경 내역 ---",
    ]

    for idx, p in enumerate(patches, start=1):
        lines.append("")
        lines.append(f"{idx}. {p['title']}")
        lines.append(f"   - 카테고리: {p['category']}")
        lines.append(f"   - 변경 파일: {p['files']}")
        if p["effect"]:
            # 여러 줄 기대효과를 한 줄로 정리
            effect_oneline = " ".join(p["effect"].split())
            lines.append(f"   - 기대 효과: {effect_oneline}")

    lines.append("")
    lines.append("---")
    lines.append("Cowork 분석 → Claude Code 자동 구현 파이프라인")

    return "\n".join(lines)


def build_event_body(
    today_date: date, summary: str, description: str,
) -> dict[str, Any]:
    """Google Calendar API 이벤트 본문을 구성한다."""
    date_str = today_date.isoformat()
    return {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": f"{date_str}T{PATCH_START_HOUR:02d}:{PATCH_START_MINUTE:02d}:00",
            "timeZone": TIMEZONE,
        },
        "end": {
            "dateTime": f"{date_str}T{PATCH_END_HOUR:02d}:{PATCH_END_MINUTE:02d}:00",
            "timeZone": TIMEZONE,
        },
        "colorId": "9",  # blueberry (파란색 — 매매결과와 구분)
    }


def main() -> None:
    """패치노트 캘린더 이벤트를 생성한다."""
    today = date.today()
    today_str = today.isoformat()

    logger.info("패치노트 이벤트 생성 시작: %s", today_str)

    patches = find_today_implementations(today_str)

    if not patches:
        logger.info("오늘 구현된 제안서 없음 — 패치노트 스킵")
        return

    summary = build_patch_note_summary(today_str, patches)
    description = build_patch_note_description(today_str, patches)
    event_body = build_event_body(today, summary, description)

    logger.info("패치노트: %s", summary)

    try:
        auth = GoogleCalendarAuth()
        service = auth.get_service()
        calendar_id = settings.calendar.calendar_id

        event: dict[str, Any] = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )
        logger.info("패치노트 캘린더 이벤트 등록 완료: %s", event["id"])

    except Exception:
        logger.exception("패치노트 캘린더 이벤트 생성 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
