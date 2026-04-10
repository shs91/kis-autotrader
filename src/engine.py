"""매매 엔진 모듈 — 시세조회·전략분석·리스크체크·주문실행·DB저장을 통합한다."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import pandas as pd

from src.api.account import AccountAPI, Balance
from src.api.client import KISClient
from src.api.order import OrderAPI
from src.api.quote import QuoteAPI
from src.calendar.event import CalendarEventCreator
from src.calendar.google_auth import GoogleCalendarAuth
from src.config import settings
from src.db.event_logger import log_trade, log_warning
from src.db.models import BuyReason, OrderStatus, OrderType, SellReason, TradeType
from src.db.repository import (
    DailyPerformanceRepository,
    DailySummaryRepository,
    OrderRepository,
    PortfolioRepository,
    ScreeningResultRepository,
    SignalRepository,
    StockRepository,
    SystemMetricRepository,
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

        # 관심종목: 직접 지정 시 고정, 미지정 시 DB에서 매 사이클 조회
        self._fixed_watchlist: list[str] | None = watchlist
        # 스크리닝으로 발굴된 동적 종목
        self._screened_codes: set[str] = set()

        self._today_trade_count = 0
        self._cycle_count = 0
        self._daily_limit_reached = False

        # 일봉 캐시: {종목코드: (날짜, DataFrame)}
        self._daily_cache: dict[str, tuple[str, pd.DataFrame]] = {}
        # 잔고 캐시: (조회시각, Balance)
        self._balance_cache: tuple[float, Balance] | None = None

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
        if len(daily_prices) < 21:
            logger.info("[%s] 일봉 데이터 부족 (%d건), 스킵", stock_code, len(daily_prices))
            return None

        df = pd.DataFrame(
            [
                {"close": item.close_price, "date": item.date}
                for item in reversed(daily_prices)
            ]
        )

        self._daily_cache[stock_code] = (today_str, df)
        return df

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

            # 관심종목 일봉 사전 캐싱
            watchlist_codes = self._get_watchlist_codes()
            for code in watchlist_codes:
                await self._get_daily_df(code)
            logger.info("관심종목 일봉 캐싱 완료 (%d종목)", len(self._daily_cache))

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
            targets = self._build_monitor_targets(held_codes)
            logger.info(
                "모니터링 대상: %d종목 (보유 %d + 관심 %d + 발굴 %d)",
                len(targets),
                len(held_codes),
                len(self._get_watchlist_codes()),
                len(self._screened_codes),
            )

            for stock_code in targets:
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
            executions = await self._account.get_executions()

            logger.info(
                "당일 체결 건수: %d, 총 평가손익: %s원 (수익률: %.2f%%)",
                len(executions),
                f"{balance.total_profit_loss:,}",
                balance.total_profit_rate,
            )

            self._save_daily_performance(balance, executions)
            self._sync_portfolio(balance)
            self._upsert_daily_summary()

            # Google Calendar 이벤트 등록
            self._create_calendar_event(balance, executions)

            # Telegram 일일 결산 알림
            await self._notifier.notify_daily_summary(
                trade_date=date.today().isoformat(),
                count=len(executions),
                profit_loss=int(balance.total_profit_loss),
                rate=float(balance.total_profit_rate),
            )

            buy_count = sum(1 for e in executions if e.side == "매수")
            sell_count = sum(1 for e in executions if e.side == "매도")

            self._client._limiter.log_daily_count()
            logger.info(
                "[일일결산] 사이클=%d, 체결=%d건 (매수 %d / 매도 %d), "
                "발굴=%d종목, 손익=%s원 (%.2f%%)",
                self._cycle_count,
                len(executions),
                buy_count,
                sell_count,
                len(self._screened_codes),
                f"{balance.total_profit_loss:,}",
                balance.total_profit_rate,
            )

        except Exception:
            logger.exception("장 마감 후 작업 중 에러 발생")

        logger.info("=== 장 마감 후 작업 완료 ===")

    # ── 종목 스크리닝 ─────────────────────────────────────

    async def _screen_stocks(self) -> None:
        """거래량 상위 종목을 필터링·스코어링하여 매수 후보를 발굴한다."""
        scfg = self._screener.config
        if len(self._screened_codes) >= scfg.max_screened:
            logger.info("스크리닝 발굴 종목 상한 도달 (%d종목), 스킵", len(self._screened_codes))
            return

        logger.info("=== 종목 스크리닝 시작 ===")

        try:
            ranked = await self._quote.get_volume_rank(top_n=scfg.top_n)
        except Exception:
            logger.exception("거래량 순위 조회 실패")
            return

        # 1단계: 사전 필터 (가격/시총/등락률/거래량)
        watchlist_set = set(self._get_watchlist_codes())
        exclude_codes = watchlist_set | self._screened_codes
        filtered = self._screener.filter_candidates(ranked, exclude_codes)

        # 2단계: 전략 분석 + 스코어링
        from src.strategy.screener import ScoredCandidate

        scored: list[ScoredCandidate] = []
        for rank_idx, item in enumerate(filtered):
            try:
                df = await self._get_daily_df(item.stock_code)
                if df is None:
                    continue

                strategy = self._selector.get_strategy(item.stock_code)
                signal = strategy.analyze(df)

                candidate = self._screener.score_candidate(
                    item, rank_idx, len(filtered), signal,
                )
                scored.append(candidate)

            except Exception:
                logger.debug("스크리닝 분석 실패: %s", item.stock_code)

        # 3단계: 종합 점수 정렬 + 최소 점수 컷
        top_candidates = self._screener.rank_candidates(scored)

        # 4단계: 슬롯 수만큼 발굴
        remaining_slots = scfg.max_screened - len(self._screened_codes)
        new_candidates: list[str] = []

        for candidate in top_candidates[:remaining_slots]:
            new_candidates.append(candidate.stock_code)
            logger.info(
                "[스크리닝 발굴] %s(%s) 종합=%.2f "
                "(거래량=%.2f, 등락률=%.2f, 전략=%.2f) — %s",
                candidate.stock_name,
                candidate.stock_code,
                candidate.total_score,
                candidate.volume_rank_score,
                candidate.change_rate_score,
                candidate.strategy_score,
                candidate.signal.reason,
            )

        self._screened_codes.update(new_candidates)
        self._record_screening_to_db(ranked, new_candidates)
        logger.info(
            "=== 종목 스크리닝 완료: 신규 %d종목 발굴 (누적 %d/%d종목) ===",
            len(new_candidates),
            len(self._screened_codes),
            scfg.max_screened,
        )

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
            return

        # 2. 현재가 조회 (실시간)
        current = await self._quote.get_current_price(stock_code)

        # 2-1. 종목명이 코드와 동일하면 API 응답의 실제 이름으로 갱신
        if current.stock_name and current.stock_name != stock_code:
            self._update_stock_name_if_needed(stock_code, current.stock_name)

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

        # 3-1. 시그널 DB 기록 (BUY/SELL만, action_taken은 아래서 결정)
        will_act = False

        # 4. 보유 종목 처리
        if is_held and holding_info is not None:
            will_act = signal.signal_type == SignalType.SELL and signal.confidence >= 0.1
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=will_act,
            )
            await self._process_held_stock(
                stock_code, current.current_price, holding_info, signal,
                stock_name=current.stock_name,
            )
            return

        # 5. 미보유 종목 — 매수 시그널 처리
        if signal.signal_type == SignalType.BUY:
            if not self._risk.validate_order(signal, float(deposit), 0):
                self._record_signal_to_db(
                    stock_code, current.stock_name, signal, action_taken=False,
                )
                return
            quantity = self._risk.calculate_position_size(
                float(deposit), float(current.current_price)
            )
            if quantity <= 0:
                logger.info("[%s] 매수 가능 수량 0, 스킵", stock_code)
                self._record_signal_to_db(
                    stock_code, current.stock_name, signal, action_taken=False,
                )
                return
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=True,
            )
            await self._execute_buy(
                stock_code, current.stock_name, quantity, current.current_price, signal=signal,
            )
        elif signal.signal_type != SignalType.HOLD:
            self._record_signal_to_db(
                stock_code, current.stock_name, signal, action_taken=False,
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

        우선순위: 손절 > 익절 > 전략 매도(데드크로스)

        Args:
            stock_code: 종목코드
            current_price: 현재가
            holding: 보유 정보
            signal: 전략 분석 시그널
            stock_name: 종목명
        """
        avg_price = holding["avg_price"]
        quantity = int(holding["quantity"])

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
        signal: Signal | None = None,
    ) -> None:
        """매수 주문을 실행하고 DB에 기록한다."""
        try:
            result = await self._order.buy(stock_code=stock_code, quantity=quantity)
            self._today_trade_count += 1
            self._invalidate_balance_cache()

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

            await self._notifier.notify_buy(stock_name, stock_code, quantity, price)

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

            await self._notifier.notify_sell(stock_name, stock_code, quantity, price, reason)

        except Exception:
            logger.exception("[매도 실패] %s", stock_code)

    # ── 매매 데이터 DB 적재 ──────────────────────────────────

    _SELL_REASON_MAP: dict[str, SellReason] = {
        "손절": SellReason.STOP_LOSS,
        "익절": SellReason.TAKE_PROFIT,
        "전략매도": SellReason.STRATEGY,
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
        """매매 체결 내역을 trades 테이블에 기록한다. 실패 시 로그만 남긴다."""
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

            with get_session() as session:
                repo = TradeRepository(session)
                repo.record_trade(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    trade_type=trade_type,
                    quantity=quantity,
                    price=price,
                    total_amount=price * quantity,
                    traded_at=datetime.now(),
                    cycle_number=self._cycle_count,
                    buy_reason=buy_reason,
                    sell_reason=sell_reason,
                    signal_type=signal_type,
                    profit_loss_pct=profit_loss_pct,
                    profit_loss_amount=profit_loss_amount,
                )
        except Exception:
            logger.exception("매매 DB 적재 실패: %s %s", stock_code, trade_type.value)

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
                        screened_at=datetime.now(),
                        cycle_number=self._cycle_count,
                        converted_to_trade=item.stock_code in candidate_set,
                    )
        except Exception:
            logger.exception("스크리닝 DB 적재 실패")

    def _record_signal_to_db(
        self,
        stock_code: str,
        stock_name: str,
        signal: Signal,
        action_taken: bool = False,
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
            elif "RSI" in signal.reason.upper() or "과매도" in signal.reason or "과매수" in signal.reason:
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
            target = float(signal.target_price) if signal.target_price is not None else None

            with get_session() as session:
                repo = SignalRepository(session)
                repo.record_signal(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    signal_type=signal_type_str,
                    detected_at=datetime.now(),
                    signal_value={
                        "confidence": conf,
                        "target_price": target,
                        "reason": signal.reason,
                    },
                    confidence=conf,
                    action_taken=action_taken,
                )
        except Exception:
            logger.exception("시그널 DB 적재 실패: %s", stock_code)

    def _record_metric(self, metric_type: str, detail: dict | None = None) -> None:
        """시스템 메트릭을 system_metrics 테이블에 기록한다."""
        try:
            with get_session() as session:
                repo = SystemMetricRepository(session)
                repo.record_metric(
                    metric_type=metric_type,
                    detail=detail,
                    recorded_at=datetime.now(),
                )
        except Exception:
            logger.exception("시스템 메트릭 DB 적재 실패: %s", metric_type)

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

    def _update_stock_name_if_needed(self, stock_code: str, stock_name: str) -> None:
        """DB의 종목명이 코드와 동일할 경우 실제 이름으로 갱신한다."""
        try:
            with get_session() as session:
                stock_repo = StockRepository(session)
                stock = stock_repo.get_by_code(stock_code)
                if stock is not None and stock.name == stock.code:
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
