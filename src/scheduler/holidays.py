"""증시 휴장일 관리 모듈 (멀티마켓).

휴장일 판단 우선순위:
1. 토/일 → 항상 휴장
2. 시장별 휴장일 파일에 등록된 날짜 → 휴장
3. 위 모두 아니면 → 개장일

시장별 파일: KRX=holidays.json, US=holidays_us.json (NYSE/NASDAQ 정규장 휴장일).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent

# 시장 코드 → 휴장일 파일명
_HOLIDAY_FILES: dict[str, str] = {
    "KRX": "holidays.json",
    "US": "holidays_us.json",
}

# 프로젝트 루트 기준 KRX 휴장일 파일 경로 (하위호환 — 기존 import 보존)
HOLIDAYS_FILE = _ROOT / "holidays.json"


def _load_holidays(market_code: str = "KRX") -> set[str]:
    """시장별 휴장일 목록을 로드한다.

    Args:
        market_code: 시장 코드 ("KRX" | "US")

    Returns:
        ISO 형식 날짜 문자열 집합 (예: {"2026-01-01", "2026-01-27"})
    """
    filename = _HOLIDAY_FILES.get(market_code.upper(), "holidays.json")
    path = _ROOT / filename
    if not path.exists():
        logger.warning("휴장일 파일 없음: %s — 주말만 체크합니다", path)
        return set()

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        holidays = set(data.get("holidays", []))
        logger.info("휴장일 %d일 로드 완료 (%s)", len(holidays), filename)
        return holidays
    except Exception:
        logger.exception("%s 로드 실패 — 주말만 체크합니다", filename)
        return set()


# 모듈 로드 시 시장별 1회 읽어 캐시
_holidays_cache: dict[str, set[str]] = {}


def _holidays_for(market_code: str) -> set[str]:
    """시장별 휴장일 집합을 캐시에서 반환한다(없으면 로드)."""
    key = market_code.upper()
    if key not in _holidays_cache:
        _holidays_cache[key] = _load_holidays(key)
    return _holidays_cache[key]


def is_market_closed(
    target_date: date | None = None, market_code: str = "KRX"
) -> bool:
    """해당 날짜가 휴장일인지 확인한다.

    Args:
        target_date: 확인할 날짜 (기본값: 오늘)
        market_code: 시장 코드 ("KRX" | "US")

    Returns:
        True면 휴장 (주말 또는 공휴일)
    """
    d = target_date or date.today()

    # 토/일
    if d.weekday() > 4:
        return True

    # 시장별 공휴일
    return d.isoformat() in _holidays_for(market_code)


def reload_holidays() -> None:
    """휴장일 캐시를 비운다(다음 조회 시 재로드)."""
    _holidays_cache.clear()
