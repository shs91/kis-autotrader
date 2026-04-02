"""데이터베이스 세션 관리 모듈."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from src.db.models import Base
from src.utils.exceptions import DatabaseError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """SQLAlchemy 엔진을 반환한다. 싱글턴 패턴.

    Returns:
        SQLAlchemy Engine 인스턴스
    """
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = create_engine(
            settings.db.url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        logger.info("데이터베이스 엔진 생성 완료: %s", settings.db.url.split("@")[-1])
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """세션 팩토리를 반환한다. 싱글턴 패턴.

    Returns:
        SQLAlchemy sessionmaker 인스턴스
    """
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """데이터베이스 세션 컨텍스트 매니저.

    트랜잭션 자동 관리: 정상 종료 시 commit, 예외 발생 시 rollback.

    Yields:
        SQLAlchemy Session 인스턴스

    Raises:
        DatabaseError: 세션 처리 중 에러 발생 시
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("데이터베이스 세션 에러: %s", e)
        raise DatabaseError(f"데이터베이스 처리 중 에러 발생: {e}") from e
    finally:
        session.close()


def init_db() -> None:
    """데이터베이스 테이블을 생성한다.

    모든 모델의 테이블을 생성한다. 이미 존재하는 테이블은 무시한다.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("데이터베이스 테이블 초기화 완료")


def reset_engine() -> None:
    """엔진 및 세션 팩토리를 초기화한다. 테스트용.

    기존 엔진을 dispose하고 싱글턴 상태를 리셋한다.
    """
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
