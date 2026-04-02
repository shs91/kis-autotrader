"""실시간 시세 웹소켓 매니저 모듈."""

from __future__ import annotations

import asyncio
import enum
import json
import time
from typing import Any, Callable, Coroutine

import websockets
import websockets.asyncio.client

from src.config import settings
from src.utils.exceptions import WebSocketError, WebSocketReconnectFailedError
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 구독 디바운싱 최소 간격 (초)
SUBSCRIBE_DEBOUNCE_INTERVAL: float = 1.0

# 수신 확인 대기 시간 (초)
RECEIVE_CONFIRM_TIMEOUT: float = 10.0


class ConnectionState(enum.Enum):
    """웹소켓 연결 상태."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SUBSCRIBING = "SUBSCRIBING"
    ACTIVE = "ACTIVE"


class KISWebSocketManager:
    """KIS 실시간 시세 웹소켓을 관리한다.

    연결 상태 머신, 자동 재연결, 구독 관리, 디바운싱을 포함한다.
    """

    def __init__(self) -> None:
        """KISWebSocketManager를 초기화한다."""
        self._ws_url = settings.kis.ws_url
        self._app_key = settings.kis.app_key
        self._app_secret = settings.kis.app_secret
        self._max_reconnect = settings.rate_limit.ws_max_reconnect
        self._base_delay = settings.rate_limit.ws_reconnect_base_delay

        self._state = ConnectionState.DISCONNECTED
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._subscriptions: set[str] = set()
        self._reconnect_count = 0
        self._last_subscribe_time: float = 0.0
        self._message_handlers: list[Callable[[dict[str, Any]], Coroutine[Any, Any, None]]] = []
        self._receive_task: asyncio.Task[None] | None = None
        self._running = False

        logger.info("KISWebSocketManager 초기화 완료 (url=%s)", self._ws_url)

    @property
    def state(self) -> ConnectionState:
        """현재 연결 상태를 반환한다."""
        return self._state

    @property
    def subscriptions(self) -> set[str]:
        """현재 구독 중인 종목 목록을 반환한다."""
        return self._subscriptions.copy()

    def add_handler(
        self, handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """메시지 수신 핸들러를 등록한다.

        Args:
            handler: 수신 메시지를 처리할 비동기 콜백 함수
        """
        self._message_handlers.append(handler)

    async def connect(self) -> None:
        """웹소켓에 연결한다.

        Raises:
            WebSocketReconnectFailedError: 최대 재연결 횟수 초과 시
        """
        if self._state != ConnectionState.DISCONNECTED:
            logger.warning("이미 연결 중이거나 연결된 상태입니다: %s", self._state.value)
            return

        self._state = ConnectionState.CONNECTING
        logger.info("웹소켓 연결 시도: %s", self._ws_url)

        try:
            self._ws = await websockets.asyncio.client.connect(self._ws_url)
            self._state = ConnectionState.CONNECTED
            self._reconnect_count = 0
            self._running = True

            logger.info("웹소켓 연결 성공")

            # 수신 루프 시작
            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            self._state = ConnectionState.DISCONNECTED
            logger.error("웹소켓 연결 실패: %s", e)
            raise WebSocketError(f"웹소켓 연결 실패: {e}") from e

    async def disconnect(self) -> None:
        """웹소켓 연결을 안전하게 종료한다.

        구독 해제 → 연결 종료 순서를 따른다.
        """
        if self._state == ConnectionState.DISCONNECTED:
            return

        logger.info("웹소켓 연결 종료 시작")
        self._running = False

        # 모든 구독 해제
        for stock_code in list(self._subscriptions):
            await self._send_unsubscribe(stock_code)

        self._subscriptions.clear()

        # 수신 태스크 취소
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # 연결 종료
        if self._ws:
            await self._ws.close()
            self._ws = None

        self._state = ConnectionState.DISCONNECTED
        logger.info("웹소켓 연결 종료 완료")

    async def subscribe(self, stock_code: str) -> None:
        """종목 실시간 시세를 구독한다.

        디바운싱이 적용되며, 구독 후 수신 확인을 기다린다.

        Args:
            stock_code: 종목코드 (6자리)

        Raises:
            WebSocketError: 연결되지 않은 상태에서 구독 시도 시
        """
        if self._state not in (ConnectionState.CONNECTED, ConnectionState.ACTIVE):
            raise WebSocketError(
                f"구독 불가 상태입니다: {self._state.value}"
            )

        if stock_code in self._subscriptions:
            logger.info("이미 구독 중인 종목: %s", stock_code)
            return

        # 디바운싱: 최소 1초 간격
        await self._debounce()

        self._state = ConnectionState.SUBSCRIBING
        logger.info("[구독 등록] 종목=%s", stock_code)

        await self._send_subscribe(stock_code)
        self._subscriptions.add(stock_code)

        self._state = ConnectionState.ACTIVE
        self._last_subscribe_time = time.monotonic()

    async def unsubscribe(self, stock_code: str) -> None:
        """종목 구독을 해제한다.

        Args:
            stock_code: 종목코드 (6자리)
        """
        if stock_code not in self._subscriptions:
            logger.info("구독 중이 아닌 종목: %s", stock_code)
            return

        # 디바운싱: 최소 1초 간격
        await self._debounce()

        logger.info("[구독 해제] 종목=%s", stock_code)
        await self._send_unsubscribe(stock_code)
        self._subscriptions.discard(stock_code)

        if not self._subscriptions:
            self._state = ConnectionState.CONNECTED

    async def _debounce(self) -> None:
        """구독/해제 간 최소 간격을 보장한다."""
        elapsed = time.monotonic() - self._last_subscribe_time
        if elapsed < SUBSCRIBE_DEBOUNCE_INTERVAL:
            wait = SUBSCRIBE_DEBOUNCE_INTERVAL - elapsed
            await asyncio.sleep(wait)

    async def _send_subscribe(self, stock_code: str) -> None:
        """구독 메시지를 전송한다."""
        message = {
            "header": {
                "approval_key": self._app_key,
                "custtype": "P",
                "tr_type": "1",  # 등록
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": "H0STCNT0",  # 실시간 체결가
                    "tr_key": stock_code,
                },
            },
        }

        if self._ws:
            await self._ws.send(json.dumps(message))

    async def _send_unsubscribe(self, stock_code: str) -> None:
        """구독 해제 메시지를 전송한다."""
        message = {
            "header": {
                "approval_key": self._app_key,
                "custtype": "P",
                "tr_type": "2",  # 해제
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": "H0STCNT0",
                    "tr_key": stock_code,
                },
            },
        }

        if self._ws:
            await self._ws.send(json.dumps(message))

    async def _receive_loop(self) -> None:
        """메시지 수신 루프."""
        while self._running and self._ws:
            try:
                raw = await self._ws.recv()
                data = self._parse_message(raw)

                for handler in self._message_handlers:
                    try:
                        await handler(data)
                    except Exception as e:
                        logger.error("메시지 핸들러 에러: %s", e)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("웹소켓 연결이 끊어졌습니다.")
                await self._handle_disconnect()
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("수신 루프 에러: %s", e)

    def _parse_message(self, raw: str | bytes) -> dict[str, Any]:
        """수신 메시지를 파싱한다.

        Args:
            raw: 원본 메시지 (JSON 또는 파이프 구분 문자열)

        Returns:
            파싱된 딕셔너리
        """
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            # KIS 실시간 데이터는 파이프(|)로 구분된 형식일 수 있음
            parts = raw.split("|")
            return {
                "type": "realtime",
                "encrypt": parts[0] if len(parts) > 0 else "",
                "count": parts[1] if len(parts) > 1 else "",
                "tr_id": parts[2] if len(parts) > 2 else "",
                "data": parts[3] if len(parts) > 3 else "",
            }

    async def _handle_disconnect(self) -> None:
        """연결 끊김을 처리하고 자동 재연결을 시도한다.

        Raises:
            WebSocketReconnectFailedError: 최대 재연결 횟수 초과 시
        """
        self._state = ConnectionState.DISCONNECTED
        self._ws = None
        saved_subscriptions = self._subscriptions.copy()

        while self._reconnect_count < self._max_reconnect:
            self._reconnect_count += 1
            delay = min(
                self._base_delay * (2 ** (self._reconnect_count - 1)),
                60.0,
            )

            logger.info(
                "재연결 시도 %d/%d (%.0f초 후)",
                self._reconnect_count,
                self._max_reconnect,
                delay,
            )
            await asyncio.sleep(delay)

            try:
                self._state = ConnectionState.CONNECTING
                self._ws = await websockets.asyncio.client.connect(self._ws_url)
                self._state = ConnectionState.CONNECTED
                self._running = True

                logger.info("재연결 성공")

                # 기존 구독 복원
                self._subscriptions.clear()
                for stock_code in saved_subscriptions:
                    await self.subscribe(stock_code)

                # 수신 루프 재시작
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._reconnect_count = 0
                return

            except Exception as e:
                logger.error("재연결 실패: %s", e)
                self._state = ConnectionState.DISCONNECTED
                self._ws = None

        raise WebSocketReconnectFailedError(
            f"최대 재연결 횟수 초과 ({self._max_reconnect}회)"
        )
