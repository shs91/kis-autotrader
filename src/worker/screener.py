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
from datetime import date, datetime

from src.api.auth import KISAuth
from src.api.client import KISClient
from src.api.quote import QuoteAPI
from src.api.rate_limiter import HybridRateLimiter
from src.config import settings
from src.db.repository import ScreeningResultRepository
from src.db.session import get_session
from src.strategy.registry import StrategyRegistry
from src.strategy.screener import ScoredCandidate, StockScreener
from src.strategy.selector import StrategySelector
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 스크리닝 기본 주기 (초)
DEFAULT_SCREENING_INTERVAL: int = 300  # 5분


class ScreeningWorker:
    """스크리닝 전용 Worker.

    장 시작 전(pre_market)과 장중 주기적으로 실행되며,
    거래량 순위 → 필터링 → 전략 분석 → 스코어링 → DB 기록을 수행한다.
    메인 매매 엔진은 screening_results 테이블에서 최신 결과만 읽는다.
    """

    def __init__(
        self,
        interval: int = DEFAULT_SCREENING_INTERVAL,
    ) -> None:
        """ScreeningWorker를 초기화한다.

        Args:
            interval: 스크리닝 실행 주기 (초).
        """
        self._auth = KISAuth()
        self._limiter = HybridRateLimiter(role="screener")
        self._client = KISClient(auth=self._auth, limiter=self._limiter)
        self._quote = QuoteAPI(client=self._client)
        self._screener = StockScreener()

        registry = StrategyRegistry.create_default()
        self._selector = StrategySelector.from_config(registry)

        self._interval = interval
        self._running = False
        self._cycle_count = 0

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

    async def _run_screening(self) -> None:
        """스크리닝 1회를 실행한다."""
        self._cycle_count += 1
        scfg = settings.screening

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

        filtered = self._screener.filter_candidates(ranked, exclude_codes)

        # 3단계: 전략 분석 + 스코어링
        scored: list[ScoredCandidate] = []
        for rank_idx, item in enumerate(filtered):
            try:
                df = await self._quote.get_daily_prices(
                    stock_code=item.stock_code, count=60,
                )
                if df is None or df.empty:
                    continue

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

    def _load_existing_screened_codes(self) -> set[str]:
        """오늘 이미 스크리닝된 종목코드를 DB에서 조회한다."""
        with get_session() as session:
            repo = ScreeningResultRepository(session)
            results = repo.get_by_date(date.today())
            return {r.stock_code for r in results if r.converted_to_trade}

    def _record_to_db(
        self,
        ranked: list[object],
        new_candidates: list[str],
    ) -> None:
        """스크리닝 결과를 screening_results 테이블에 배치 기록한다."""
        try:
            candidate_set = set(new_candidates)
            with get_session() as session:
                repo = ScreeningResultRepository(session)
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

    def stop(self) -> None:
        """Worker를 정지한다."""
        self._running = False
