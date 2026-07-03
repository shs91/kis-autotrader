"""스크리닝 전용 Worker.

메인 매매 엔진과 별도 asyncio.Task로 실행되며,
Redis Rate Limiter를 통해 API 호출 할당량을 관리한다.
스크리닝 결과는 screening_results 테이블에 저장되고,
메인 엔진은 이 테이블에서 최신 결과를 읽는다.

메인 엔진 ↔ screening_results 조회 규약 (proposal 2026-04-16):
- ScreeningWorker는 ``_record_to_db`` → ``ScreeningResultRepository``를 통해
  ``screening_results`` 테이블에 insert한다. 이때 상위 후보는
  ``converted_to_trade=True``로 표시되어 메인 엔진이 참조할 수 있도록
  마킹된다(실제 매매 전환 여부가 아닌 "스코어 컷을 통과해 매매 평가
  대상으로 승격된 후보" 의 의미).
- 메인 엔진(`src.engine.TradingEngine._screen_stocks`)은 해당 날짜의
  ``converted_to_trade=True`` 레코드를 `ScreeningResultRepository.get_by_date`
  로 조회하여 `self._screened_codes`에 병합한다. 즉 조회 키는
  ``(date=today, converted_to_trade=True)``이며 사이클 번호는 Worker와
  엔진이 독립적으로 카운트한다.
- 이 규약이 깨지면(예: Worker가 converted_to_trade=False만 insert, 날짜
  불일치) 메인 엔진이 발굴된 종목을 읽어오지 못해 스크리닝→시그널 평가
  파이프라인이 단절된다. 디버깅은 ``EVAL_TARGETS`` 메트릭의
  ``detail.counts.screening`` 값을 우선 확인할 것.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd

from src.api.auth import KISAuth
from src.api.client import KISClient
from src.api.overseas_quote import OverseasQuoteAPI
from src.api.quote import QuoteAPI, RankItem, VolumeRankItem
from src.api.rate_limiter import HybridRateLimiter, RateLimiter
from src.config import ScreeningConfig, settings
from src.db.repository import (
    MarketActionRepository,
    NewsChunkRepository,
    ScreeningResultRepository,
    StockRepository,
    SystemMetricRepository,
)
from src.db.session import get_session
from src.market.profile import KRX_PROFILE, MarketProfile
from src.scheduler.holidays import is_market_closed
from src.strategy.disclosure_risk import match_critical_disclosure
from src.strategy.flow_filter import features_from_structured, flow_score
from src.strategy.registry import StrategyRegistry
from src.strategy.screener import (
    MergedCandidate,
    ScoredCandidate,
    ScreeningFilter,
    StockScreener,
)
from src.strategy.selector import StrategySelector
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 스크리닝 기본 주기 (초)
DEFAULT_SCREENING_INTERVAL: int = 300  # 5분

_KST = ZoneInfo("Asia/Seoul")
_MARKET_OPEN_KST = time(9, 0)
_MARKET_CLOSE_KST = time(15, 30)
# US 정규장(ET) — 스크리닝 윈도우. 엔진 사이클(15:50 종료)과 달리 발굴은 정규장 전체.
_US_REGULAR_OPEN_ET = time(9, 30)
_US_REGULAR_CLOSE_ET = time(16, 0)


class ScreeningWorker:
    """스크리닝 전용 Worker.

    장 시작 전(pre_market)과 장중 주기적으로 실행되며,
    거래량 순위 → 필터링 → 전략 분석 → 스코어링 → DB 기록을 수행한다.
    메인 매매 엔진은 screening_results 테이블에서 최신 결과만 읽는다.
    """

    def __init__(
        self,
        interval: int = DEFAULT_SCREENING_INTERVAL,
        market_profile: MarketProfile | None = None,
    ) -> None:
        """ScreeningWorker를 초기화한다.

        Args:
            interval: 스크리닝 실행 주기 (초).
            market_profile: 시장 프로파일(None이면 KRX). US면 해외 시세 API 사용.
        """
        self._market = market_profile or KRX_PROFILE
        self._tz = ZoneInfo(self._market.timezone)
        self._auth = KISAuth()
        self._limiter = HybridRateLimiter(role="screener")
        # HybridRateLimiter는 RateLimiter와 구조적으로 호환(async acquire 동일).
        # KISClient는 limiter.acquire()만 사용하므로 런타임상 안전.
        self._client = KISClient(
            auth=self._auth, limiter=cast("RateLimiter", self._limiter)
        )
        self._quote = QuoteAPI(client=self._client)
        # US는 해외 시세 API(거래소별 순위·해외 일봉). KRX는 None(미사용).
        self._ovs_quote: OverseasQuoteAPI | None = (
            OverseasQuoteAPI(client=self._client)
            if self._market.is_overseas
            else None
        )
        self._screener = StockScreener(is_overseas=self._market.is_overseas)

        registry = StrategyRegistry.create_default()
        self._selector = StrategySelector.from_config(registry)

        self._interval = interval
        self._running = False
        self._cycle_count = 0
        # 수급 flow 일일 캐시 (증분2) — 종목당 1회/일 조회로 per-stock 예산 절감
        self._flow_cache: dict[str, float] = {}
        self._flow_cache_date: date | None = None

        logger.info(
            "ScreeningWorker 초기화 (주기=%d초, role=screener)",
            self._interval,
        )

    async def run(self) -> None:
        """스크리닝 Worker 메인 루프.

        interval 간격으로 스크리닝을 실행한다.
        """
        self._running = True
        logger.info("ScreeningWorker 시작 (주기=%d초)", self._interval)

        while self._running:
            try:
                await self._run_screening()
            except asyncio.CancelledError:
                logger.info("ScreeningWorker 종료 요청 수신")
                break
            except Exception:
                logger.exception("스크리닝 실행 중 에러 (다음 주기에 재시도)")

            await asyncio.sleep(self._interval)

        self._running = False
        logger.info("ScreeningWorker 종료")

    def _is_trading_window(self) -> bool:
        """현재 시각이 해당 시장 매매시간인지 판정한다(시장별).

        KRX는 기존 그대로 평일 09:00~15:30 KST. US는 ET 정규장 09:30~16:00 +
        미국 휴장일(holidays_us). 시장 타임존·휴장일 모두 self._market 기준.
        """
        if self._market.is_overseas:
            now = datetime.now(self._tz)
            if is_market_closed(now.date(), self._market.market_code):
                return False
            return _US_REGULAR_OPEN_ET <= now.time() <= _US_REGULAR_CLOSE_ET
        now_kst = datetime.now(_KST)
        if is_market_closed(now_kst.date()):
            return False
        t = now_kst.time()
        return _MARKET_OPEN_KST <= t <= _MARKET_CLOSE_KST

    async def _run_screening(self) -> None:
        """스크리닝 1회를 실행한다."""
        if not self._is_trading_window():
            logger.debug("매매시간/개장일 외 — 스크리닝 스킵")
            return
        self._cycle_count += 1
        scfg = settings.screening

        if self._market.is_overseas:
            await self._run_screening_us(scfg)
            return

        if scfg.multisource_enabled:
            await self._run_screening_multisource(scfg)
            return

        # 1단계: 거래량 순위 조회 (KIS API)
        try:
            ranked = await self._quote.get_volume_rank(top_n=scfg.top_n)
        except Exception:
            logger.exception("거래량 순위 조회 실패")
            return

        if not ranked:
            return

        # 2단계: 필터링
        exclude_codes: set[str] = set()
        try:
            exclude_codes = self._load_existing_screened_codes()
        except Exception:
            logger.debug("기존 스크리닝 코드 로드 실패")

        # 2-1단계: 위험종목 사전 배제 — 상장폐지/정리매매/관리종목 등은 후보 풀에서
        # 제거한다. 정리매매 종목의 급등락이 기술지표를 강한 BUY로 속여 단일 위험종목에
        # 매수신호가 고착되던 문제(2026-05-27~ 230980)를 신호 생성 이전에 차단한다.
        # 매매 엔진 buy-time 게이트와 동일 데이터·키워드를 사용(disclosure_risk 공유).
        risk_blocked = self._load_risk_blocked_codes(
            {item.stock_code for item in ranked}
        )
        if risk_blocked:
            exclude_codes |= set(risk_blocked)
            self._record_risk_excluded_metric(risk_blocked)
            logger.info(
                "스크리닝 위험종목 사전 배제: %d종목 (%s)",
                len(risk_blocked),
                ", ".join(sorted(risk_blocked)),
            )

        filtered = self._screener.filter_candidates(ranked, exclude_codes)

        # 3단계: 전략 분석 + 스코어링
        scored: list[ScoredCandidate] = []
        for rank_idx, item in enumerate(filtered):
            try:
                daily_prices = await self._quote.get_daily_price(item.stock_code)
                if len(daily_prices) < 36:
                    continue

                df = pd.DataFrame(
                    [
                        {"close": p.close_price, "date": p.date}
                        for p in reversed(daily_prices)
                    ]
                )

                strategy = self._selector.get_strategy(item.stock_code)
                signal = strategy.analyze(df)

                candidate = self._screener.score_candidate(
                    item, rank_idx, len(filtered), signal,
                )
                scored.append(candidate)

            except Exception:
                logger.debug("스크리닝 분석 실패: %s", item.stock_code)

        # 4단계: 종합 점수 정렬 + 컷
        top_candidates = self._screener.rank_candidates(scored)

        # 5단계: DB 기록
        new_codes: list[str] = []
        remaining_slots = scfg.max_screened - len(exclude_codes)
        for candidate in top_candidates[:max(remaining_slots, 0)]:
            new_codes.append(candidate.stock_code)

        self._record_to_db(ranked, new_codes)

        logger.info(
            "=== 스크리닝 Worker 완료 (사이클 #%d): "
            "조회 %d종목, 발굴 %d종목 ===",
            self._cycle_count,
            len(ranked),
            len(new_codes),
        )

    async def _run_screening_multisource(self, scfg: ScreeningConfig) -> None:
        """멀티소스 스크리닝 1회 (마스터 스위치 ON).

        4 순위 조회 → 병합 → 위험종목 배제 → 필터 → 사전컷(예산 가드) →
        daily-price 분석 → 5축 스코어 → DB 기록 + 관측 메트릭.
        """
        sources = await self._fetch_rank_sources(scfg)
        if not any(sources.values()):
            logger.warning("멀티소스 순위 조회 전부 실패 — 스킵")
            return

        merged = self._screener.merge_rankings(sources)

        exclude_codes: set[str] = set()
        try:
            exclude_codes = self._load_existing_screened_codes()
        except Exception:
            logger.debug("기존 스크리닝 코드 로드 실패")

        risk_blocked = self._load_risk_blocked_codes({m.stock_code for m in merged})
        if risk_blocked:
            exclude_codes |= set(risk_blocked)
            self._record_risk_excluded_metric(risk_blocked)

        filtered = self._screener.filter_candidates(merged, exclude_codes)
        # 예산 가드: 사전점수 상위 max_analysis_pool개만 daily-price 분석 대상으로 컷
        filtered.sort(key=self._screener.prelim_score, reverse=True)
        analysis_pool = filtered[: scfg.max_analysis_pool]

        scored: list[ScoredCandidate] = []
        for cand in analysis_pool:
            try:
                daily_prices = await self._quote.get_daily_price(cand.stock_code)
                if len(daily_prices) < 36:
                    continue
                df = pd.DataFrame(
                    [
                        {"close": p.close_price, "date": p.date}
                        for p in reversed(daily_prices)
                    ]
                )
                strategy = self._selector.get_strategy(cand.stock_code)
                signal = strategy.analyze(df)
                fs = (
                    await self._get_flow_score(cand.stock_code)
                    if scfg.flow_enabled
                    else 0.0
                )
                scored.append(
                    self._screener.score_merged_candidate(cand, signal, flow_score=fs)
                )
            except Exception:
                logger.debug("스크리닝 분석 실패: %s", cand.stock_code)

        top_candidates = self._screener.rank_candidates(scored)

        new_codes: list[str] = []
        remaining_slots = scfg.max_screened - len(exclude_codes)
        for candidate in top_candidates[: max(remaining_slots, 0)]:
            new_codes.append(candidate.stock_code)

        self._record_to_db(analysis_pool, new_codes)
        self._record_multisource_metric(
            sources, len(merged), len(filtered), len(analysis_pool), new_codes
        )

        logger.info(
            "=== 멀티소스 스크리닝 완료 (#%d): 소스 %s, 병합 %d, 필터 %d, 분석 %d, 발굴 %d ===",
            self._cycle_count,
            {k: len(v) for k, v in sources.items()},
            len(merged),
            len(filtered),
            len(analysis_pool),
            len(new_codes),
        )

    async def _run_screening_us(self, scfg: ScreeningConfig) -> None:
        """미국 동적 스크리닝 1회 (거래소별 순위 → 필터 → 일봉분석 → 스코어 → 적재).

        거래소(OVRS_EXCG_CD NASD/NYSE/AMEX)별 거래량순위(EXCD NAS/NYS/AMS)를 조회해
        VolumeRankItem으로 변환·병합하고, ``exch_of[symbol]``에 주문용 거래소코드를
        기록한다. 일봉은 해외 일봉(EXCD)으로 분석한다. 적재 시 market="US" +
        stocks.market=거래소(엔진이 _exchanges 시드 → 올바른 거래소로 주문).
        """
        ovs = self._ovs_quote
        if ovs is None:  # 방어 (US 프로파일이면 항상 존재)
            return

        merged: dict[str, VolumeRankItem] = {}
        exch_of: dict[str, str] = {}  # symbol → OVRS_EXCG_CD (주문/stocks.market)
        for exch_ovrs in self._market.exchanges:  # NASD, NYSE, AMEX
            excd = self._market.quote_exchange_map.get(exch_ovrs, exch_ovrs)
            try:
                ranking = await ovs.get_ranking(excd, top_n=scfg.top_n)
            except Exception:
                logger.exception("해외 거래량순위 조회 실패: %s", exch_ovrs)
                continue
            for r in ranking:
                if r.symbol in merged:  # 거래소 중복(드묾) — 첫 거래소 유지
                    continue
                merged[r.symbol] = VolumeRankItem(
                    stock_code=r.symbol,
                    stock_name=r.name or r.symbol,  # 순위 응답의 영문명(ename)
                    current_price=int(round(r.last)),
                    change_rate=r.change_rate,
                    volume=r.volume,
                    market_cap=0,  # 미제공 → US는 시총 필터 스킵(is_overseas)
                )
                exch_of[r.symbol] = exch_ovrs

        all_items = list(merged.values())
        if not all_items:
            return

        exclude_codes: set[str] = set()
        try:
            exclude_codes = self._load_existing_screened_codes()
        except Exception:
            logger.debug("기존 스크리닝 코드 로드 실패")

        filtered = self._screener.filter_candidates(all_items, exclude_codes)

        scored: list[ScoredCandidate] = []
        for rank_idx, item in enumerate(filtered):
            excd = self._market.quote_exchange_map.get(
                exch_of.get(item.stock_code, ""), ""
            )
            if not excd:
                continue
            try:
                daily = await ovs.get_daily_price(item.stock_code, excd)
                if len(daily) < 36:
                    continue
                df = pd.DataFrame(
                    [
                        {"close": float(p.close), "date": p.date}
                        for p in reversed(daily)
                    ]
                )
                strategy = self._selector.get_strategy(item.stock_code)
                signal = strategy.analyze(df)
                scored.append(
                    self._screener.score_candidate(
                        item, rank_idx, len(filtered), signal
                    )
                )
            except Exception:
                logger.debug("US 스크리닝 분석 실패: %s", item.stock_code)

        top_candidates = self._screener.rank_candidates(scored)
        remaining_slots = scfg.max_screened - len(exclude_codes)
        new_codes = [c.stock_code for c in top_candidates[: max(remaining_slots, 0)]]

        self._record_to_db(all_items, new_codes, market="US", exch_of=exch_of)

        logger.info(
            "=== US 스크리닝 완료 (#%d): 조회 %d종목, 필터 %d, 발굴 %d ===",
            self._cycle_count, len(all_items), len(filtered), len(new_codes),
        )

    async def _fetch_rank_sources(
        self, scfg: ScreeningConfig
    ) -> dict[str, list[RankItem]]:
        """4개 순위 소스를 {source: list[RankItem]}로 조회한다.

        거래량순위는 VolumeRankItem → RankItem 변환(source_rank=조회 순번, market_cap
        보존). 각 소스 실패는 빈 리스트로 격리한다(한 소스 실패가 나머지를 막지 않음).
        """
        sources: dict[str, list[RankItem]] = {}
        try:
            vol = await self._quote.get_volume_rank(top_n=scfg.top_n)
            sources["volume"] = [
                RankItem(
                    stock_code=v.stock_code,
                    stock_name=v.stock_name,
                    current_price=v.current_price,
                    change_rate=v.change_rate,
                    volume=v.volume,
                    source_rank=idx,
                    market_cap=v.market_cap,
                )
                for idx, v in enumerate(vol, start=1)
            ]
        except Exception:
            logger.exception("거래량 순위 조회 실패")
            sources["volume"] = []

        rank_fetchers = (
            ("change_rate", self._quote.get_change_rate_rank),
            ("volume_power", self._quote.get_volume_power_rank),
            ("quote_balance", self._quote.get_quote_balance_rank),
        )
        for key, fetch in rank_fetchers:
            try:
                sources[key] = await fetch(top_n=scfg.top_n)
            except Exception:
                logger.exception("%s 순위 조회 실패", key)
                sources[key] = []
        return sources

    def _record_multisource_metric(
        self,
        sources: dict[str, list[RankItem]],
        merged_count: int,
        filtered_count: int,
        analyzed_count: int,
        new_codes: list[str],
    ) -> None:
        """멀티소스 깔때기를 SCREENING_MULTISOURCE 메트릭으로 기록(관측용)."""
        try:
            with get_session() as session:
                SystemMetricRepository(session).record_metric(
                    metric_type="SCREENING_MULTISOURCE",
                    detail={
                        "cycle": self._cycle_count,
                        "sources": {k: len(v) for k, v in sources.items()},
                        "merged": merged_count,
                        "filtered": filtered_count,
                        "analyzed": analyzed_count,
                        "candidates": len(new_codes),
                    },
                )
        except Exception:
            logger.debug("SCREENING_MULTISOURCE 메트릭 기록 실패")

    async def _get_flow_score(self, stock_code: str) -> float:
        """종목 수급 flow_score(-1~1)를 일일 캐시로 조회한다(증분2).

        investor_trend(FHPTJ04160001) 1콜만 사용(flow_score는 공매도 미반영). 날짜
        변경 시 캐시 리셋. None/에러는 0.0으로 캐시(당일 재호출 방지).
        """
        today = date.today()
        if self._flow_cache_date != today:
            self._flow_cache = {}
            self._flow_cache_date = today
        cached = self._flow_cache.get(stock_code)
        if cached is not None:
            return cached
        trend = await self._quote.get_investor_trend_daily(stock_code)
        if trend is None:
            self._flow_cache[stock_code] = 0.0
            return 0.0
        features = features_from_structured(
            institution_net=trend.institution_net_qty,
            foreign_net=trend.foreign_net_qty,
            individual_net=trend.individual_net_qty,
            pension_net=trend.pension_net_qty,
        )
        score = flow_score(features)
        self._flow_cache[stock_code] = score
        return score

    def _load_existing_screened_codes(self) -> set[str]:
        """fresh window 내 converted 종목코드를 시장별로 조회한다(재발굴 배제 목록).

        배제를 '당일 converted 전체'로 잡으면 재발굴이 불가능해져 엔진 회전의
        latest_at이 발굴 시각에 동결되고, 모든 후보가 fresh window 경과 시 영구
        제거된다(모니터링 유니버스 기아 — 2026-07-03 감사: 체류 median 29.7분,
        상시 ~3종목). fresh window 내로 좁히면 계속 순위권인 종목은 재발굴·재기록돼
        latest_at이 갱신되고, 순위 탈락 종목만 자연 회전으로 제거된다.
        """
        now = datetime.now(self._tz)
        cutoff = now - timedelta(minutes=settings.screening.fresh_window_min)
        with get_session() as session:
            repo = ScreeningResultRepository(session)
            results = repo.get_by_date(
                now.date(),
                market=self._market.market_code,
                tz=self._market.timezone,
            )
            return {
                r.stock_code
                for r in results
                if r.converted_to_trade and r.screened_at >= cutoff
            }

    def _load_risk_blocked_codes(self, codes: set[str]) -> dict[str, str]:
        """후보 중 매수 위험종목(시장조치 차단 OR 치명 공시)을 ``{code: 사유}``로 반환.

        매매 엔진 buy-time 게이트(``_check_market_action_block`` /
        ``_check_disclosure_risk_block``)와 동일한 데이터(market_actions, DART 공시)와
        키워드(``disclosure_risk``)를 사용해, 위험종목이 애초에 후보 풀·신호 평가에
        들어오지 못하게 한다. DB 조회 실패는 스크리닝을 막지 않도록 swallow(빈 dict).
        """
        if not codes:
            return {}
        tcfg = settings.trading
        blocked: dict[str, str] = {}
        try:
            since = datetime.now(UTC) - timedelta(days=tcfg.news_risk_lookback_days)
            gate_on = tcfg.news_risk_gate_enabled
            with get_session() as session:
                ma_repo = MarketActionRepository(session)
                news_repo = NewsChunkRepository(session)
                for code in codes:
                    ma = ma_repo.get(code)
                    if ma is not None and ma.should_block_buy:
                        blocked[code] = ",".join(ma.block_reasons) or "MARKET_ACTION"
                        continue
                    if gate_on:
                        title = match_critical_disclosure(
                            news_repo.get_recent_disclosure_titles(code, since)
                        )
                        if title:
                            blocked[code] = title
        except Exception:
            logger.exception("위험종목 사전 배제 lookup 실패 (스크리닝은 계속)")
        return blocked

    def _record_risk_excluded_metric(self, blocked: dict[str, str]) -> None:
        """배제된 위험종목을 ``SCREENING_RISK_EXCLUDED`` 메트릭으로 기록(관측용)."""
        try:
            with get_session() as session:
                SystemMetricRepository(session).record_metric(
                    metric_type="SCREENING_RISK_EXCLUDED",
                    detail={
                        "cycle": self._cycle_count,
                        "count": len(blocked),
                        "codes": sorted(blocked.keys()),
                    },
                )
        except Exception:
            logger.debug("SCREENING_RISK_EXCLUDED 메트릭 기록 실패")

    def _record_to_db(
        self,
        ranked: Sequence[VolumeRankItem | MergedCandidate],
        new_candidates: list[str],
        market: str = "KRX",
        exch_of: dict[str, str] | None = None,
    ) -> None:
        """스크리닝 결과를 screening_results 테이블에 배치 기록한다(KRX·US·멀티소스 공통).

        US는 ``market="US"`` + ``exch_of[code]``(주문용 거래소코드)로 ``stocks.market``을
        거래소로 upsert해, 엔진 ``_screen_stocks``가 이를 읽어 ``_exchanges``를 시드하고
        올바른 거래소로 주문하게 한다. ETF 판별은 시장별(US는 심볼셋/이름 키워드).
        """
        is_overseas = self._market.is_overseas
        exch_of = exch_of or {}
        try:
            candidate_set = set(new_candidates)
            etf_blocked = 0
            with get_session() as session:
                repo = ScreeningResultRepository(session)
                stock_repo = StockRepository(session) if is_overseas else None
                for rank_idx, item in enumerate(ranked, start=1):
                    if ScreeningFilter._is_etf_etn(
                        item.stock_code, item.stock_name, is_overseas
                    ):
                        etf_blocked += 1
                        continue
                    repo.record_screening(
                        stock_code=item.stock_code,
                        stock_name=item.stock_name,
                        screening_rank=rank_idx,
                        volume=item.volume,
                        price_change_pct=item.change_rate,
                        screened_at=datetime.now(UTC),
                        cycle_number=self._cycle_count,
                        converted_to_trade=item.stock_code in candidate_set,
                        market=market,
                    )
                    # US: stocks.market=거래소코드 upsert (엔진 거래소 라우팅 시드).
                    if stock_repo is not None:
                        exch = exch_of.get(item.stock_code)
                        if exch:
                            existing = stock_repo.get_by_code(item.stock_code)
                            if existing is None:
                                stock_repo.create(
                                    item.stock_code, item.stock_name, exch
                                )
                            elif existing.market != exch:
                                existing.market = exch
                try:
                    SystemMetricRepository(session).record_metric(
                        metric_type="SCREENING_CANDIDATE",
                        detail={
                            "cycle": self._cycle_count,
                            "ranked_total": len(ranked),
                            "candidate_count": len(candidate_set),
                        },
                    )
                except Exception:
                    logger.exception("SCREENING_CANDIDATE 메트릭 기록 실패")
            if etf_blocked:
                logger.info("스크리닝 DB 적재 시 ETF 블록 %d건 차단", etf_blocked)
        except Exception:
            logger.exception("스크리닝 DB 적재 실패")

    def stop(self) -> None:
        """Worker를 정지한다."""
        self._running = False
