"""한국 증시 휴장일 관리 모듈.

휴장일 판단 우선순위:
1. 토/일 → 항상 휴장
2. holidays.json 파일에 등록된 날짜 → 휴장
3. 위 모두 아니면 → 개장일
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 프로젝트 루트 기준 휴장일 파일 경로
HOLIDAYS_FILE = Path(__file__).resolve().parent.parent.parent / "holidays.json"


def _load_holidays() -> set[str]:
    """holidays.json에서 휴장일 목록을 로드한다.

    Returns:
        ISO 형식 날짜 문자열 집합 (예: {"2026-01-01", "2026-01-27"})
    """
    if not HOLIDAYS_FILE.exists():
        logger.warning("holidays.json 파일 없음: %s — 주말만 체크합니다", HOLIDAYS_FILE)
        return set()

    try:
        with open(HOLIDAYS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        holidays = set(data.get("holidays", []))
        logger.info("휴장일 %d일 로드 완료 (%s)", len(holidays), HOLIDAYS_FILE.name)
        return holidays
    except Exception:
        logger.exception("holidays.json 로드 실패 — 주말만 체크합니다")
        return set()


# 모듈 로드 시 한 번만 읽음
_holidays: set[str] = _load_holidays()


def is_market_closed(target_date: date | None = None) -> bool:
    """해당 날짜가 휴장일인지 확인한다.

    Args:
        target_date: 확인할 날짜 (기본값: 오늘)

    Returns:
        True면 휴장 (주말 또는 공휴일)
    """
    d = target_date or date.today()

    # 토/일
    if d.weekday() > 4:
        return True

    # 공휴일
    return d.isoformat() in _holidays


def reload_holidays() -> None:
    """휴장일 목록을 다시 로드한다."""
    global _holidays  # noqa: PLW0603
    _holidays = _load_holidays()
