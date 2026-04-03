"""매매 엔진 모듈 — 시세조회·전략분석·리스크체크·주문실행·DB저장을 통합한다."""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd

from src.api.account import AccountAPI, Balance
from src.api.client import KISClient
from src.api.order import OrderAPI
from src.api.quote import DailyPriceItem, QuoteAPI
from src.config import settings
from src.calendar.event import CalendarEventCreator
from src.calendar.google_auth import GoogleCalendarAuth
from src.utils.exceptions import DailyLimitExceededError
from src.db.models import OrderStatus, OrderType
from src.db.repository import (
    DailyPerformanceRepository,
    OrderRepository,
    PortfolioRepository,
    StockRepository,
)
from src.db.session import get_session
from src.strategy.base import BaseStrategy, Signal, SignalType
from src.strategy.moving_average import MovingAverageStrategy
from src.strategy.risk import RiskManager
from src.db.event_logger import log_error, log_trade, log_warning
from src.notify.telegram import TelegramNotifier
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 스크리닝 상수
SCREENING_TOP_N: int = 20  # 거래량 상위 N종목 스캔
SCREENING_INTERVAL_CYCLES: int = 60  # N사이클마다 스크리닝 (약 5분 간격)
MAX_SCREENED_STOCKS: int = 15  # 스크리닝 발굴 종목 상한 (API 호출량 제어)

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
    ) -> None:
        """매매 엔진을 초기화한다.

        Args:
            watchlist: 고정 관심종목코드 목록 (None이면 설정에서 로드)
            strategy: 매매 전략 (None이면 이동평균 교차 전략)
        """
        self._client = KISClient()
        self._quote = QuoteAPI(client=self._client)
        self._order = OrderAPI(client=self._client)
        self._account = AccountAPI(client=self._client)
        self._strategy = strategy or MovingAverageStrategy()
        self._risk = RiskManager()
        self._notifier = TelegramNotifier()

        # 고정 관심종목 (설정 기반)
        self._fixed_watchlist = watchlist or settings.trading.watchlist_codes
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
            "매매 엔진 초기화: 전략=%s, 고정 관심종목=%s",
            self._strategy.name,
            self._fixed_watchlist,
        )

    @property
    def _watchlist(self) -> list[str]:
        """고정 관심종목 + 스크리닝 종목을 반환한다 (외부 호환용)."""
        return self._fixed_watchlist

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
        for code in self._fixed_watchlist:
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

    # ── 메인 작업 ─────────────────────────────────────────

    async def pre_market(self) -> None:
        """장 시작 전 작업: 토큰 갱신, 잔고 확인, 일봉 캐싱, 스크리닝."""
        logger.info("=== 장 시작 전 작업 시작 ===")
        self._today_trade_count = 0
        self._cycle_count = 0
        self._daily_limit_reached = False
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

            self._ensure_watchlist_stocks()

            # 관심종목 일봉 사전 캐싱
            for code in self._fixed_watchlist:
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

        # 일일 한도 초과 시 이후 사이클 전부 즉시 중단
        if self._daily_limit_reached:
            return

        logger.info("--- 장중 매매 사이클 #%d 시작 ---", self._cycle_count)

        if self._risk.check_daily_trade_limit(self._today_trade_count):
            logger.warning("일일 매매 횟수 한도 도달, 사이클 스킵")
            return

        # 주기적 스크리닝 (N사이클마다)
        if self._cycle_count % SCREENING_INTERVAL_CYCLES == 0:
            try:
                await self._screen_stocks()
            except DailyLimitExceededError:
                await self._set_daily_limit_reached()
                return

        try:
            balance = await self._get_balance()
        except DailyLimitExceededError:
            self._daily_limit_reached = True
            logger.warning("API 일일 한도 초과, 당일 매매 사이클 중단")
            return
        except Exception:
            logger.exception("잔고 조회 실패, 사이클 스킵")
            return

        held_codes = {h.stock_code for h in balance.holdings if h.quantity > 0}
        targets = self._build_monitor_targets(held_codes)
        logger.info(
            "모니터링 대상: %d종목 (보유 %d + 관심 %d + 발굴 %d)",
            len(targets),
            len(held_codes),
            len(self._fixed_watchlist),
            len(self._screened_codes),
        )

        for stock_code in targets:
            try:
                is_held = stock_code in held_codes
                holding_info = self._find_holding_from_balance(balance, stock_code)
                await self._process_stock(stock_code, balance.deposit, is_held, holding_info)
            except DailyLimitExceededError:
                await self._set_daily_limit_reached()
                return
            except Exception:
                logger.exception("종목 처리 중 에러: %s", stock_code)

        self._client._limiter.log_daily_count()
        logger.info(
            "--- 장중 매매 사이클 #%d 완료 (당일 매매: %d건) ---",
            self._cycle_count,
            self._today_trade_count,
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
        """거래량 상위 종목을 스캔하여 매수 후보를 발굴한다."""
        if len(self._screened_codes) >= MAX_SCREENED_STOCKS:
            logger.info("스크리닝 발굴 종목 상한 도달 (%d종목), 스킵", len(self._screened_codes))
            return

        logger.info("=== 종목 스크리닝 시작 ===")

        try:
            ranked = await self._quote.get_volume_rank(top_n=SCREENING_TOP_N)
        except Exception:
            logger.exception("거래량 순위 조회 실패")
            return

        remaining_slots = MAX_SCREENED_STOCKS - len(self._screened_codes)
        new_candidates: list[str] = []

        for item in ranked:
            if len(new_candidates) >= remaining_slots:
                break
            if item.stock_code in self._fixed_watchlist:
                continue
            if item.stock_code in self._screened_codes:
                continue

            try:
                df = await self._get_daily_df(item.stock_code)
                if df is None:
                    continue

                signal = self._strategy.analyze(df)

                if signal.signal_type == SignalType.BUY and signal.confidence >= 0.3:
                    new_candidates.append(item.stock_code)
                    logger.info(
                        "[스크리닝 발굴] %s(%s) — %s, 신뢰도=%.2f",
                        item.stock_name,
                        item.stock_code,
                        signal.reason,
                        signal.confidence,
                    )

            except Exception:
                logger.debug("스크리닝 분석 실패: %s", item.stock_code)

        self._screened_codes.update(new_candidates)
        logger.info(
            "=== 종목 스크리닝 완료: 신규 %d종목 발굴 (누적 %d/%d종목) ===",
            len(new_candidates),
            len(self._screened_codes),
            MAX_SCREENED_STOCKS,
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

        # 3. 전략 분석 (보유/미보유 모두 실행)
        signal = self._strategy.analyze(df)
        logger.info(
            "[%s %s] 보유=%s, 시그널=%s, 신뢰도=%.2f, 현재가=%s",
            stock_code,
            current.stock_name,
            "Y" if is_held else "N",
            signal.signal_type.value,
            signal.confidence,
            f"{current.current_price:,}",
        )

        # 4. 보유 종목 처리
        if is_held and holding_info is not None:
            await self._process_held_stock(
                stock_code, current.current_price, holding_info, signal
            )
            return

        # 5. 미보유 종목 — 매수 시그널 처리
        if signal.signal_type == SignalType.BUY:
            if not self._risk.validate_order(signal, float(deposit), 0):
                return
            quantity = self._risk.calculate_position_size(
                float(deposit), float(current.current_price)
            )
            if quantity <= 0:
                logger.info("[%s] 매수 가능 수량 0, 스킵", stock_code)
                return
            await self._execute_buy(stock_code, current.stock_name, quantity, current.current_price)

    async def _process_held_stock(
        self,
        stock_code: str,
        current_price: int,
        holding: dict[str, float],
        signal: Signal,
    ) -> None:
        """보유 종목의 매도 판단을 수행한다.

        우선순위: 손절 > 익절 > 전략 매도(데드크로스)

        Args:
            stock_code: 종목코드
            current_price: 현재가
            holding: 보유 정보
            signal: 전략 분석 시그널
        """
        avg_price = holding["avg_price"]
        quantity = int(holding["quantity"])

        if self._risk.should_stop_loss(float(current_price), avg_price):
            logger.warning(
                "[%s] 손절 매도 실행 (현재가: %d, 매입가: %.0f)",
                stock_code, current_price, avg_price,
            )
            await self._execute_sell(stock_code, quantity, current_price, reason="손절")
            return

        if self._risk.should_take_profit(float(current_price), avg_price):
            logger.info(
                "[%s] 익절 매도 실행 (현재가: %d, 매입가: %.0f)",
                stock_code, current_price, avg_price,
            )
            await self._execute_sell(stock_code, quantity, current_price, reason="익절")
            return

        if signal.signal_type == SignalType.SELL and signal.confidence >= 0.1:
            logger.info(
                "[%s] 전략 매도 실행 — %s (현재가: %d, 매입가: %.0f)",
                stock_code, signal.reason, current_price, avg_price,
            )
            await self._execute_sell(
                stock_code, quantity, current_price,
                reason="전략매도",
            )

    # ── 주문 실행 ─────────────────────────────────────────

    async def _execute_buy(
        self, stock_code: str, stock_name: str, quantity: int, price: int
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

            await self._notifier.notify_buy(stock_name, stock_code, quantity, price)

        except Exception:
            logger.exception("[매수 실패] %s(%s)", stock_name, stock_code)

    async def _execute_sell(
        self, stock_code: str, quantity: int, price: int, reason: str = ""
    ) -> None:
        """매도 주문을 실행하고 DB에 기록한다."""
        try:
            result = await self._order.sell(stock_code=stock_code, quantity=quantity)
            self._today_trade_count += 1
            self._invalidate_balance_cache()

            logger.info(
                "[매도 체결] %s %d주, 사유=%s, 주문번호=%s",
                stock_code, quantity, reason, result.order_no,
            )
            log_trade(f"매도 {stock_code} {quantity}주 @ {price:,}원 ({reason})")

            self._record_order_to_db(
                stock_code, "", OrderType.SELL, quantity, float(price), result.order_no
            )

            await self._notifier.notify_sell("", stock_code, quantity, price, reason)

        except Exception:
            logger.exception("[매도 실패] %s", stock_code)

    # ── DB 연동 ───────────────────────────────────────────

    def _create_calendar_event(self, balance: object, executions: list[object]) -> None:
        """일일 매매 결과를 Google Calendar에 등록한다."""
        try:
            auth = GoogleCalendarAuth()
            service = auth.get_service()
            creator = CalendarEventCreator(service=service)

            details = json.dumps(
                [
                    {
                        "name": e.stock_name,
                        "code": e.stock_code,
                        "buy_price": e.price if e.side == "매수" else 0,
                        "buy_qty": e.quantity if e.side == "매수" else 0,
                        "sell_price": e.price if e.side == "매도" else 0,
                        "sell_qty": e.quantity if e.side == "매도" else 0,
                        "profit_loss": 0,
                        "profit_rate": 0.0,
                    }
                    for e in executions
                ],
                ensure_ascii=False,
            )

            event_id = creator.create_daily_report_event(
                trade_date=date.today(),
                total_profit_loss=int(balance.total_profit_loss),
                profit_rate=float(balance.total_profit_rate),
                execution_count=len(executions),
                details_json=details,
            )
            logger.info("Google Calendar 이벤트 등록 완료: %s", event_id)

        except Exception:
            logger.exception("Google Calendar 이벤트 등록 실패 (매매 결과에는 영향 없음)")

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

    def _ensure_watchlist_stocks(self) -> None:
        """관심종목이 DB에 없으면 생성한다."""
        try:
            with get_session() as session:
                stock_repo = StockRepository(session)
                for code in self._fixed_watchlist:
                    if stock_repo.get_by_code(code) is None:
                        stock_repo.create(code, code, "KOSPI")
                        logger.info("관심종목 DB 등록: %s", code)

        except Exception:
            logger.exception("관심종목 DB 등록 실패")

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
