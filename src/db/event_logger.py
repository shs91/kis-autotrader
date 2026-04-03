"""이벤트를 DB에 기록하는 헬퍼 모듈.

매매 로직에 영향을 주지 않도록 모든 기록은 try-except로 보호한다.
"""

from __future__ import annotations

from src.db.models import EventLevel
from src.db.repository import EventLogRepository
from src.db.session import get_session
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def log_event(
    level: EventLevel,
    category: str,
    message: str,
    details: str | None = None,
) -> None:
    """이벤트를 DB에 기록한다. 실패 시 로그만 남긴다."""
    try:
        with get_session() as session:
            repo = EventLogRepository(session)
            repo.log(level, category, message, details)
    except Exception:
        logger.debug("이벤트 DB 기록 실패: %s/%s", category, message)


def log_trade(message: str, details: str | None = None) -> None:
    """매매 이벤트를 기록한다."""
    log_event(EventLevel.INFO, "trade", message, details)


def log_system(message: str, details: str | None = None) -> None:
    """시스템 이벤트를 기록한다."""
    log_event(EventLevel.INFO, "system", message, details)


def log_error(message: str, details: str | None = None) -> None:
    """에러 이벤트를 기록한다."""
    log_event(EventLevel.ERROR, "error", message, details)


def log_warning(message: str, details: str | None = None) -> None:
    """경고 이벤트를 기록한다."""
    log_event(EventLevel.WARNING, "warning", message, details)
