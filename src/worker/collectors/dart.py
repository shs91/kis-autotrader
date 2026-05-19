"""DART OpenAPI 공시 수집기.

API: https://opendart.fss.or.kr/api/list.json
- 일 20,000건 / 분당 1,000건 한도 (개발자 키 기준)
- 관심 종목 + 추적 종목으로 corp_code 제한해 일 한도 통제

Phase 3-2 단순 구현:
- list.json만 호출 (본문 fetch는 후속 phase).
- 정정공시 corr_rcept_no는 list 응답에 표준 노출되지 않으므로 후속 phase에서
  본문 호출과 함께 처리.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import httpx

from src.db.models import NewsSourceType
from src.rag.chunker import RawDocument
from src.utils.logger import setup_logger
from src.worker.collectors.base import BaseCollector

if TYPE_CHECKING:
    from src.db.repository import NewsChunkRepository, SystemMetricRepository
    from src.rag.embedder import Embedder

logger = setup_logger(__name__)

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
KST = timezone(timedelta(hours=9))


class DARTCollector(BaseCollector):
    """DART 공시 수집기."""

    source_name = "dart"

    def __init__(
        self,
        embedder: Embedder,
        repo: NewsChunkRepository,
        api_key: str,
        corp_code_to_ticker: dict[str, str],
        client: httpx.AsyncClient | None = None,
        rate_limit_sec: float = 1.0,
        metric_repo: SystemMetricRepository | None = None,
    ) -> None:
        """
        Args:
            corp_code_to_ticker: DART corp_code(8자리) → 종목코드(6자리) 매핑.
                관심/추적 종목만 포함하여 일 한도를 통제한다.
            rate_limit_sec: 매 요청 사이 최소 대기 (초). 분당 호출 제한 회피.
            metric_repo: 사이클 단위 NEWS_COLLECTED 메트릭 기록용 (옵션).
        """
        super().__init__(embedder=embedder, repo=repo, metric_repo=metric_repo)
        self._api_key = api_key
        self._corp_code_to_ticker = corp_code_to_ticker
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        self._rate_limit_sec = rate_limit_sec

    async def collect(self, since: datetime) -> list[RawDocument]:
        end_date = datetime.now(UTC).astimezone(KST).date()
        bgn_de = since.astimezone(KST).strftime("%Y%m%d")
        end_de = end_date.strftime("%Y%m%d")

        params: dict[str, str | int] = {
            "crtfc_key": self._api_key,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": 1,
            "page_count": 100,
        }
        await asyncio.sleep(self._rate_limit_sec)
        response = await self._client.get(DART_LIST_URL, params=params)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

        status = str(payload.get("status", ""))
        if status != "000":
            # 013 = 조회 데이터 없음, 그 외도 일단 빈 리스트로 처리하고 로그
            logger.info("DART list: status=%s message=%s", status, payload.get("message"))
            return []

        items = payload.get("list") or []
        docs: list[RawDocument] = []
        for item in items:
            corp_code = item.get("corp_code")
            if not corp_code:
                continue
            ticker = self._corp_code_to_ticker.get(corp_code)
            if not ticker:
                continue
            doc = self._to_document(item, ticker)
            if doc is not None:
                docs.append(doc)
        return docs

    def _to_document(self, item: dict[str, Any], ticker: str) -> RawDocument | None:
        rcept_no = item.get("rcept_no")
        rcept_dt = item.get("rcept_dt")
        report_nm = item.get("report_nm")
        corp_name = item.get("corp_name") or ""
        if not (rcept_no and rcept_dt and report_nm):
            return None
        try:
            event_kst = datetime.strptime(rcept_dt, "%Y%m%d").replace(
                hour=9, minute=0, tzinfo=KST,
            )
        except ValueError:
            logger.warning("DART rcept_dt parse 실패: %s", rcept_dt)
            return None
        event_time = event_kst.astimezone(UTC)

        return RawDocument(
            ticker=ticker,
            source_type=NewsSourceType.DISCLOSURE,
            source_id=rcept_no,
            title=report_nm,
            body=f"{corp_name} {report_nm}",
            event_time=event_time,
            source_url=DART_VIEWER_URL.format(rcept_no=rcept_no),
            metadata={"corp_name": corp_name},
        )
