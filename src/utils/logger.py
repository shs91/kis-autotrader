"""로깅 설정 모듈.

일자별 로그 로테이션을 지원한다.
- logs/autotrader.log (당일 로그)
- logs/autotrader.log.2026-04-02 (이전 날짜 로그)
- 최대 30일치 보관, 이후 자동 삭제
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "autotrader.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_BACKUP_COUNT = 30  # 30일치 보관

_initialized = False


def _init_root_logger() -> None:
    """루트 로거에 파일 핸들러와 콘솔 핸들러를 설정한다.

    최초 1회만 실행되며, 이후 모든 모듈 로거가 이 설정을 상속한다.
    """
    global _initialized  # noqa: PLW0603
    if _initialized:
        return
    _initialized = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # 일자별 로테이션 파일 핸들러
    file_handler = TimedRotatingFileHandler(
        filename=str(LOG_FILE),
        when="midnight",
        interval=1,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 콘솔 핸들러 (launchd stdout 캡처용)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """모듈별 로거를 생성하고 설정한다.

    Args:
        name: 로거 이름 (보통 __name__ 사용)
        level: 로그 레벨

    Returns:
        설정된 Logger 인스턴스
    """
    _init_root_logger()

    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger
