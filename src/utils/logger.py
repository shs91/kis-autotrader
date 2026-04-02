"""로깅 설정 모듈."""

from __future__ import annotations

import logging
import sys


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """모듈별 로거를 생성하고 설정한다.

    Args:
        name: 로거 이름 (보통 __name__ 사용)
        level: 로그 레벨

    Returns:
        설정된 Logger 인스턴스
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
