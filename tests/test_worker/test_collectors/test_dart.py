"""DARTCollector 테스트.

httpx.AsyncClient를 mock하여 DART OpenAPI list.json 응답을 시뮬레이션.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.models import NewsSourceType
from src.worker.collectors.dart import DARTCollector


def _list_response(items: list[dict[str, str]]) -> dict[str, object]:
    return {
        "status": "000",
        "message": "정상",
        "page_no": 1,
        "page_count": 100,
        "total_count": len(items),
        "total_page": 1,
        "list": items,
    }


def _mock_client(payload: dict[str, object]) -> MagicMock:
    """httpx.AsyncClient의 get을 mock."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status = MagicMock()

    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    return client


def _make_collector(
    client: MagicMock,
    corp_code_to_ticker: dict[str, str] | None = None,
) -> DARTCollector:
    return DARTCollector(
        embedder=MagicMock(),
        repo=MagicMock(),
        api_key="test-key",
        corp_code_to_ticker=corp_code_to_ticker or {"00126380": "005930"},
        client=client,
        rate_limit_sec=0.0,  # 테스트는 sleep 0
    )


@pytest.mark.asyncio
class TestCollect:
    async def test_returns_single_document(self) -> None:
        client = _mock_client(_list_response([
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "report_nm": "주요사항보고서(자기주식취득결정)",
                "rcept_no": "20260518000001",
                "rcept_dt": "20260518",
            },
        ]))
        collector = _make_collector(client)
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        assert len(docs) == 1
        doc = docs[0]
        assert doc.ticker == "005930"
        assert doc.source_type == NewsSourceType.DISCLOSURE
        assert doc.source_id == "20260518000001"
        assert "자기주식" in (doc.title or "")
        assert "삼성전자" in doc.body
        assert doc.event_time.tzinfo is not None
        assert "20260518000001" in (doc.source_url or "")

    async def test_skips_unmapped_corp_code(self) -> None:
        """관심 종목 매핑에 없는 corp_code는 skip."""
        client = _mock_client(_list_response([
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "report_nm": "보고서1",
                "rcept_no": "1",
                "rcept_dt": "20260518",
            },
            {
                "corp_code": "99999999",
                "corp_name": "관심없음",
                "stock_code": "999999",
                "report_nm": "보고서2",
                "rcept_no": "2",
                "rcept_dt": "20260518",
            },
        ]))
        collector = _make_collector(client)
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        assert len(docs) == 1
        assert docs[0].source_id == "1"

    async def test_empty_response(self) -> None:
        client = _mock_client(_list_response([]))
        collector = _make_collector(client)
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        assert docs == []

    async def test_event_time_kst_to_utc(self) -> None:
        """rcept_dt YYYYMMDD를 KST 09:00으로 해석 → UTC 00:00 변환."""
        client = _mock_client(_list_response([
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930",
                "report_nm": "x",
                "rcept_no": "1",
                "rcept_dt": "20260518",
            },
        ]))
        collector = _make_collector(client)
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        assert docs[0].event_time == datetime(2026, 5, 18, 0, 0, tzinfo=UTC)

    async def test_request_passes_api_key_and_date_range(self) -> None:
        client = _mock_client(_list_response([]))
        collector = _make_collector(client)
        await collector.collect(since=datetime(2026, 5, 17, 0, 0, tzinfo=UTC))
        call_kwargs = client.get.call_args.kwargs
        params = call_kwargs.get("params") or {}
        assert params.get("crtfc_key") == "test-key"
        assert params.get("bgn_de") == "20260517"
        assert "end_de" in params

    async def test_error_status_skipped(self) -> None:
        """status != '000' (예: '013' = 조회된 데이터 없음) → 빈 리스트."""
        client = _mock_client({
            "status": "013",
            "message": "조회된 데이타가 없습니다.",
        })
        collector = _make_collector(client)
        docs = await collector.collect(since=datetime(2026, 5, 17, tzinfo=UTC))
        assert docs == []
