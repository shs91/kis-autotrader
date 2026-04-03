"""환경변수 및 설정값 관리 모듈."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    """환경변수를 조회한다."""
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    """환경변수를 정수로 조회한다."""
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float = 0.0) -> float:
    """환경변수를 실수로 조회한다."""
    return float(os.getenv(key, str(default)))


@dataclass(frozen=True)
class KISConfig:
    """한국투자증권 API 설정."""

    app_key: str = field(default_factory=lambda: _env("KIS_APP_KEY"))
    app_secret: str = field(default_factory=lambda: _env("KIS_APP_SECRET"))
    account_no: str = field(default_factory=lambda: _env("KIS_ACCOUNT_NO"))
    account_product_code: str = field(
        default_factory=lambda: _env("KIS_ACCOUNT_PRODUCT_CODE", "01")
    )
    env: str = field(default_factory=lambda: _env("KIS_ENV", "virtual"))

    @property
    def base_url(self) -> str:
        """API 기본 URL을 반환한다."""
        if self.env == "real":
            return "https://openapi.koreainvestment.com:9443"
        return "https://openapivts.koreainvestment.com:29443"

    @property
    def ws_url(self) -> str:
        """웹소켓 URL을 반환한다."""
        if self.env == "real":
            return "ws://ops.koreainvestment.com:21000"
        return "ws://ops.koreainvestment.com:31000"


def _default_db_url() -> str:
    """KIS_ENV에 따라 기본 DB URL을 반환한다."""
    env = _env("KIS_ENV", "virtual")
    env_key = "DATABASE_URL_REAL" if env == "real" else "DATABASE_URL"
    # 환경별 전용 키가 있으면 우선, 없으면 DATABASE_URL 폴백
    url = _env(env_key)
    if url:
        return url
    return _env("DATABASE_URL", "postgresql://user:password@localhost:5432/kis_trader")


@dataclass(frozen=True)
class DBConfig:
    """데이터베이스 설정."""

    url: str = field(default_factory=_default_db_url)


@dataclass(frozen=True)
class CalendarConfig:
    """Google Calendar 설정."""

    calendar_id: str = field(default_factory=lambda: _env("GOOGLE_CALENDAR_ID"))
    credentials_path: Path = field(
        default_factory=lambda: Path(_env("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
    )
    token_path: Path = field(default_factory=lambda: Path("token.json"))


@dataclass(frozen=True)
class RateLimitConfig:
    """API 호출 제한 설정."""

    per_second: int = field(
        default_factory=lambda: _env_int(
            "API_RATE_LIMIT_PER_SECOND",
            20 if _env("KIS_ENV", "virtual") == "real" else 5,
        )
    )
    daily_limit: int = field(
        default_factory=lambda: _env_int("API_DAILY_CALL_LIMIT", 50000)
    )
    ws_max_reconnect: int = field(
        default_factory=lambda: _env_int("WS_MAX_RECONNECT_ATTEMPTS", 5)
    )
    ws_reconnect_base_delay: int = field(
        default_factory=lambda: _env_int("WS_RECONNECT_BASE_DELAY", 5)
    )


@dataclass(frozen=True)
class TradingConfig:
    """매매 관련 설정."""

    max_loss_rate: float = field(
        default_factory=lambda: _env_float("MAX_LOSS_RATE", 0.03)
    )
    max_position_ratio: float = field(
        default_factory=lambda: _env_float("MAX_POSITION_RATIO", 0.2)
    )
    daily_trade_limit: int = field(
        default_factory=lambda: _env_int("DAILY_TRADE_LIMIT", 10)
    )
    watchlist_codes: list[str] = field(
        default_factory=lambda: [
            c.strip()
            for c in _env("WATCHLIST_CODES", "005930,000660,035420").split(",")
            if c.strip()
        ]
    )


@dataclass(frozen=True)
class StrategyConfig:
    """전략 관련 설정."""

    default: str = field(
        default_factory=lambda: _env("STRATEGY_DEFAULT", "moving_average")
    )
    mappings_raw: str = field(
        default_factory=lambda: _env("STRATEGY_MAPPINGS", "")
    )

    def parse_mappings(self) -> dict[str, str]:
        """STRATEGY_MAPPINGS 환경변수를 파싱한다.

        형식: "005930:rsi,000660:ensemble"

        Returns:
            {종목코드: 전략이름} 딕셔너리
        """
        if not self.mappings_raw:
            return {}
        result: dict[str, str] = {}
        for pair in self.mappings_raw.split(","):
            pair = pair.strip()
            if ":" in pair:
                code, strategy = pair.split(":", 1)
                result[code.strip()] = strategy.strip()
        return result


@dataclass(frozen=True)
class HealthConfig:
    """헬스체크 서버 설정."""

    port: int = field(
        default_factory=lambda: _env_int("HEALTH_PORT", 8080)
    )
    enabled: bool = field(
        default_factory=lambda: _env("HEALTH_ENABLED", "true").lower() == "true"
    )


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram 알림 설정."""

    bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))
    enabled: bool = field(
        default_factory=lambda: _env("TELEGRAM_ENABLED", "false").lower() == "true"
    )


@dataclass(frozen=True)
class Settings:
    """전체 설정을 통합 관리한다."""

    kis: KISConfig = field(default_factory=KISConfig)
    db: DBConfig = field(default_factory=DBConfig)
    calendar: CalendarConfig = field(default_factory=CalendarConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


settings = Settings()
