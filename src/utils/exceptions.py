"""커스텀 예외 클래스 정의."""

from __future__ import annotations


class KISAutoTraderError(Exception):
    """KIS 자동매매 시스템 기본 예외."""


class AuthenticationError(KISAutoTraderError):
    """인증 관련 에러."""


class TokenExpiredError(AuthenticationError):
    """토큰 만료 에러."""


class RateLimitExceededError(KISAutoTraderError):
    """API 호출 제한 초과 에러."""


class DailyLimitExceededError(RateLimitExceededError):
    """일일 API 호출 한도 초과 에러."""


class OrderError(KISAutoTraderError):
    """주문 관련 에러."""


class InsufficientBalanceError(OrderError):
    """잔고 부족 에러."""


class WebSocketError(KISAutoTraderError):
    """웹소켓 관련 에러."""


class WebSocketReconnectFailedError(WebSocketError):
    """웹소켓 재연결 실패 에러."""


class StrategyError(KISAutoTraderError):
    """전략 관련 에러."""


class RiskLimitError(StrategyError):
    """리스크 한도 초과 에러."""


class DatabaseError(KISAutoTraderError):
    """데이터베이스 관련 에러."""


class CalendarError(KISAutoTraderError):
    """Google Calendar 관련 에러."""


class WorkerError(KISAutoTraderError):
    """Worker 프로세스 관련 에러."""


class TaskExecutionError(WorkerError):
    """태스크 실행 실패 에러."""
