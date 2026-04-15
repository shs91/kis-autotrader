"""환경변수 및 설정값 관리 모듈."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

# config_overrides.json 로드 결과. _load_overrides()가 import 시점에 채운다.
_overrides: dict[str, str] = {}
_overrides_meta: dict[str, Any] = {}


@dataclass(frozen=True)
class OverrideState:
    """config_overrides.json 적용 상태 스냅샷."""

    values: dict[str, str]
    """적용된 key → 문자열화된 값."""

    meta: dict[str, Any]
    """_meta 내용물 (평탄화 — updated_at, updated_by 등)."""

    source_path: Path
    """config_overrides.json 절대 경로."""

    loaded: bool
    """파일이 실제로 존재하여 로드되었는지 여부."""


def _load_overrides_from(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """지정한 경로에서 config_overrides.json을 로드한다.

    파일이 없으면 ``({}, {})``를 반환한다. 파싱/타입 오류 시 ``RuntimeError``.
    """
    if not path.exists():
        logger.debug("config_overrides.json not found, using .env only")
        return {}, {}

    raw_text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"config_overrides.json parse failed: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError("config_overrides.json root must be an object")

    values: dict[str, str] = {}
    meta: dict[str, Any] = {}

    for key, value in data.items():
        if key == "_meta":
            if isinstance(value, dict):
                meta.update(value)
            continue
        if key.startswith("_"):
            continue
        # bool은 int의 하위 타입이므로 반드시 먼저 체크한다.
        if isinstance(value, bool):
            values[key] = "true" if value else "false"
        elif isinstance(value, str):
            values[key] = value
        elif isinstance(value, (int, float)):
            values[key] = str(value)
        else:
            raise RuntimeError(
                f"config_overrides.json: unsupported type for {key}: "
                f"{type(value).__name__}"
            )

    return values, meta


def _load_overrides() -> None:
    """프로젝트 루트의 config_overrides.json을 로드하여 모듈 전역을 채운다."""
    values, meta = _load_overrides_from(_PROJECT_ROOT / "config_overrides.json")
    _overrides.update(values)
    _overrides_meta.update(meta)
    if values:
        logger.info(
            "config_overrides loaded: %d keys (source=%s)",
            len(values),
            meta.get("updated_by", "unknown"),
        )


_load_overrides()


def _build_override_state() -> OverrideState:
    """현재 모듈 전역 _overrides/_overrides_meta를 기반으로 스냅샷을 만든다."""
    source_path = _PROJECT_ROOT / "config_overrides.json"
    return OverrideState(
        values=dict(_overrides),
        meta=dict(_overrides_meta),
        source_path=source_path,
        loaded=source_path.exists(),
    )


def _env(key: str, default: str = "") -> str:
    """환경변수를 조회한다. config_overrides.json 값이 있으면 우선한다."""
    if key in _overrides:
        return _overrides[key]
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    """환경변수를 정수로 조회한다. override를 반영한다."""
    return int(_env(key, str(default)))


def _env_float(key: str, default: float = 0.0) -> float:
    """환경변수를 실수로 조회한다. override를 반영한다."""
    return float(_env(key, str(default)))


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

    # 포트폴리오 리스크
    max_daily_drawdown: float = field(
        default_factory=lambda: _env_float("MAX_DAILY_DRAWDOWN", 0.05)
    )
    max_consecutive_losses: int = field(
        default_factory=lambda: _env_int("MAX_CONSECUTIVE_LOSSES", 5)
    )
    market_close_cutoff_hour: int = field(
        default_factory=lambda: _env_int("MARKET_CLOSE_CUTOFF_HOUR", 14)
    )
    market_close_cutoff_minute: int = field(
        default_factory=lambda: _env_int("MARKET_CLOSE_CUTOFF_MINUTE", 30)
    )


@dataclass(frozen=True)
class StrategyConfig:
    """전략 관련 설정."""

    default: str = field(
        default_factory=lambda: _env("STRATEGY_DEFAULT", "ensemble")
    )
    mappings_raw: str = field(
        default_factory=lambda: _env("STRATEGY_MAPPINGS", "")
    )

    # 이동평균 전략 파라미터
    ma_short_period: int = field(
        default_factory=lambda: _env_int("STRATEGY_MA_SHORT_PERIOD", 5)
    )
    ma_long_period: int = field(
        default_factory=lambda: _env_int("STRATEGY_MA_LONG_PERIOD", 20)
    )
    ma_max_divergence: float = field(
        default_factory=lambda: _env_float("STRATEGY_MA_MAX_DIVERGENCE", 0.05)
    )

    # RSI 전략 파라미터
    rsi_period: int = field(
        default_factory=lambda: _env_int("STRATEGY_RSI_PERIOD", 14)
    )
    rsi_oversold: float = field(
        default_factory=lambda: _env_float("STRATEGY_RSI_OVERSOLD", 30.0)
    )
    rsi_overbought: float = field(
        default_factory=lambda: _env_float("STRATEGY_RSI_OVERBOUGHT", 70.0)
    )

    # 앙상블 투표 방식 ("majority" 또는 "weighted")
    ensemble_method: str = field(
        default_factory=lambda: _env("STRATEGY_ENSEMBLE_METHOD", "weighted")
    )

    # 리스크: 익절 비율
    take_profit_ratio: float = field(
        default_factory=lambda: _env_float("TAKE_PROFIT_RATIO", 0.05)
    )

    # 최소 신뢰도 (이 미만 시그널 무시)
    min_confidence: float = field(
        default_factory=lambda: _env_float("STRATEGY_MIN_CONFIDENCE", 0.1)
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
class ScreeningConfig:
    """종목 스크리닝 설정."""

    # 조회 설정
    top_n: int = field(
        default_factory=lambda: _env_int("SCREENING_TOP_N", 20)
    )
    interval_cycles: int = field(
        default_factory=lambda: _env_int("SCREENING_INTERVAL_CYCLES", 60)
    )
    max_screened: int = field(
        default_factory=lambda: _env_int("MAX_SCREENED_STOCKS", 15)
    )

    # 사전 필터
    min_price: int = field(
        default_factory=lambda: _env_int("SCREENING_MIN_PRICE", 1000)
    )
    max_price: int = field(
        default_factory=lambda: _env_int("SCREENING_MAX_PRICE", 500000)
    )
    min_market_cap: int = field(
        default_factory=lambda: _env_int("SCREENING_MIN_MARKET_CAP", 100_000_000)
    )
    change_rate_min: float = field(
        default_factory=lambda: _env_float("SCREENING_CHANGE_RATE_MIN", -5.0)
    )
    change_rate_max: float = field(
        default_factory=lambda: _env_float("SCREENING_CHANGE_RATE_MAX", 15.0)
    )
    min_volume: int = field(
        default_factory=lambda: _env_int("SCREENING_MIN_VOLUME", 10000)
    )

    # 스코어링 가중치
    weight_volume_rank: float = field(
        default_factory=lambda: _env_float("SCREENING_WEIGHT_VOLUME_RANK", 0.3)
    )
    weight_change_rate: float = field(
        default_factory=lambda: _env_float("SCREENING_WEIGHT_CHANGE_RATE", 0.3)
    )
    weight_strategy: float = field(
        default_factory=lambda: _env_float("SCREENING_WEIGHT_STRATEGY", 0.4)
    )

    # 최소 종합 점수 (0.0~1.0, 이하 컷)
    min_score: float = field(
        default_factory=lambda: _env_float("SCREENING_MIN_SCORE", 0.3)
    )


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
class WorkerConfig:
    """Worker 프로세스 설정."""

    poll_interval: int = field(
        default_factory=lambda: _env_int("WORKER_POLL_INTERVAL", 30)
    )
    max_retries: int = field(
        default_factory=lambda: _env_int("WORKER_MAX_RETRIES", 5)
    )
    retry_base_delay: int = field(
        default_factory=lambda: _env_int("WORKER_RETRY_BASE_DELAY", 60)
    )
    batch_size: int = field(
        default_factory=lambda: _env_int("WORKER_BATCH_SIZE", 10)
    )
    enabled: bool = field(
        default_factory=lambda: _env("WORKER_ENABLED", "true").lower() == "true"
    )


@dataclass(frozen=True)
class RedisConfig:
    """Redis 연결 설정."""

    url: str = field(
        default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0")
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
    screening: ScreeningConfig = field(default_factory=ScreeningConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    overrides: OverrideState = field(default_factory=_build_override_state)


settings = Settings()


def get_active_overrides() -> OverrideState:
    """현재 프로세스에 적용된 config override 상태를 반환한다.

    대시보드/디버깅 용도. ``settings.overrides``와 동일한 객체를 반환한다.
    """
    return settings.overrides
