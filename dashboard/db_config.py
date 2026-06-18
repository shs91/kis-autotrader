"""대시보드 DB 연결 — 엔진과 동일한 단일 소스에서 DB URL을 해석한다.

기존에는 각 대시보드 페이지가 ``dashboard/.streamlit/secrets.toml`` 의
``DATABASE_URL`` 을 직접 읽었다. 이 값은 매매 엔진(.env / ``src.config``)의 DB
선택과 독립적이라 서로 드리프트(drift)할 수 있었다. 2026-06 실전 전환 이후
운영 대시보드 프로세스가 (전환 전 secrets 값을 캐시한 채) 모의 DB(``kis_trader``)에
연결된 상태로 모의 데이터를 표시한 사고의 구조적 원인이 바로 이 이중 소스다.

이를 막기 위해 대시보드도 엔진과 동일하게 ``src.config.settings.db.url``
(``KIS_ENV`` 기반 해석)을 1순위 소스로 사용한다. 즉 대시보드는 항상 엔진과
같은 DB를 본다 — 운영자가 secrets.toml을 따로 맞춰줄 필요가 없다.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

# 대시보드(app.py / pages/*)가 src.* 를 import할 수 있도록 프로젝트 루트를 path에 추가
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
    import streamlit as st

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

    우선순위:
    1. ``src.config.settings.db.url`` — 매매 엔진과 동일한 ``KIS_ENV`` 기반
       해석(단일 소스). 실전(``KIS_ENV=real``)이면 ``DATABASE_URL_REAL``
       (``kis_trader_real``)을 사용한다.
    2. Streamlit secrets의 ``DATABASE_URL`` — ``src.config`` 로드 실패 시
       명시적 override (예: 엔진과 다른 호스트에서 대시보드만 띄우는 경우).
    3. 하드코딩 fallback(``kis_trader_real``).
    """
    return _safe(_url_from_config) or _safe(_url_from_secrets) or _FALLBACK_DB_URL


def secret_get(key: str, default: str) -> str:
    """Streamlit secrets에서 ``key`` 를 읽되, 부재/로드 실패 시 ``default`` 를 반환한다.

    ``st.secrets`` 는 secrets.toml이 아예 없으면 ``.get(key, default)`` 호출조차
    ``StreamlitSecretNotFoundError`` 를 던진다. 대시보드가 secrets.toml 없이도
    동작하도록 안전하게 감싼다.
    """

    def _read() -> str | None:
        import streamlit as st

        val = st.secrets.get(key)
        return str(val) if val is not None else None

    return _safe(_read) or default
