"""매매 엔진 모듈 — 시세조회·전략분석·리스크체크·주문실행·DB저장을 통합한다."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from src.api.account import AccountAPI, Balance
from src.api.client import KISClient
from src.api.order import OrderAPI
from src.api.quote import CurrentPrice, QuoteAPI
from src.calendar.event import CalendarEventCreator
from src.calendar.google_auth import GoogleCalendarAuth
from src.config import settings
from src.db.event_logger import log_trade, log_warning
from src.db.models import BuyReason, OrderStatus, OrderType, SellReason, TradeType
from src.db.repository import (
    DailyPerformanceRepository,
    DailySummaryRepository,
    MarketActionRepository,
    OrderRepository,
    PortfolioRepository,
    ScreeningResultRepository,
    StockRepository,
    TradeRepository,
    WatchlistRepository,
)
from src.db.session import get_session
from src.notify.telegram import TelegramNotifier
from src.strategy.base import BaseStrategy, Signal, SignalType
from src.strategy.registry import StrategyRegistry
from src.strategy.risk import RiskManager
from src.strategy.screener import StockScreener
from src.strategy.selector import StrategySelector
from src.utils.exceptions import DailyLimitExceededError
from src.utils.logger import setup_logger
from src.worker.queue import TaskQueueService

logger = setup_logger(__name__)

# 잔고 조회 캐시 유효 시간(초) — 매 사이클 잔고 조회도 줄임
BALANCE_CACHE_TTL: float = 60.0


class TradingEngine:
    """매매 파이프라인을 통합 실행하는 엔진.

    시세조회 → 전략분석 → 리스크체크 → 주문실행 → DB기록
    """

    def __init__(
        self,
        watchlist: list[str] | None = None,
        strategy: BaseStrategy | None = None,
        selector: StrategySelector | None = None,
    ) -> None:
        """매매 엔진을 초기화한다.

        Args:
            watchlist: 고정 관심종목코드 목록 (None이면 설정에서 로드)
            strategy: 매매 전략 (단일 전략 모드, 하위 호환용)
            selector: 전략 셀렉터 (다중 전략 모드)
        """
        self._client = KISClient()
        self._quote = QuoteAPI(client=self._client)
        self._order = OrderAPI(client=self._client)
        self._account = AccountAPI(client=self._client)

        # 전략 셀렉터 초기화: selector > strategy > 설정 파일
        if selector is not None:
            self._selector = selector
        elif strategy is not None:
            registry = StrategyRegistry()
            registry.register("custom", strategy)
            self._selector = StrategySelector(registry, default_strategy="custom")
        else:
            registry = StrategyRegistry.create_default()
            self._selector = StrategySelector.from_config(registry)

        self._risk = RiskManager()
        self._notifier = TelegramNotifier()
        self._screener = StockScreener()
        self._task_queue = TaskQueueService()

        # 관심종목: 직접 지정 시 고정, 미지정 시 DB에서 매 사이클 조회
        self._fixed_watchlist: list[str] | None = watchlist
        # 스크리닝으로 발굴된 동적 종목
        self._screened_codes: set[str] = set()

        self._today_trade_count = 0
        self._cycle_count = 0
        self._daily_limit_reached = False

        # 사이클별 전략 평가 카운터 (시그널 가뭄 진단용)
        self._cycle_buy_count = 0
        self._cycle_sell_count = 0
        self._cycle_hold_count = 0
        self._cycle_max_confidence = 0.0

        # 스크리닝 종목 시그널 품질 카운터
        self._cycle_screening_buy: int = 0
        self._cycle_screening_sell: int = 0
        self._cycle_screening_hold: int = 0

        # 일봉 캐시: {종목코드: (날짜, DataFrame)}
        self._daily_cache: dict[str, tuple[str, pd.DataFrame]] = {}
        # 잔고 캐시: (조회시각, Balance)
        self._balance_cache: tuple[float, Balance] | None = None
        # 고점 캐시: {종목코드: 고점가격} — 트레일링 스톱 계산용
        self._peak_prices: dict[str, float] = {}

        logger.info(
            "매매 엔진 초기화: 기본전략=%s, 관심종목모드=%s",
            self._selector.default_strategy_name,
            "고정" if self._fixed_watchlist else "DB",
        )

    def _get_watchlist_codes(self) -> list[str]:
        """관심종목 코드를 반환한다.

        직접 지정된 watchlist가 있으면 그대로 사용,
        없으면 DB에서 매번 조회한다. DB 실패 시 .env 폴백.

        Returns:
            관심종목 코드 리스트
        """
        if self._fixed_watchlist is not None:
            return self._fixed_watchlist
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                codes = repo.get_codes()
            if codes:
                return codes
            return settings.trading.watchlist_codes
        except Exception:
            logger.exception("관심종목 DB 조회 실패, .env 폴백")
            return settings.trading.watchlist_codes

    @property
    def _watchlist(self) -> list[str]:
        """관심종목을 반환한다 (외부 호환용)."""
        return self._get_watchlist_codes()

    def _build_monitor_targets(self, held_codes: set[str]) -> list[str]:
        """모니터링 대상 종목을 구성한다.

        고정 관심종목 + 스크리닝 발굴 종목 + 보유 종목을 병합한다.

        Args:
            held_codes: 현재 보유 종목코드 집합

        Returns:
            중복 제거된 모니터링 대상 종목코드 목록
        """
        all_codes: dict[str, None] = {}
        for code in held_codes:
            all_codes[code] = None
        for code in self._get_watchlist_codes():
            all_codes[code] = None
        for code in self._screened_codes:
            all_codes[code] = None
        return list(all_codes)

    # ── 일봉 캐시 ─────────────────────────────────────────

    async def _get_daily_df(self, stock_code: str) -> pd.DataFrame | None:
        """일봉 DataFrame을 반환한다. 당일 캐시가 있으면 API 호출을 생략한다.

        Args:
            stock_code: 종목코드

        Returns:
            종가 DataFrame 또는 None (데이터 부족 시)
        """
        today_str = date.today().isoformat()

        # 캐시 히트: 같은 날짜면 재사용
        cached = self._daily_cache.get(stock_code)
        if cached is not None and cached[0] == today_str:
            return cached[1]

        # API 호출
        daily_prices = await self._quote.get_daily_price(stock_code)
        min_daily_count = settings.strategy.ma_long_period + 2
        if len(daily_prices) < min_daily_count:
            logger.info("[%s] 일봉 데이터 부족 (%d건), 스킵", stock_code, len(daily_prices))
            self._record_metric("DAILY_DATA_INSUFFICIENT", {
                "stock_code": stock_code,
                "returned_count": len(daily_prices),
                "required_count": min_daily_count,
                "cycle": self._cycle_count,
            })
            return None

        df = pd.DataFrame(
            [
                {"close": item.close_price, "date": item.date}
                for item in reversed(daily_prices)
            ]
        )

        self._daily_cache[stock_code] = (today_str, df)
        return df

    def _load_peak_prices(self) -> dict[str, float]:
        """portfolios.peak_price를 읽어 인메모리 peak dict를 시드한다."""
        from src.db.repository import PortfolioRepository

        try:
            with get_session() as session:
                return PortfolioRepository(session).get_peak_prices()
        except Exception:
            logger.exception("peak_price 시드 로드 실패 — 빈 dict로 시작")
            return {}

    # ── 잔고 캐시 ─────────────────────────────────────────

    async def _get_balance(self, force: bool = False) -> Balance:
        """잔고를 조회한다. TTL 내이면 캐시를 반환한다.

        Args:
            force: True이면 캐시를 무시하고 강제 조회

        Returns:
            잔고 정보
        """
        now = datetime.now().timestamp()

        if not force and self._balance_cache is not None:
            cached_time, cached_balance = self._balance_cache
            if now - cached_time < BALANCE_CACHE_TTL:
                return cached_balance

        balance = await self._account.get_balance()
        self._balance_cache = (now, balance)
        return balance

    def _invalidate_balance_cache(self) -> None:
        """잔고 캐시를 무효화한다 (주문 실행 후 호출)."""
        self._balance_cache = None

    async def _set_daily_limit_reached(self) -> None:
        """일일 한도 초과 상태를 설정하고 알림을 전송한다."""
        if not self._daily_limit_reached:
            await self._notifier.notify_error(
                "장중 매매", "API 일일 한도 초과, 당일 매매 사이클 중단"
            )
        self._daily_limit_reached = True
        logger.warning("API 일일 한도 초과, 당일 매매 사이클 중단")
        log_warning("API 일일 한도 초과, 당일 매매 사이클 중단")
        self._record_metric("API_LIMIT", {"cycle": self._cycle_count})

    # ── 메인 작업 ─────────────────────────────────────────

    async def pre_market(self) -> None:
        """장 시작 전 작업: 토큰 갱신, 잔고 확인, 일봉 캐싱, 스크리닝."""
        logger.info("=== 장 시작 전 작업 시작 ===")
        self._today_trade_count = 0
        self._cycle_count = 0
        self._daily_limit_reached = False
        self._risk.reset_daily_risk()
        self._screened_codes.clear()
        self._daily_cache.clear()
        self._balance_cache = None
        self._peak_prices = self._load_peak_prices()

        try:
            await self._client._auth.get_access_token()
            logger.info("토큰 갱신 완료")

            balance = await self._get_balance(force=True)
            logger.info(
                "잔고 확인 — 예수금: %s원, 보유종목: %d개, 평가손익: %s원",
                f"{balance.deposit:,}",
                len(balance.holdings),
                f"{balance.total_profit_loss:,}",
            )

            for h in balance.holdings:
                logger.info(
                    "  보유: %s(%s) %d주, 평균가 %.0f, 수익률 %.2f%%",
                    h.stock_name, h.stock_code, h.quantity, h.avg_price, h.profit_rate,
                )

            await self._seed_watchlist_from_env()

            # 관심종목 일봉 사전 캐싱 + 종목명 사전 등록
            watchlist_codes = self._get_watchlist_codes()
            for code in watchlist_codes:
                await self._get_daily_df(code)
            logger.info("관심종목 일봉 캐싱 완료 (%d종목)", len(self._daily_cache))
            await self._prefetch_stock_names(watchlist_codes)

            # 장 시작 전 스크리닝 1회 실행
            await self._screen_stocks()

        except Exception:
            logger.exception("장 시작 전 작업 중 에러 발생")

        logger.info("=== 장 시작 전 작업 완료 ===")

    async def run_trading_cycle(self) -> None:
        """장중 매매 사이클 1회 실행."""
        self._cycle_count += 1

        # 일일 한도 초과 또는 포트폴리오 리스크 시 이후 사이클 전부 즉시 중단
        if self._daily_limit_reached:
            return
        if self._risk.is_portfolio_halted:
            logger.info("포트폴리오 리스크 한도 도달, 당일 매매 중단 (연패=%d, 누적PnL=%d)",
                        self._risk.consecutive_losses, self._risk.daily_cumulative_pnl)
            return

        logger.info("--- 장중 매매 사이클 #%d 시작 ---", self._cycle_count)
        limiter = self._client._limiter
        self._record_metric("CYCLE_START", {
            "cycle": self._cycle_count,
            "api_calls": limiter.daily_count,
            "api_limit": limiter.daily_limit,
            "trade_count": self._today_trade_count,
        })

        exit_reason: str = "completed"
        held_codes: set[str] = set()
        targets: list[str] = []
        try:
            # 서킷 브레이커가 열려있으면 사이클 즉시 스킵
            if self._client.circuit_breaker.is_open:
                logger.warning("서킷 브레이커 열림 — 사이클 #%d 즉시 스킵", self._cycle_count)
                exit_reason = "circuit_breaker_open"
                return

            if self._risk.check_daily_trade_limit(self._today_trade_count):
                logger.warning("일일 매매 횟수 한도 도달, 사이클 스킵")
                exit_reason = "trade_limit"
                return

            # 주기적 스크리닝 (N사이클마다)
            if self._cycle_count % self._screener.config.interval_cycles == 0:
                try:
                    await self._screen_stocks()
                except DailyLimitExceededError:
                    await self._set_daily_limit_reached()
                    exit_reason = "api_limit_screening"
                    return

            try:
                balance = await self._get_balance()
            except DailyLimitExceededError:
                self._daily_limit_reached = True
                logger.warning("API 일일 한도 초과, 당일 매매 사이클 중단")
                exit_reason = "api_limit_balance"
                return
            except Exception:
                logger.exception("잔고 조회 실패, 사이클 스킵")
                exit_reason = "balance_error"
                return

            held_codes = {h.stock_code for h in balance.holdings if h.quantity > 0}
            watchlist_codes = self._get_watchlist_codes()
            targets = self._build_monitor_targets(held_codes)
            logger.info(
                "모니터링 대상: %d종목 (보유 %d + 관심 %d + 발굴 %d)",
                len(targets),
                len(held_codes),
                len(watchlist_codes),
                len(self._screened_codes),
            )
            # 스크리닝→시그널 파이프라인 가시화 (proposal 2026-04-16):
            # 이번 사이클에서 평가할 종목 리스트와 원천별 카운트를
            # system_metrics 에 EVAL_TARGETS 레코드로 기록한다.
            self._record_eval_targets(
                cycle_number=self._cycle_count,
                targets=targets,
                counts={
                    "screening": len(self._screened_codes),
                    "watchlist": len(watchlist_codes),
                    "positions": len(held_codes),
                },
            )

            # 사이클별 전략 평가 카운터 리셋
            self._cycle_buy_count = 0
            self._cycle_sell_count = 0
            self._cycle_hold_count = 0
            self._cycle_max_confidence = 0.0
            self._cycle_screening_buy = 0
            self._cycle_screening_sell = 0
            self._cycle_screening_hold = 0

            for stock_code in targets:
                # 서킷 브레이커가 열려있으면 사이클 즉시 중단
                if self._client.circuit_breaker.is_open:
                    logger.warning(
                        "서킷 브레이커 열림 — 나머지 %d종목 스킵, 사이클 조기 종료",
                        len(targets) - targets.index(stock_code),
                    )
                    exit_reason = "circuit_breaker_open"
                    return
                try:
                    is_held = stock_code in held_codes
                    holding_info = self._find_holding_from_balance(balance, stock_code)
                    await self._process_stock(stock_code, balance.deposit, is_held, holding_info)
                except DailyLimitExceededError:
                    await self._set_daily_limit_reached()
                    exit_reason = "api_limit_processing"
                    return
                except Exception:
                    logger.exception("종목 처리 중 에러: %s", stock_code)
                    self._record_metric("ERROR", {
                        "cycle": self._cycle_count,
                        "stock_code": stock_code,
                        "error": "종목 처리 실패",
                    })

            total_evaluated = (
                self._cycle_buy_count + self._cycle_sell_count + self._cycle_hold_count
            )
            if total_evaluated > 0:
                logger.info(
                    "사이클 #%d 전략 요약: 평가 %d종목, BUY %d / SELL %d / HOLD %d, "
                    "max_confidence=%.3f, 스크리닝 %d종목",
                    self._cycle_count,
                    total_evaluated,
                    self._cycle_buy_count,
                    self._cycle_sell_count,
                    self._cycle_hold_count,
                    self._cycle_max_confidence,
                    len(self._screened_codes),
                )
                self._record_metric("SIGNAL_SUMMARY", {
                    "cycle": self._cycle_count,
                    "evaluated": total_evaluated,
                    "buy_count": self._cycle_buy_count,
                    "sell_count": self._cycle_sell_count,
                    "hold_count": self._cycle_hold_count,
                    "max_confidence": round(self._cycle_max_confidence, 4),
                    "screened_count": len(self._screened_codes),
                    "screening_buy": self._cycle_screening_buy,
                    "screening_sell": self._cycle_screening_sell,
                    "screening_hold": self._cycle_screening_hold,
                })
        finally:
            limiter = self._client._limiter
            self._record_metric("CYCLE_END", {
                "cycle": self._cycle_count,
                "exit_reason": exit_reason,
                "trade_count": self._today_trade_count,
                "api_calls": limiter.daily_count,
                "api_limit": limiter.daily_limit,
                "monitor_stocks": len(targets),
                "held_stocks": len(held_codes),
                "screened_stocks": len(self._screened_codes),
            })
            logger.info(
                "--- 사이클 #%d %s — 매매 %d건, API %d/%d, "
                "모니터링 %d종목(보유 %d/발굴 %d) ---",
                self._cycle_count,
                "완료" if exit_reason == "completed" else f"조기종료({exit_reason})",
                self._today_trade_count,
                limiter.daily_count,
                limiter.daily_limit,
                len(targets),
                len(held_codes),
                len(self._screened_codes),
            )

    async def post_market(self) -> None:
        """장 마감 후 작업: 체결 내역 조회, 일일 성과 저장."""
        logger.info("=== 장 마감 후 작업 시작 ===")

        try:
            balance = await self._get_balance(force=True)

            # KIS 모의투자 환경의 inquire-daily-ccld API가 종종 빈 결과/500을
            # 반환해 KIS executions를 그대로 신뢰할 수 없다. 모든 장 마감 집계는
            # DB trades 테이블을 기준으로 계산한다. KIS executions는 부가 로깅
            # 용도로만 사용.
            kis_executions = await self._account.get_executions()
            today = date.today()
            trades = self._load_today_trades(today)

            buy_count = sum(1 for t in trades if t.trade_type == TradeType.BUY)
            sell_count = sum(1 for t in trades if t.trade_type == TradeType.SELL)
            realized_pl = sum(
                (t.profit_loss_amount or 0)
                for t in trades
                if t.trade_type == TradeType.SELL
            )
            sell_total = sum(
                t.total_amount
                for t in trades
                if t.trade_type == TradeType.SELL
            )
            realized_rate = (
                (realized_pl / sell_total * 100.0) if sell_total > 0 else 0.0
            )

            logger.info(
                "당일 체결 건수(DB): %d (매수 %d / 매도 %d), "
                "실현손익: %s원 (%.2f%%) | "
                "평가손익: %s원 (%.2f%%) | KIS API 체결=%d건",
                len(trades),
                buy_count,
                sell_count,
                f"{realized_pl:,}",
                realized_rate,
                f"{balance.total_profit_loss:,}",
                balance.total_profit_rate,
                len(kis_executions),
            )

            # Worker Queue 경유: 일일 성과·포트폴리오·집계·캘린더·텔레그램
            today_str = today.isoformat()
            self._enqueue_daily_performance(balance, trades)
            self._enqueue_sync_portfolio(balance)
            self._enqueue_daily_summary(today_str)
            self._enqueue_calendar_event(
                trades=trades,
                realized_profit_loss=realized_pl,
                realized_rate=realized_rate,
            )
            self._enqueue_telegram_daily_summary(
                balance=balance,
                buy_count=buy_count,
                sell_count=sell_count,
                realized_profit_loss=realized_pl,
                realized_rate=realized_rate,
            )

            self._client._limiter.log_daily_count()
            logger.info(
                "[일일결산] 사이클=%d, 체결=%d건 (매수 %d / 매도 %d), "
                "발굴=%d종목, 실현손익=%s원 (%.2f%%)",
                self._cycle_count,
                len(trades),
                buy_count,
                sell_count,
                len(self._screened_codes),
                f"{realized_pl:,}",
                realized_rate,
            )

        except Exception:
            logger.exception("장 마감 후 작업 중 에러 발생")

        logger.info("=== 장 마감 후 작업 완료 ===")

    # ── 종목 스크리닝 ─────────────────────────────────────

    async def _screen_stocks(self) -> None:
        """screening_results 테이블에서 ScreeningWorker의 최신 결과를 읽는다.

        실제 스크리닝(API 호출 + 전략 분석)은 ScreeningWorker가 별도로 수행한다.
        메인 엔진은 DB 결과만 읽어 매매 대상에 추가한다.
        converted_to_trade 플래그와 무관하게 상위 랭킹 종목을 평가 대상에
        포함한다 — 엔진이 자체 전략 분석을 수행하므로 Worker의 사전 필터에
        의존하지 않는다.
        """
        scfg = self._screener.config
        if len(self._screened_codes) >= scfg.max_screened:
            return

        try:
            today = date.today()
            with get_session() as session:
                repo = ScreeningResultRepository(session)
                results = repo.get_by_date(today)

            new_codes: list[str] = []
            name_map: dict[str, str] = {}
            seen: set[str] = set()
            watchlist_set = set(self._get_watchlist_codes())
            converted_count = 0
            for r in results:
                if r.converted_to_trade:
                    converted_count += 1
                if r.stock_code in seen:
                    continue
                seen.add(r.stock_code)
                if r.stock_name and r.stock_name != r.stock_code:
                    name_map[r.stock_code] = r.stock_name
                if r.stock_code in self._screened_codes:
                    continue
                if r.stock_code in watchlist_set:
                    continue
                new_codes.append(r.stock_code)

            remaining = scfg.max_screened - len(self._screened_codes)
            added = new_codes[:remaining]

            if results:
                unique_count = len(seen)
                logger.info(
                    "스크리닝 DB 조회: %d건 (고유 %d종목, converted %d건)",
                    len(results), unique_count, converted_count,
                )

            if added:
                self._screened_codes.update(added)
                logger.info(
                    "스크리닝 결과 반영: 신규 %d종목 (누적 %d/%d)",
                    len(added),
                    len(self._screened_codes),
                    scfg.max_screened,
                )
            elif results and not added:
                logger.info(
                    "스크리닝 결과 반영 0종목 (이미 등록 %d, 관심종목 제외)",
                    len(self._screened_codes),
                )

            # screening_results에 있는 종목명을 stocks 테이블에 upsert
            # → _process_stock의 _resolve_stock_name 폴백 경로에서 사용됨
            if name_map:
                self._upsert_stock_names(name_map)
        except Exception:
            logger.exception("스크리닝 결과 DB 조회 실패")

    # ── 개별 종목 처리 ────────────────────────────────────

    async def _process_stock(
        self,
        stock_code: str,
        deposit: int,
        is_held: bool,
        holding_info: dict[str, float] | None,
    ) -> None:
        """개별 종목에 대해 시세조회 → 전략 → 주문을 수행한다.

        일봉은 캐시를 사용하고, 현재가만 실시간 조회한다.

        Args:
            stock_code: 종목코드
            deposit: 가용 예수금
            is_held: 보유 여부
            holding_info: 보유 정보 (보유 시)
        """
        # 1. 일봉 데이터 (캐시 활용)
        df = await self._get_daily_df(stock_code)
        if df is None:
            # 일봉이 없어도 보유 종목은 현재가 기준 손절/익절은 평가한다.
            # (전략 매도는 일봉에 의존하므로 불가 — 리스크 청산만 수행)
            # ETN 등 일봉 조회가 불가한 종목의 리스크 청산이 통째로
            # 누락되던 문제를 보완한다.
            if is_held and holding_info is not None:
                await self._evaluate_held_without_daily(stock_code, holding_info)
            else:
                self._record_metric("EVAL_SKIP", {
                    "stock_code": stock_code,
                    "skip_reason": "daily_data_insufficient",
                    "cycle": self._cycle_count,
                })
            return

        # 2. 현재가 조회 (실시간)
        current = await self._quote.get_current_price(stock_code)

        # 2-1. 종목명 해결: API 응답 → DB 조회 → 코드 fallback
        self._resolve_current_stock_name(current, stock_code)

        # 3. 전략 분석 (보유/미보유 모두 실행)
        strategy = self._selector.get_strategy(stock_code)
        signal = strategy.analyze(df)
        logger.info(
            "[%s %s] 전략=%s, 보유=%s, 시그널=%s, 신뢰도=%.2f, 현재가=%s",
            stock_code,
            current.stock_name,
            strategy.name,
            "Y" if is_held else "N",
            signal.signal_type.value,
            signal.confidence,
            f"{current.current_price:,}",
        )

        # 3-1. 사이클 전략 평가 카운터 갱신
        if signal.signal_type == SignalType.BUY:
            self._cycle_buy_count += 1
        elif signal.signal_type == SignalType.SELL:
            self._cycle_sell_count += 1
        else:
            self._cycle_hold_count += 1
        if signal.confidence > self._cycle_max_confidence:
            self._cycle_max_confidence = signal.confidence

        # 3-1a. 스크리닝 종목 시그널 품질 카운터 갱신
        if stock_code in self._screened_codes:
            if signal.signal_type == SignalType.BUY:
                self._cycle_screening_buy += 1
            elif signal.signal_type == SignalType.SELL:
                self._cycle_screening_sell += 1
            else:
                self._cycle_screening_hold += 1

        # 3-2. 시그널 DB 기록 (BUY/SELL만, action_taken은 아래서 결정)
        will_act = False
        skip_reason: str | None = None

        # 4. 보유 종목 처리
        if is_held and holding_info is not None:
            will_act = signal.signal_type == SignalType.SELL and signal.confidence >= 0.1
            if not will_act and signal.signal_type == SignalType.SELL:
                skip_reason = "low_confidence_sell"
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=will_act,
                skip_reason=skip_reason,
            )
            await self._process_held_stock(
                stock_code, current.current_price, holding_info, signal,
                stock_name=current.stock_name,
            )
            return

        # 5. 미보유 종목 — 시그널 처리
        if signal.signal_type == SignalType.HOLD:
            skip_reason = "hold_action"
            self._record_signal_skip(
                stock_code, current.stock_name, signal, skip_reason,
            )
            return

        if signal.signal_type == SignalType.SELL:
            skip_reason = "sell_without_position"
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=False,
                skip_reason=skip_reason,
            )
            return

        # BUY 시그널 — 일일 매매 한도 체크 (proposal 2026-05-18: BUY_REJECT 진단)
        if self._risk.check_daily_trade_limit(self._today_trade_count):
            skip_reason = "daily_trade_limit"
            self._record_buy_reject(
                stock_code=stock_code,
                reason="DAILY_TRADE_LIMIT",
                confidence=signal.confidence,
                context={"trade_count": self._today_trade_count},
            )
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=False,
                skip_reason=skip_reason,
            )
            return

        # BUY 시그널 — 게이트 사유 진단 (저신뢰/잔고/리스크)
        gate_reason = self._risk.check_buy_gates(signal, float(deposit))
        if gate_reason is not None:
            skip_reason = "risk_rejected"
            self._record_buy_reject(
                stock_code=stock_code,
                reason=gate_reason,
                confidence=signal.confidence,
                context={"balance": float(deposit)},
            )
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=False,
                skip_reason=skip_reason,
            )
            return

        # check_buy_gates가 halt(MAX_CONSECUTIVE_LOSSES/MAX_DAILY_DRAWDOWN) +
        # MARKET_CLOSE_GUARD + INSUFFICIENT_CASH + LOW_CONFIDENCE 모두 잡으므로
        # validate_order 호출은 잉여. POSITION_RATIO만 quantity ≤ 0 분기에서 분류.
        quantity = self._risk.calculate_position_size(
            float(deposit), float(current.current_price)
        )
        if quantity <= 0:
            skip_reason = "zero_quantity"
            logger.info("[%s] 매수 가능 수량 0, 스킵", stock_code)
            self._record_buy_reject(
                stock_code=stock_code,
                reason="POSITION_RATIO",
                confidence=signal.confidence,
                context={
                    "balance": float(deposit),
                    "price": float(current.current_price),
                },
            )
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=False,
                skip_reason=skip_reason,
            )
            return
        self._record_signal_to_db(
            stock_code, current.stock_name, signal, action_taken=True,
        )
        await self._execute_buy(
            stock_code, current.stock_name, quantity, current.current_price,
            signal=signal, strategy_name=strategy.name,
        )

    def _resolve_current_stock_name(self, current: CurrentPrice, stock_code: str) -> str:
        """현재가 응답의 종목명을 해결한다: API 응답 → DB 조회 → 코드 fallback.

        해결한 이름을 ``current.stock_name``에 반영하고 동일 값을 반환한다.

        Args:
            current: 현재가 정보 (stock_name이 보정됨)
            stock_code: 종목코드

        Returns:
            해결된 종목명
        """
        if current.stock_name and current.stock_name != stock_code:
            self._update_stock_name_if_needed(stock_code, current.stock_name)
        else:
            resolved = self._resolve_stock_name(stock_code)
            if resolved:
                current.stock_name = resolved
            else:
                # 최후 수단: 코드를 이름으로 사용하되 로그 남김
                current.stock_name = stock_code
                logger.debug("종목명 미해결: %s (API·DB 모두 빈 값)", stock_code)
        return current.stock_name

    async def _evaluate_held_without_daily(
        self,
        stock_code: str,
        holding: dict[str, float],
    ) -> None:
        """일봉 데이터가 없을 때 보유 종목의 손절/익절만 현재가 기준으로 평가한다.

        전략 매도(데드크로스 등)는 일봉이 필요하므로 생략하고, 평균단가 대비
        손절/익절 조건만 검사한다. HOLD 시그널을 넘겨 ``_process_held_stock``의
        전략 매도 분기를 타지 않도록 한다.

        Args:
            stock_code: 종목코드
            holding: 보유 정보 (avg_price, quantity)
        """
        current = await self._quote.get_current_price(stock_code)
        stock_name = self._resolve_current_stock_name(current, stock_code)

        self._record_metric("RISK_ONLY_EVAL", {
            "stock_code": stock_code,
            "current_price": int(current.current_price),
            "avg_price": holding["avg_price"],
            "cycle": self._cycle_count,
        })
        logger.info(
            "[%s %s] 일봉 없음 — 현재가 기준 손절/익절만 평가 (현재가=%s, 매입가=%.0f)",
            stock_code, stock_name, f"{current.current_price:,}", holding["avg_price"],
        )

        # HOLD 시그널을 넘겨 전략 매도 분기는 건너뛰고 손절/익절만 평가
        hold_signal = Signal(signal_type=SignalType.HOLD, confidence=0.0)
        await self._process_held_stock(
            stock_code, current.current_price, holding, hold_signal,
            stock_name=stock_name,
        )

    async def _process_held_stock(
        self,
        stock_code: str,
        current_price: int,
        holding: dict[str, float],
        signal: Signal,
        stock_name: str = "",
    ) -> None:
        """보유 종목의 매도 판단을 수행한다.

        우선순위: 손절 > 마감 청산 게이트 > 트레일링(또는 고정 익절) > 전략 매도(데드크로스)
        (TRAILING_STOP_ENABLED=false이면 트레일링 대신 기존 고정 익절을 평가)

        Args:
            stock_code: 종목코드
            current_price: 현재가
            holding: 보유 정보
            signal: 전략 분석 시그널
            stock_name: 종목명
        """
        # 비정상 시세 가드: 현재가가 0 이하이면(개장 직후 미체결·거래정지·조회 실패 등)
        # 손실률이 -100%로 잘못 계산돼 손절/트레일링이 오발동한다. 매도 평가를
        # 통째로 스킵하고 다음 사이클에서 정상 시세로 재평가한다.
        if current_price <= 0:
            logger.warning(
                "[%s] 비정상 시세(현재가 %s) — 매도 평가 스킵 (매입가 %.0f)",
                stock_code, current_price, holding["avg_price"],
            )
            self._record_metric("INVALID_PRICE_SKIP", {
                "stock_code": stock_code,
                "current_price": int(current_price),
                "cycle": self._cycle_count,
            })
            return

        avg_price = holding["avg_price"]
        quantity = int(holding["quantity"])

        # 고점(peak) 갱신 — 핫패스 인메모리 단일 소스
        prev = self._peak_prices.get(stock_code)
        seed = prev if prev is not None else max(avg_price, float(current_price))
        peak = max(seed, float(current_price))
        self._peak_prices[stock_code] = peak

        if self._risk.should_stop_loss(float(current_price), avg_price):
            logger.warning(
                "[%s] 손절 매도 실행 (현재가: %d, 매입가: %.0f)",
                stock_code, current_price, avg_price,
            )
            await self._execute_sell(
                stock_code, quantity, current_price,
                reason="손절", avg_price=avg_price, stock_name=stock_name,
            )
            return

        # 2순위: 마감 임박 강제 청산 게이트 (이익 포지션 한정, 트레일링과 독립)
        if self._risk.should_close_for_market_end(float(current_price), avg_price):
            logger.info(
                "[%s] 마감 청산 게이트 매도 (현재가: %d, 매입가: %.0f)",
                stock_code, current_price, avg_price,
            )
            await self._execute_sell(
                stock_code, quantity, current_price,
                reason="마감청산", avg_price=avg_price, stock_name=stock_name,
            )
            return

        # 3순위: 트레일링 스톱 (활성화 시 익절 대체) / 비활성 시 고정 익절 폴백
        if settings.strategy.trailing_stop_enabled:
            if self._risk.should_trailing_stop(float(current_price), avg_price, peak):
                logger.info(
                    "[%s] 트레일링 매도 (현재가: %d, 고점: %.0f, 매입가: %.0f)",
                    stock_code, current_price, peak, avg_price,
                )
                await self._execute_sell(
                    stock_code, quantity, current_price,
                    reason="트레일링", avg_price=avg_price, stock_name=stock_name,
                )
                return
        else:
            if self._risk.should_take_profit(float(current_price), avg_price):
                logger.info(
                    "[%s] 익절 매도 실행 (현재가: %d, 매입가: %.0f)",
                    stock_code, current_price, avg_price,
                )
                await self._execute_sell(
                    stock_code, quantity, current_price,
                    reason="익절", avg_price=avg_price, stock_name=stock_name,
                )
                return

        if signal.signal_type == SignalType.SELL and signal.confidence >= 0.1:
            logger.info(
                "[%s] 전략 매도 실행 — %s (현재가: %d, 매입가: %.0f)",
                stock_code, signal.reason, current_price, avg_price,
            )
            await self._execute_sell(
                stock_code, quantity, current_price,
                reason="전략매도", avg_price=avg_price,
                signal_type=signal.reason.split(" ")[0] if signal.reason else None,
                stock_name=stock_name,
            )

    # ── 주문 실행 ─────────────────────────────────────────

    async def _execute_buy(
        self, stock_code: str, stock_name: str, quantity: int, price: int,
        signal: Signal | None = None, strategy_name: str = "",
    ) -> None:
        """매수 주문을 실행하고 DB에 기록한다."""
        # KIS 종목마스터 sync 결과(market_actions) 기반 차단 lookup.
        # 거래정지/관리종목/정리매매/시장경고/경고예고/불성실공시 중 하나라도 ON이면
        # 매수를 막는다. 미등록 종목은 통과(안전 기본값 — sync 전 매매 위축 방지).
        block_reasons = self._check_market_action_block(stock_code)
        if block_reasons:
            logger.warning(
                "[매수 차단] %s(%s) — 사유: %s",
                stock_name, stock_code, ",".join(block_reasons),
            )
            return

        try:
            result = await self._order.buy(stock_code=stock_code, quantity=quantity)
            self._today_trade_count += 1
            self._invalidate_balance_cache()
            # 신규/추가 매수 — 다음 사이클에 max(avg, current)로 재시드
            self._peak_prices.pop(stock_code, None)

            logger.info(
                "[매수 체결] %s(%s) %d주, 주문번호=%s",
                stock_name, stock_code, quantity, result.order_no,
            )
            log_trade(f"매수 {stock_name}({stock_code}) {quantity}주 @ {price:,}원")

            self._record_order_to_db(
                stock_code, stock_name, OrderType.BUY, quantity, float(price), result.order_no
            )
            self._record_trade_to_db(
                stock_code, stock_name, TradeType.BUY, quantity, price,
                signal=signal,
            )
            self._record_screening_match_metric(stock_code)

            self._task_queue.enqueue(
                task_type="telegram_notify",
                payload={
                    "notify_type": "buy",
                    "message_data": {
                        "stock_name": stock_name,
                        "stock_code": stock_code,
                        "quantity": quantity,
                        "price": price,
                        "strategy": strategy_name,
                        "reason": signal.reason if signal else "",
                        "confidence": signal.confidence if signal else 0.0,
                    },
                },
                priority=3,
            )

        except Exception:
            logger.exception("[매수 실패] %s(%s)", stock_name, stock_code)

    async def _execute_sell(
        self,
        stock_code: str,
        quantity: int,
        price: int,
        reason: str = "",
        avg_price: float | None = None,
        signal_type: str | None = None,
        stock_name: str = "",
    ) -> None:
        """매도 주문을 실행하고 DB에 기록한다."""
        try:
            result = await self._order.sell(stock_code=stock_code, quantity=quantity)
            self._today_trade_count += 1
            self._invalidate_balance_cache()

            logger.info(
                "[매도 체결] %s(%s) %d주, 사유=%s, 주문번호=%s",
                stock_name, stock_code, quantity, reason, result.order_no,
            )
            log_trade(f"매도 {stock_name}({stock_code}) {quantity}주 @ {price:,}원 ({reason})")

            self._record_order_to_db(
                stock_code, stock_name, OrderType.SELL, quantity, float(price), result.order_no
            )
            self._record_trade_to_db(
                stock_code, stock_name, TradeType.SELL, quantity, price,
                reason=reason, signal_type=signal_type, avg_price=avg_price,
            )
            # 청산 — 고점 추적 종료
            self._peak_prices.pop(stock_code, None)

            self._task_queue.enqueue(
                task_type="telegram_notify",
                payload={
                    "notify_type": "sell",
                    "message_data": {
                        "stock_name": stock_name,
                        "stock_code": stock_code,
                        "quantity": quantity,
                        "price": price,
                        "reason": reason,
                        "avg_price": avg_price or 0.0,
                    },
                },
                priority=3,
            )

        except Exception:
            logger.exception("[매도 실패] %s", stock_code)

    # ── 매매 데이터 DB 적재 ──────────────────────────────────

    _SELL_REASON_MAP: dict[str, SellReason] = {
        "손절": SellReason.STOP_LOSS,
        "익절": SellReason.TAKE_PROFIT,
        "전략매도": SellReason.STRATEGY,
        "트레일링": SellReason.TRAILING_STOP,
        "마감청산": SellReason.MARKET_CLOSE,
    }

    _BUY_REASON_MAP: dict[str, BuyReason] = {
        "골든크로스": BuyReason.GOLDEN_CROSS,
        "과매도": BuyReason.RSI_OVERSOLD,
        "앙상블": BuyReason.ENSEMBLE,
    }

    @staticmethod
    def _detect_buy_reason(signal: Signal) -> BuyReason | None:
        """시그널 reason 문자열에서 BuyReason을 추론한다."""
        reason = signal.reason
        if "골든크로스" in reason:
            return BuyReason.GOLDEN_CROSS
        if "과매도" in reason or "RSI" in reason.upper():
            return BuyReason.RSI_OVERSOLD
        if "앙상블" in reason or "ensemble" in reason.lower():
            return BuyReason.ENSEMBLE
        return None

    def _record_trade_to_db(
        self,
        stock_code: str,
        stock_name: str,
        trade_type: TradeType,
        quantity: int,
        price: int,
        reason: str = "",
        signal: Signal | None = None,
        signal_type: str | None = None,
        avg_price: float | None = None,
    ) -> None:
        """매매 체결 내역을 Worker Queue에 적재한다.

        비즈니스 로직(buy_reason 판별, profit_loss 계산)은 엔진에서 처리하고,
        DB INSERT만 Worker에게 위임한다.
        """
        try:
            buy_reason: BuyReason | None = None
            sell_reason: SellReason | None = None
            profit_loss_pct: float | None = None
            profit_loss_amount: int | None = None

            if trade_type == TradeType.BUY and signal is not None:
                buy_reason = self._detect_buy_reason(signal)
                signal_type = signal.reason.split(" ")[0] if signal.reason else signal_type

            if trade_type == TradeType.SELL:
                sell_reason = self._SELL_REASON_MAP.get(reason)
                if avg_price and avg_price > 0:
                    avg_price = float(avg_price)
                    profit_loss_pct = float(((price - avg_price) / avg_price) * 100)
                    profit_loss_amount = int((price - avg_price) * quantity)
                    self._risk.record_trade_result(profit_loss_amount)

            self._task_queue.enqueue(
                task_type="record_trade",
                payload={
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "trade_type": trade_type.value,
                    "quantity": quantity,
                    "price": price,
                    "total_amount": price * quantity,
                    "traded_at": datetime.now(UTC).isoformat(),
                    "cycle_number": self._cycle_count,
                    "buy_reason": buy_reason.value if buy_reason else None,
                    "sell_reason": sell_reason.value if sell_reason else None,
                    "signal_type": signal_type,
                    "profit_loss_pct": profit_loss_pct,
                    "profit_loss_amount": profit_loss_amount,
                },
                priority=10,
            )
        except Exception:
            logger.exception("매매 큐 적재 실패: %s %s", stock_code, trade_type.value)

    def _record_screening_to_db(
        self,
        ranked: list[object],
        new_candidates: list[str],
    ) -> None:
        """스크리닝 결과를 screening_results 테이블에 배치 기록한다."""
        try:
            with get_session() as session:
                repo = ScreeningResultRepository(session)
                candidate_set = set(new_candidates)
                for rank_idx, item in enumerate(ranked, start=1):
                    repo.record_screening(
                        stock_code=item.stock_code,
                        stock_name=item.stock_name,
                        screening_rank=rank_idx,
                        volume=item.volume,
                        price_change_pct=item.change_rate,
                        screened_at=datetime.now(UTC),
                        cycle_number=self._cycle_count,
                        converted_to_trade=item.stock_code in candidate_set,
                    )
        except Exception:
            logger.exception("스크리닝 DB 적재 실패")

    def _record_signal_skip(
        self,
        stock_code: str,
        stock_name: str,
        signal: Signal,
        skip_reason: str,
    ) -> None:
        """HOLD 등 DB 미기록 시그널의 skip 사유를 메트릭으로 기록한다."""
        logger.debug(
            "[%s %s] 시그널 skip: reason=%s, type=%s, conf=%.2f, meta=%s",
            stock_code, stock_name, skip_reason,
            signal.signal_type.value, signal.confidence,
            json.dumps(signal.meta, ensure_ascii=False) if signal.meta else "{}",
        )
        self._record_metric("SIGNAL_SKIP", {
            "stock_code": stock_code,
            "skip_reason": skip_reason,
            "signal_type": signal.signal_type.value,
            "confidence": round(signal.confidence, 4),
            "vote_meta": signal.meta if signal.meta else None,
        })

    def _record_signal_to_db(
        self,
        stock_code: str,
        stock_name: str,
        signal: Signal,
        action_taken: bool = False,
        skip_reason: str | None = None,
    ) -> None:
        """전략 시그널을 signals 테이블에 기록한다. BUY/SELL만 기록한다."""
        if signal.signal_type == SignalType.HOLD:
            return
        # 저신뢰도 + 비매매전환 시그널은 DB 저장 스킵 (노이즈 축소)
        if (
            not action_taken
            and signal.confidence < settings.strategy.min_confidence
        ):
            return
        try:
            # 시그널 reason에서 시그널 타입 추출
            signal_type_str = "UNKNOWN"
            if "골든크로스" in signal.reason:
                signal_type_str = "GOLDEN_CROSS"
            elif "데드크로스" in signal.reason:
                signal_type_str = "DEAD_CROSS"
            elif (
                "RSI" in signal.reason.upper()
                or "과매도" in signal.reason
                or "과매수" in signal.reason
            ):
                signal_type_str = "RSI_SIGNAL"
            elif "MACD" in signal.reason.upper():
                signal_type_str = "MACD_SIGNAL"
            elif "볼린저" in signal.reason:
                signal_type_str = "BOLLINGER_SIGNAL"
            elif "앙상블" in signal.reason or "ensemble" in signal.reason.lower():
                signal_type_str = "ENSEMBLE"
            else:
                signal_type_str = signal.reason[:50] if signal.reason else "UNKNOWN"

            # numpy float → Python float 변환 (PostgreSQL JSONB 호환)
            conf = float(signal.confidence)
            target = (
                float(signal.target_price) if signal.target_price is not None else None
            )

            self._task_queue.enqueue(
                task_type="record_signal",
                payload={
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "signal_type": signal_type_str,
                    "detected_at": datetime.now(UTC).isoformat(),
                    "signal_value": {
                        "confidence": conf,
                        "target_price": target,
                        "reason": signal.reason,
                        **({"skip_reason": skip_reason} if skip_reason else {}),
                    },
                    "confidence": conf,
                    "action_taken": action_taken,
                },
                priority=5,
            )
        except Exception:
            logger.exception("시그널 큐 적재 실패: %s", stock_code)

    def _record_metric(self, metric_type: str, detail: dict | None = None) -> None:
        """시스템 메트릭을 Worker Queue에 적재한다."""
        try:
            self._task_queue.enqueue(
                task_type="record_metric",
                payload={
                    "metric_type": metric_type,
                    "detail": detail,
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
                priority=3,
            )
        except Exception:
            logger.exception("메트릭 큐 적재 실패: %s", metric_type)

    def _record_buy_reject(
        self,
        *,
        stock_code: str,
        reason: str,
        confidence: float | None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """매수 게이트 거절 사유를 ``BUY_REJECT`` 메트릭으로 기록한다.

        proposal 2026-05-18: 시그널→매수 전환 0% anomaly 분해용 진단 메트릭.
        시그널이 매수 단계까지 도달했으나 게이트(잔고/포지션/리스크/신뢰도)에
        막혀 차단된 경우 1건씩 기록한다.

        ``reason`` 코드는 BRIDGE 제안서의 분류를 따른다:
        ``LOW_CONFIDENCE``, ``POSITION_RATIO``, ``INSUFFICIENT_CASH``,
        ``DAILY_TRADE_LIMIT``, ``MARKET_CLOSE_GUARD``,
        ``MAX_CONSECUTIVE_LOSSES``, ``MAX_DAILY_DRAWDOWN``.
        기록 실패는 매매 본 흐름에 영향이 없도록 swallow 한다.

        Args:
            stock_code: 종목코드.
            reason: 거절 사유 코드.
            confidence: 시그널 신뢰도 (없으면 ``None``).
            context: 추가 메타데이터(예: ``{"balance": 0}``).
        """
        try:
            detail: dict[str, Any] = {
                "cycle": self._cycle_count,
                "stock_code": stock_code,
                "reason": reason,
                "confidence": (
                    round(float(confidence), 4) if confidence is not None else None
                ),
            }
            if context:
                detail["context"] = context
            self._record_metric("BUY_REJECT", detail)
        except Exception:
            logger.exception(
                "BUY_REJECT 메트릭 기록 실패: %s reason=%s",
                stock_code,
                reason,
            )

    def _check_market_action_block(self, stock_code: str) -> list[str]:
        """매수 전 시장조치 차단 lookup.

        KIS 종목마스터 일일 sync(`market_actions` 테이블) 결과를 조회해 거래정지/
        관리종목/정리매매/시장경고/경고예고/불성실공시 중 하나라도 ON이면 차단
        사유 리스트를 반환한다. 미등록 종목은 빈 리스트(통과 — 안전 기본값).
        DB 조회 실패는 매매를 막지 않도록 swallow(빈 리스트 반환).
        """
        try:
            with get_session() as session:
                repo = MarketActionRepository(session)
                ma = repo.get(stock_code)
                if ma is None:
                    return []
                return ma.block_reasons
        except Exception:
            logger.exception("market_action 차단 lookup 실패: %s", stock_code)
            return []

    def _record_screening_match_metric(self, stock_code: str) -> None:
        """신규 BUY 직후 동일 stock_code의 screening_results 매칭 여부를 메트릭으로 기록한다.

        proposal 2026-05-15: 룰 B(스크리닝→매매 전환율) 진단용. 당일 KST 범위의
        screening_results에 해당 종목이 존재하면 SCREENING_HIT, 없으면
        SCREENING_MISS로 기록한다. 매수 본 흐름과 분리(예외 시 swallow).
        """
        try:
            today = date.today()
            with get_session() as session:
                repo = ScreeningResultRepository(session)
                results = repo.get_by_date(today)
                matched = any(r.stock_code == stock_code for r in results)
            self._record_metric(
                "SCREENING_HIT" if matched else "SCREENING_MISS",
                {
                    "cycle": self._cycle_count,
                    "stock_code": stock_code,
                    "matched": matched,
                },
            )
        except Exception:
            logger.exception("SCREENING_HIT/MISS 메트릭 기록 실패: %s", stock_code)

    # truncate 임계값: detail.targets 배열이 길어져 JSON이 과도하게 커지는
    # 것을 방지한다. 50개 초과 시 앞 50개만 남기고 truncated=True 플래그를 기록한다.
    _EVAL_TARGETS_MAX_CODES: int = 50

    def _record_eval_targets(
        self,
        *,
        cycle_number: int,
        targets: list[str],
        counts: dict[str, int],
    ) -> None:
        """이번 사이클의 평가 대상 종목과 원천별 카운트를 메트릭으로 기록한다.

        스크리닝→전략 평가 파이프라인의 가시성을 확보하기 위한 observability
        레코드(proposal 2026-04-16). ``counts``는 ``{screening, watchlist,
        positions}`` 3개 키를 가진다. ``targets`` 리스트가 길어져 JSON이
        과도하게 커지지 않도록 앞 ``_EVAL_TARGETS_MAX_CODES``개만 기록하고
        잘린 경우 ``truncated=True`` 플래그를 함께 남긴다.
        """
        truncated = len(targets) > self._EVAL_TARGETS_MAX_CODES
        recorded_targets = targets[: self._EVAL_TARGETS_MAX_CODES]
        self._record_metric(
            "EVAL_TARGETS",
            {
                "cycle": cycle_number,
                "counts": {
                    "screening": int(counts.get("screening", 0)),
                    "watchlist": int(counts.get("watchlist", 0)),
                    "positions": int(counts.get("positions", 0)),
                },
                "total_targets": len(targets),
                "targets": recorded_targets,
                "truncated": truncated,
            },
        )

    # ── Worker Queue enqueue 메서드 ──────────────────────────

    def _enqueue_calendar_event(
        self,
        *,
        trades: list[Any],
        realized_profit_loss: int,
        realized_rate: float,
    ) -> None:
        """캘린더 이벤트 등록을 Worker Queue에 적재한다.

        캘린더 이벤트의 "총 손익"·"수익률"은 종목별 상세 합계와 일치해야
        하므로 평가손익(``balance.total_profit_loss``)이 아닌 DB trades
        테이블 기반 실현손익/실현수익률을 전달한다.
        """
        today = date.today()
        details_json = json.dumps(
            self._group_trades_for_calendar(trades),
            ensure_ascii=False,
        )
        self._task_queue.enqueue(
            task_type="calendar_event",
            payload={
                "trade_date": today.isoformat(),
                "total_profit_loss": int(realized_profit_loss),
                "profit_rate": float(realized_rate),
                "execution_count": len(trades),
                "details_json": details_json,
            },
            priority=1,
            idempotency_key=f"calendar_{today.isoformat()}",
        )

    def _enqueue_telegram_daily_summary(
        self,
        *,
        balance: Balance,
        buy_count: int,
        sell_count: int,
        realized_profit_loss: int,
        realized_rate: float,
    ) -> None:
        """Telegram 일일 결산 알림을 Worker Queue에 적재한다.

        Telegram 메시지는 "실현손익" 라벨을 사용하므로, KIS API의
        평가손익(balance.total_profit_loss, total_profit_rate)이 아닌 DB trades
        테이블에서 집계한 실현손익/수익률을 전달한다.
        """
        today_str = date.today().isoformat()
        _ = balance  # 현재 payload에 balance 필드는 포함하지 않음 (호환 유지)
        self._task_queue.enqueue(
            task_type="telegram_notify",
            payload={
                "notify_type": "daily_summary",
                "message_data": {
                    "trade_date": today_str,
                    "count": buy_count + sell_count,
                    "profit_loss": int(realized_profit_loss),
                    "rate": float(realized_rate),
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                },
            },
            priority=3,
            idempotency_key=f"telegram_summary_{today_str}",
        )

    def _enqueue_daily_summary(self, today_str: str) -> None:
        """일일 요약 집계를 Worker Queue에 적재한다."""
        self._task_queue.enqueue(
            task_type="daily_summary",
            payload={"report_date": today_str},
            priority=1,
            idempotency_key=f"daily_summary_{today_str}",
        )

    def _enqueue_sync_portfolio(self, balance: Balance) -> None:
        """포트폴리오 동기화를 Worker Queue에 적재한다."""
        holdings = []
        for h in balance.holdings:
            holdings.append({
                "stock_code": h.stock_code,
                "stock_name": getattr(h, "stock_name", h.stock_code),
                "quantity": h.quantity,
                "avg_price": float(h.avg_price),
                "current_price": float(h.current_price),
                "peak_price": self._peak_prices.get(h.stock_code),
            })
        self._task_queue.enqueue(
            task_type="sync_portfolio",
            payload={"holdings": holdings},
            priority=1,
            idempotency_key=f"sync_portfolio_{date.today().isoformat()}",
        )

    def _enqueue_daily_performance(
        self, balance: Balance, trades: list[Any]
    ) -> None:
        """일일 성과 저장을 Worker Queue에 적재한다.

        ``trades``는 DB ``trades`` 테이블의 오늘 체결 레코드 목록이다. KIS
        모의투자 API 결과가 비어 있어도 DB 기반으로 정확한 체결 건수/내역을
        기록하기 위해 Trade 객체를 받는다.
        """
        details = json.dumps(
            [
                {
                    "stock_code": t.stock_code,
                    "stock_name": t.stock_name,
                    "side": (
                        "매수" if t.trade_type == TradeType.BUY else "매도"
                    ),
                    "quantity": t.quantity,
                    "price": t.price,
                    "profit_loss_amount": t.profit_loss_amount,
                }
                for t in trades
            ],
            ensure_ascii=False,
        )
        # DB daily_performances.profit_rate 컬럼은 비율(ratio) 단위로 저장한다
        # (예: 2.5% → 0.025). KIS API는 퍼센트 단위(ASST_ICDC_ERNG_RT)로
        # 값을 주므로 100으로 나눠 통일한다.
        self._task_queue.enqueue(
            task_type="daily_performance",
            payload={
                "trade_date": date.today().isoformat(),
                "total_profit_loss": float(balance.total_profit_loss),
                "profit_rate": float(balance.total_profit_rate) / 100.0,
                "execution_count": len(trades),
                "details": details,
            },
            priority=5,
            idempotency_key=f"daily_perf_{date.today().isoformat()}",
        )

    # ── 레거시 직접 호출 (Worker 미가동 시 폴백) ─────────

    def _upsert_daily_summary(self) -> None:
        """일일 요약을 집계하여 daily_summary 테이블에 UPSERT한다."""
        try:
            with get_session() as session:
                repo = DailySummaryRepository(session)
                repo.upsert_daily_summary(date.today())
        except Exception:
            logger.exception("일일 요약 DB 적재 실패")

    # ── DB 연동 (기존) ─────────────────────────────────────

    def _create_calendar_event(self, balance: object, executions: list[object]) -> None:
        """일일 매매 결과를 Google Calendar에 등록한다.

        체결 건수·종목 상세는 DB Trade 테이블을 기준으로 집계한다.
        KIS 모의투자 환경의 ``inquire-daily-ccld`` API가 빈 결과를 반환해
        ``executions`` 인자를 신뢰할 수 없어 DB로 대체한다.
        수익률은 ``balance.total_profit_rate`` (KIS API의 ``ASST_ICDC_ERNG_RT``,
        전일 대비 자산증감수익률)를 그대로 사용한다.
        """
        try:
            today = date.today()
            trades = self._load_today_trades(today)

            auth = GoogleCalendarAuth()
            service = auth.get_service()
            creator = CalendarEventCreator(service=service)

            details_json = json.dumps(
                self._group_trades_for_calendar(trades),
                ensure_ascii=False,
            )

            event_id = creator.create_daily_report_event(
                trade_date=today,
                total_profit_loss=int(balance.total_profit_loss),
                profit_rate=float(balance.total_profit_rate),
                execution_count=len(trades),
                details_json=details_json,
            )
            logger.info(
                "Google Calendar 이벤트 등록 완료: %s (DB 체결=%d건)",
                event_id,
                len(trades),
            )

        except Exception:
            logger.exception("Google Calendar 이벤트 등록 실패 (매매 결과에는 영향 없음)")

    @staticmethod
    def _load_today_trades(today: date) -> list[Any]:
        """오늘 체결된 매매 내역을 DB에서 조회한다."""
        try:
            with get_session() as session:
                repo = TradeRepository(session)
                return list(repo.get_trades_by_date(today))
        except Exception:
            logger.exception("DB 체결 내역 조회 실패 — 캘린더에는 빈 내역으로 기록")
            return []

    @staticmethod
    def _group_trades_for_calendar(trades: list[Any]) -> list[dict[str, Any]]:
        """Trade 목록을 종목별로 집계해 캘린더 상세 형식으로 변환한다.

        동일 종목을 여러 번 매수/매도한 경우 수량·금액을 합산하고,
        매도 손익은 ``profit_loss_amount`` 합, 수익률은 금액 가중 평균으로 계산한다.
        """
        grouped: dict[str, dict[str, Any]] = {}

        for t in trades:
            code = t.stock_code
            entry = grouped.setdefault(
                code,
                {
                    "name": t.stock_name or code,
                    "code": code,
                    "buy_qty": 0,
                    "buy_amount": 0,
                    "sell_qty": 0,
                    "sell_amount": 0,
                    "profit_loss": 0,
                    "_pl_base_amount": 0,  # 수익률 가중평균 계산용
                    "_pl_weighted_pct": 0.0,
                },
            )
            if t.stock_name and entry["name"] == code:
                entry["name"] = t.stock_name

            if t.trade_type == TradeType.BUY:
                entry["buy_qty"] += t.quantity
                entry["buy_amount"] += t.total_amount
            else:  # SELL
                entry["sell_qty"] += t.quantity
                entry["sell_amount"] += t.total_amount
                pl_amt = t.profit_loss_amount or 0
                entry["profit_loss"] += pl_amt
                if t.profit_loss_pct is not None and t.total_amount > 0:
                    entry["_pl_base_amount"] += t.total_amount
                    entry["_pl_weighted_pct"] += float(t.profit_loss_pct) * t.total_amount

        result: list[dict[str, Any]] = []
        for code, e in grouped.items():
            buy_price = e["buy_amount"] // e["buy_qty"] if e["buy_qty"] > 0 else 0
            sell_price = e["sell_amount"] // e["sell_qty"] if e["sell_qty"] > 0 else 0
            if e["_pl_base_amount"] > 0:
                profit_rate = e["_pl_weighted_pct"] / e["_pl_base_amount"]
            else:
                profit_rate = 0.0
            result.append(
                {
                    "name": e["name"],
                    "code": code,
                    "buy_price": buy_price,
                    "buy_qty": e["buy_qty"],
                    "sell_price": sell_price,
                    "sell_qty": e["sell_qty"],
                    "profit_loss": e["profit_loss"],
                    "profit_rate": profit_rate,
                }
            )
        return result

    def _find_holding_from_balance(
        self, balance: Balance, stock_code: str
    ) -> dict[str, float] | None:
        """잔고에서 보유 정보를 직접 조회한다 (DB 거치지 않음)."""
        for h in balance.holdings:
            if h.stock_code == stock_code and h.quantity > 0:
                return {
                    "quantity": float(h.quantity),
                    "avg_price": h.avg_price,
                }
        return None

    async def _prefetch_stock_names(self, codes: list[str]) -> None:
        """관심종목의 이름을 사전에 DB에 등록한다.

        stocks 테이블에 없거나 이름이 코드와 동일한 종목은
        현재가 API를 호출하여 이름을 가져온 뒤 등록/갱신한다.
        """
        try:
            with get_session() as session:
                stock_repo = StockRepository(session)
                missing_codes = []
                for code in codes:
                    stock = stock_repo.get_by_code(code)
                    if stock is None or not stock.name or stock.name == code:
                        missing_codes.append(code)

            if not missing_codes:
                return

            logger.info("종목명 사전 등록: %d종목 조회 중", len(missing_codes))
            for code in missing_codes:
                try:
                    current = await self._quote.get_current_price(code)
                    if current.stock_name and current.stock_name != code:
                        with get_session() as session:
                            stock_repo = StockRepository(session)
                            stock = stock_repo.get_by_code(code)
                            if stock is None:
                                stock_repo.create(code, current.stock_name, "UNKNOWN")
                            elif stock.name != current.stock_name:
                                stock_repo.update_name(code, current.stock_name)
                except Exception:
                    logger.debug("종목명 조회 실패: %s", code)

        except Exception:
            logger.exception("종목명 사전 등록 실패 (매매에 영향 없음)")

    def _upsert_stock_names(self, name_map: dict[str, str]) -> None:
        """주어진 (코드, 이름) 쌍을 stocks 테이블에 upsert한다.

        스크리닝 결과로 발굴된 종목의 이름을 사전 등록하여,
        ``_process_stock``에서 현재가 API의 ``HTS_KOR_ISNM`` 응답이
        비어있을 때 폴백으로 사용할 수 있도록 한다.

        Args:
            name_map: {종목코드: 종목명} 매핑
        """
        if not name_map:
            return
        try:
            registered = 0
            updated = 0
            with get_session() as session:
                stock_repo = StockRepository(session)
                for code, name in name_map.items():
                    if not name or name == code:
                        continue
                    stock = stock_repo.get_by_code(code)
                    if stock is None:
                        stock_repo.create(code, name, "UNKNOWN")
                        registered += 1
                    elif stock.name == stock.code or not stock.name:
                        stock_repo.update_name(code, name)
                        updated += 1
            if registered or updated:
                logger.info(
                    "스크리닝 종목명 stocks 테이블 반영: 신규 %d / 보정 %d",
                    registered, updated,
                )
        except Exception:
            logger.exception("스크리닝 종목명 upsert 실패 (매매에 영향 없음)")

    def _resolve_stock_name(self, stock_code: str) -> str:
        """DB에서 종목명을 조회한다. 코드와 동일하거나 없으면 빈 문자열 반환."""
        try:
            with get_session() as session:
                stock_repo = StockRepository(session)
                stock = stock_repo.get_by_code(stock_code)
                if stock is not None and stock.name and stock.name != stock.code:
                    return stock.name
        except Exception:
            pass
        return ""

    def _update_stock_name_if_needed(self, stock_code: str, stock_name: str) -> None:
        """DB의 종목명이 코드와 동일하거나 빈 문자열일 경우 실제 이름으로 갱신한다."""
        try:
            with get_session() as session:
                stock_repo = StockRepository(session)
                stock = stock_repo.get_by_code(stock_code)
                if stock is not None and (
                    stock.name == stock.code or not stock.name
                ):
                    stock_repo.update_name(stock_code, stock_name)
        except Exception:
            logger.debug("종목명 갱신 실패: %s", stock_code)

    def _record_order_to_db(
        self,
        stock_code: str,
        stock_name: str,
        order_type: OrderType,
        quantity: int,
        price: float,
        order_no: str,
    ) -> None:
        """주문 내역을 DB에 기록한다."""
        try:
            with get_session() as session:
                stock_repo = StockRepository(session)
                order_repo = OrderRepository(session)

                stock = stock_repo.get_by_code(stock_code)
                if stock is None:
                    stock = stock_repo.create(stock_code, stock_name or stock_code, "KOSPI")

                order = order_repo.create(stock.id, order_type, quantity, price)
                order_repo.update_status(order.id, OrderStatus.SUBMITTED, order_no)

        except Exception:
            logger.exception("주문 DB 기록 실패: %s", stock_code)

    async def _seed_watchlist_from_env(self) -> None:
        """최초 실행 시 .env의 관심종목을 DB에 시드하고, 종목명을 보정한다."""
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                stock_repo = StockRepository(session)
                for code in settings.trading.watchlist_codes:
                    repo.add(code)

                    # 종목명이 코드와 동일하면 API로 실제 이름을 조회하여 갱신
                    stock = stock_repo.get_by_code(code)
                    if stock is not None and stock.name == stock.code:
                        try:
                            price_info = await self._quote.get_current_price(code)
                            if price_info.stock_name:
                                stock_repo.update_name(code, price_info.stock_name)
                        except Exception:
                            logger.debug("종목명 조회 실패 (시드): %s", code)
        except Exception:
            logger.exception("관심종목 시드 실패")

    def _save_daily_performance(self, balance: object, executions: list[object]) -> None:
        """일일 성과를 DB에 저장한다."""
        try:
            with get_session() as session:
                perf_repo = DailyPerformanceRepository(session)
                today = date.today()

                existing = perf_repo.get_by_date(today)
                if existing is not None:
                    logger.info("금일 성과 이미 존재, 스킵")
                    return

                details = json.dumps(
                    [
                        {
                            "stock_code": e.stock_code,
                            "stock_name": e.stock_name,
                            "side": e.side,
                            "quantity": e.quantity,
                            "price": e.price,
                            "amount": e.amount,
                        }
                        for e in executions
                    ],
                    ensure_ascii=False,
                )

                perf_repo.create(
                    perf_date=today,
                    total_pl=float(balance.total_profit_loss),
                    rate=float(balance.total_profit_rate) / 100.0,
                    count=len(executions),
                    details=details,
                )
                logger.info("일일 성과 저장 완료: %s", today)

        except Exception:
            logger.exception("일일 성과 저장 실패")

    def _sync_portfolio(self, balance: object) -> None:
        """KIS 잔고를 기반으로 DB 포트폴리오를 동기화한다."""
        try:
            with get_session() as session:
                stock_repo = StockRepository(session)
                portfolio_repo = PortfolioRepository(session)

                for h in balance.holdings:
                    stock = stock_repo.get_by_code(h.stock_code)
                    if stock is None:
                        stock = stock_repo.create(h.stock_code, h.stock_name, "KOSPI")

                    portfolio_repo.upsert(
                        stock_id=stock.id,
                        quantity=h.quantity,
                        avg_price=h.avg_price,
                        current_price=float(h.current_price),
                    )

                logger.info("포트폴리오 동기화 완료 (%d종목)", len(balance.holdings))

        except Exception:
            logger.exception("포트폴리오 동기화 실패")
