"""헬스체크 HTTP 서버 모듈.

외부 패키지 없이 asyncio 표준 라이브러리로 경량 HTTP 서버를 제공한다.
GET /health → 프로세스, DB, 스케줄러 상태를 JSON으로 반환.
"""

from __future__ import annotations

import asyncio
import json
import time
from asyncio import StreamReader, StreamWriter
from datetime import datetime
from typing import Any

from sqlalchemy import text

from src.config import settings
from src.db.session import get_engine
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_PORT = 18923


def _check_db() -> dict[str, Any]:
    """DB 연결 상태를 확인한다."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


def _build_health_response(
    *,
    start_time: float,
    scheduler_running: bool,
    cycle_count: int,
    daily_api_count: int,
) -> dict[str, Any]:
    """헬스체크 응답을 구성한다."""
    uptime_seconds = int(time.time() - start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    db_status = _check_db()

    health: dict[str, Any] = {
        "status": "ok" if db_status["status"] == "ok" else "degraded",
        "timestamp": datetime.now().isoformat(),
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "env": settings.kis.env,
        "components": {
            "db": db_status,
            "scheduler": {
                "status": "ok" if scheduler_running else "stopped",
                "running": scheduler_running,
            },
            "trading": {
                "cycle_count": cycle_count,
                "daily_api_calls": daily_api_count,
            },
        },
    }
    return health


async def _handle_request(
    reader: StreamReader,
    writer: StreamWriter,
    *,
    start_time: float,
    get_status: Any,
) -> None:
    """HTTP 요청을 처리한다."""
    try:
        data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
        request_line = data.decode("utf-8", errors="replace").split("\r\n")[0]
        method, path, *_ = request_line.split(" ", 2)

        if method == "GET" and path == "/health":
            status_info = get_status()
            body = _build_health_response(
                start_time=start_time,
                scheduler_running=status_info.get("scheduler_running", False),
                cycle_count=status_info.get("cycle_count", 0),
                daily_api_count=status_info.get("daily_api_count", 0),
            )
            response_body = json.dumps(body, ensure_ascii=False)
            status_code = 200 if body["status"] == "ok" else 503
            status_text = "OK" if status_code == 200 else "Service Unavailable"
        else:
            response_body = json.dumps({"error": "Not Found"})
            status_code = 404
            status_text = "Not Found"

        response = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(response_body.encode('utf-8'))}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{response_body}"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()
    except Exception:
        logger.debug("헬스체크 요청 처리 중 에러")
    finally:
        writer.close()


class HealthServer:
    """헬스체크 HTTP 서버.

    asyncio 기반 경량 TCP 서버로 /health 엔드포인트를 제공한다.
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
    ) -> None:
        """HealthServer를 초기화한다.

        Args:
            port: 리스닝 포트 (기본값: 8080)
        """
        self._port = port
        self._start_time = time.time()
        self._server: asyncio.Server | None = None
        self._get_status: Any = lambda: {}

    def set_status_provider(self, func: Any) -> None:
        """상태 조회 콜백을 설정한다.

        Args:
            func: scheduler_running, cycle_count, daily_api_count를 반환하는 함수
        """
        self._get_status = func

    async def start(self) -> None:
        """서버를 시작한다."""
        self._server = await asyncio.start_server(
            lambda r, w: _handle_request(
                r, w,
                start_time=self._start_time,
                get_status=self._get_status,
            ),
            host="0.0.0.0",
            port=self._port,
        )
        logger.info("헬스체크 서버 시작: http://0.0.0.0:%d/health", self._port)

    async def stop(self) -> None:
        """서버를 종료한다."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("헬스체크 서버 종료")
