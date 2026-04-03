"""헬스체크 서버 테스트."""

from __future__ import annotations

import asyncio
import json

from src.api.health import HealthServer, _build_health_response


class TestBuildHealthResponse:
    """헬스 응답 구성 테스트."""

    def test_ok_status(self) -> None:
        """정상 상태에서 ok를 반환한다."""
        response = _build_health_response(
            start_time=0.0,
            scheduler_running=True,
            cycle_count=100,
            daily_api_count=5000,
        )
        # DB가 테스트 환경에서 연결 가능하면 ok, 아니면 degraded
        assert response["status"] in ("ok", "degraded")
        assert "timestamp" in response
        assert "uptime" in response
        assert response["components"]["scheduler"]["running"] is True
        assert response["components"]["trading"]["cycle_count"] == 100
        assert response["components"]["trading"]["daily_api_calls"] == 5000

    def test_scheduler_stopped(self) -> None:
        """스케줄러 중지 시 stopped를 반환한다."""
        response = _build_health_response(
            start_time=0.0,
            scheduler_running=False,
            cycle_count=0,
            daily_api_count=0,
        )
        assert response["components"]["scheduler"]["status"] == "stopped"
        assert response["components"]["scheduler"]["running"] is False


class TestHealthServer:
    """HealthServer 통합 테스트."""

    async def test_health_endpoint(self) -> None:
        """GET /health가 JSON 응답을 반환한다."""
        server = HealthServer(port=0)  # OS가 빈 포트 할당
        server.set_status_provider(
            lambda: {
                "scheduler_running": True,
                "cycle_count": 42,
                "daily_api_count": 1000,
            }
        )
        await server.start()

        # 할당된 포트 확인
        assert server._server is not None
        port = server._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            response_str = response.decode("utf-8")
            writer.close()

            # HTTP 응답 파싱
            assert "200 OK" in response_str
            body = response_str.split("\r\n\r\n", 1)[1]
            data = json.loads(body)
            assert data["status"] in ("ok", "degraded")
            assert data["components"]["trading"]["cycle_count"] == 42
        finally:
            await server.stop()

    async def test_404_for_unknown_path(self) -> None:
        """알 수 없는 경로는 404를 반환한다."""
        server = HealthServer(port=0)
        server.set_status_provider(lambda: {})
        await server.start()

        assert server._server is not None
        port = server._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /unknown HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            response_str = response.decode("utf-8")
            writer.close()

            assert "404" in response_str
        finally:
            await server.stop()
