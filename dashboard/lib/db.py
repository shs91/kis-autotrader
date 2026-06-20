"""대시보드 DB 연결 — 매매 엔진과 동일한 단일 소스에서 DB URL을 해석한다.

각 페이지가 ``dashboard/.streamlit/secrets.toml`` 의 ``DATABASE_URL`` 을 직접 읽으면
엔진(.env / ``src.config``)의 DB 선택과 드리프트한다(2026-06 운영 대시보드가 실전
전환 후에도 모의 DB에 연결된 사고의 원인). 이를 막기 위해 엔진과 동일하게
``src.config.settings.db.url`` (``KIS_ENV`` 기반)을 1순위로 사용한다.

기존 ``dashboard/db_config.py`` 의 로직을 흡수하며, 엔진/쿼리 헬퍼를 추가로 제공한다.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text
from sqlalchemy.engine import Engine

# 대시보드가 ``src.*`` 를 import할 수 있도록 프로젝트 루트를 path에 추가 (lib → dashboard → root)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 어떤 소스도 사용할 수 없을 때의 최후 fallback (실전 DB 기본값)
_FALLBACK_DB_URL = "postgresql://kis_user:kis_password@localhost:5432/kis_trader_real"


def _url_from_config() -> str | None:
    """매매 엔진과 동일한 소스(``src.config.settings.db.url``)에서 DB URL을 읽는다."""
    from src.config import settings

    return settings.db.url


def _url_from_secrets() -> str | None:
    """Streamlit secrets의 ``DATABASE_URL`` 을 읽는다(명시적 override)."""
    url = st.secrets.get("DATABASE_URL")
    return str(url) if url else None


def _safe(getter: Callable[[], str | None]) -> str | None:
    """getter를 실행하되 로드 실패(설정/스트림릿 미가용 등)는 None으로 폴백한다."""
    try:
        return getter()
    except Exception:  # noqa: BLE001 — 소스 로드 실패는 다음 소스로 폴백
        return None


def resolve_db_url() -> str:
    """대시보드가 사용할 DB URL을 해석한다.

    우선순위: (1) ``src.config.settings.db.url``(엔진과 동일, KIS_ENV 기반) →
    (2) Streamlit secrets의 ``DATABASE_URL``(override) → (3) 하드코딩 fallback.
    """
    return _safe(_url_from_config) or _safe(_url_from_secrets) or _FALLBACK_DB_URL


def secret_get(key: str, default: str) -> str:
    """Streamlit secrets에서 ``key`` 를 읽되, 부재/로드 실패 시 ``default`` 를 반환한다.

    ``st.secrets`` 는 secrets.toml이 아예 없으면 ``.get`` 호출조차 예외를 던지므로
    대시보드가 secrets.toml 없이도 동작하도록 안전하게 감싼다.
    """

    def _read() -> str | None:
        val = st.secrets.get(key)
        return str(val) if val is not None else None

    return _safe(_read) or default


@st.cache_resource
def get_engine() -> Engine:
    """DB 엔진을 생성한다(프로세스당 1회 캐시)."""
    from sqlalchemy import create_engine

    return create_engine(resolve_db_url(), pool_pre_ping=True)


def run_query(sql: str, params: dict[str, object] | None = None) -> pd.DataFrame:
    """SQL을 실행해 DataFrame을 반환한다."""
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def current_database() -> str | None:
    """연결된 DB 이름을 반환한다(연결 실패 시 None)."""

    def _read() -> str | None:
        with get_engine().connect() as conn:
            return conn.execute(text("SELECT current_database()")).scalar()

    return _safe(_read)
