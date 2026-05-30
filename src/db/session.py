"""데이터베이스 세션 관리 모듈."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from src.db.models import Base
from src.utils.exceptions import DatabaseError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


@event.listens_for(Base, "load", propagate=True)
def _coerce_naive_datetimes_to_utc(target: Any, _context: Any) -> None:
    """ORM 로드 직후 naive datetime을 UTC-aware로 보정한다.

    SQLite는 TIMESTAMPTZ 컬럼을 naive datetime으로 돌려주는데, 이를 그대로 두면
    이후 dirty 플러시 때 `validate_timezone_aware`가 트립한다. PostgreSQL은 이미
    aware로 반환하므로 본 핸들러는 사실상 SQLite 테스트 환경에서만 동작한다.
    """
    mapper = inspect(target).mapper
    for col in mapper.columns:
        if not isinstance(col.type, DateTime) or not col.type.timezone:
            continue
        attr_name = mapper.get_property_by_column(col).key
        value = target.__dict__.get(attr_name)
        if isinstance(value, datetime) and value.tzinfo is None:
            target.__dict__[attr_name] = value.replace(tzinfo=UTC)


def validate_timezone_aware(session: Session, *_: Any) -> None:
    """TIMESTAMPTZ 컬럼에 명시적으로 set된 naive datetime을 차단한다.

    호출자가 직접 set한 값만 검사하므로, 컬럼 default(예: datetime.utcnow)는
    플러시 시점까지 객체 __dict__에 없어 이 검사를 우회한다.
    `get_session()`이 만든 세션 인스턴스에만 등록되며, 테스트가 자체 세션을
    만들 때는 적용되지 않는다.
    """
    for obj in list(session.new) + list(session.dirty):
        mapper = inspect(obj).mapper
        instance_dict = obj.__dict__
        for col in mapper.columns:
            if not isinstance(col.type, DateTime) or not col.type.timezone:
                continue
            attr_name = mapper.get_property_by_column(col).key
            if attr_name not in instance_dict:
                continue
            value = instance_dict[attr_name]
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError(
                    f"Naive datetime in TIMESTAMPTZ column "
                    f"{obj.__class__.__name__}.{attr_name}: "
                    f"use datetime.now(UTC) or aware datetime"
                )


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
    event.listen(session, "before_flush", validate_timezone_aware)
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("데이터베이스 세션 에러: %s", e)
        raise DatabaseError(f"데이터베이스 처리 중 에러 발생: {e}") from e
    finally:
        session.close()


def db_healthcheck() -> bool:
    """DB 연결 가용성을 ``SELECT 1``로 확인한다.

    실주문을 내기 직전 호출하여, DB가 응답하지 않으면 주문을 보류시켜
    'KIS에는 체결됐는데 DB에는 기록 못한' 추적 불가 실포지션을 예방한다.
    어떤 예외도 전파하지 않고 False로 흡수한다(헬스체크 자체가 매매를 깨면 안 됨).

    Returns:
        DB가 응답하면 True, 아니면 False.
    """
    from sqlalchemy import text

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("DB 헬스체크 실패 (SELECT 1)", exc_info=True)
        return False


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
