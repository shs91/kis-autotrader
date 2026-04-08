"""종목 스크리닝 모듈 — 필터링 + 복수 소스 스코어링."""

from __future__ import annotations

from dataclasses import dataclass

from src.api.quote import VolumeRankItem
from src.config import ScreeningConfig, settings
from src.strategy.base import Signal, SignalType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ScoredCandidate:
    """스코어링된 매수 후보."""

    stock_code: str
    stock_name: str
    volume_rank_score: float  # 0.0~1.0 (1위 = 1.0)
    change_rate_score: float  # 0.0~1.0 (양의 등락률 가중)
    strategy_score: float  # 0.0~1.0 (전략 신뢰도)
    total_score: float  # 가중합산 종합 점수
    signal: Signal
    volume: int
    change_rate: float
    current_price: int


class ScreeningFilter:
    """스크리닝 사전 필터.

    거래량 상위 목록에서 부적합 종목을 빠르게 걸러낸다.
    """

    def __init__(self, config: ScreeningConfig | None = None) -> None:
        """ScreeningFilter를 초기화한다."""
        self._config = config or settings.screening

    def apply(
        self,
        items: list[VolumeRankItem],
        exclude_codes: set[str],
    ) -> list[VolumeRankItem]:
        """필터 조건을 적용하여 후보를 반환한다.

        Args:
            items: 거래량 순위 종목 목록
            exclude_codes: 제외할 종목코드 (관심종목 + 기발굴)

        Returns:
            필터를 통과한 종목 목록
        """
        cfg = self._config
        passed: list[VolumeRankItem] = []

        for item in items:
            if item.stock_code in exclude_codes:
                continue
            if not self._pass_filter(item, cfg):
                continue
            passed.append(item)

        logger.info(
            "스크리닝 필터: %d → %d종목 (제외 %d)",
            len(items), len(passed), len(items) - len(passed),
        )
        return passed

    @staticmethod
    def _pass_filter(item: VolumeRankItem, cfg: ScreeningConfig) -> bool:
        """단일 종목의 필터 통과 여부를 판정한다."""
        if item.current_price < cfg.min_price or item.current_price > cfg.max_price:
            return False
        if item.market_cap < cfg.min_market_cap:
            return False
        if item.change_rate < cfg.change_rate_min or item.change_rate > cfg.change_rate_max:
            return False
        if item.volume < cfg.min_volume:
            return False
        return True


class ScreeningScorer:
    """복수 소스 종합 스코어링.

    거래량 순위, 등락률, 전략 신뢰도를 가중합산하여 종합 점수를 산출한다.
    """

    def __init__(self, config: ScreeningConfig | None = None) -> None:
        """ScreeningScorer를 초기화한다."""
        self._config = config or settings.screening

    def score(
        self,
        item: VolumeRankItem,
        rank_index: int,
        total_count: int,
        signal: Signal,
    ) -> ScoredCandidate:
        """단일 종목의 종합 점수를 산출한다.

        Args:
            item: 거래량 순위 종목 정보
            rank_index: 순위 인덱스 (0-based, 0이 1위)
            total_count: 전체 후보 수
            signal: 전략 분석 결과

        Returns:
            스코어링된 후보 객체
        """
        cfg = self._config

        # 거래량 순위 점수: 1위 → 1.0, 꼴찌 → 0.0
        volume_rank_score = 1.0 - (rank_index / max(total_count - 1, 1))

        # 등락률 점수: 0~10% 구간을 0.0~1.0으로 매핑 (음수 → 0, 15% 이상 → 과열 감점)
        change_rate_score = self._score_change_rate(item.change_rate)

        # 전략 점수: 매수 시그널 신뢰도 (BUY가 아니면 0)
        strategy_score = signal.confidence if signal.signal_type == SignalType.BUY else 0.0

        # 가중합산
        total_score = (
            cfg.weight_volume_rank * volume_rank_score
            + cfg.weight_change_rate * change_rate_score
            + cfg.weight_strategy * strategy_score
        )

        return ScoredCandidate(
            stock_code=item.stock_code,
            stock_name=item.stock_name,
            volume_rank_score=round(volume_rank_score, 4),
            change_rate_score=round(change_rate_score, 4),
            strategy_score=round(strategy_score, 4),
            total_score=round(total_score, 4),
            signal=signal,
            volume=item.volume,
            change_rate=item.change_rate,
            current_price=item.current_price,
        )

    @staticmethod
    def _score_change_rate(rate: float) -> float:
        """등락률을 0.0~1.0 점수로 변환한다.

        - 음수/0%: 0.0 (하락 종목은 최하점)
        - 0~10%: 선형 0.0~1.0 (적정 상승)
        - 10~15%: 1.0~0.7 (과열 감점)
        - 15% 이상: 0.5 (급등주 경고)
        """
        if rate <= 0:
            return 0.0
        if rate <= 10:
            return rate / 10.0
        if rate <= 15:
            return 1.0 - (rate - 10) * 0.06  # 10%→1.0, 15%→0.7
        return 0.5


class StockScreener:
    """종목 스크리닝 통합 클래스.

    필터링 → 전략 분석 → 스코어링 → 정렬 파이프라인을 실행한다.
    """

    def __init__(self, config: ScreeningConfig | None = None) -> None:
        """StockScreener를 초기화한다."""
        self._config = config or settings.screening
        self._filter = ScreeningFilter(self._config)
        self._scorer = ScreeningScorer(self._config)

    @property
    def config(self) -> ScreeningConfig:
        """현재 스크리닝 설정을 반환한다."""
        return self._config

    def filter_candidates(
        self,
        items: list[VolumeRankItem],
        exclude_codes: set[str],
    ) -> list[VolumeRankItem]:
        """사전 필터를 적용한다."""
        return self._filter.apply(items, exclude_codes)

    def score_candidate(
        self,
        item: VolumeRankItem,
        rank_index: int,
        total_count: int,
        signal: Signal,
    ) -> ScoredCandidate:
        """단일 종목을 스코어링한다."""
        return self._scorer.score(item, rank_index, total_count, signal)

    def rank_candidates(
        self, candidates: list[ScoredCandidate]
    ) -> list[ScoredCandidate]:
        """후보를 종합 점수 기준으로 정렬하고 최소 점수 미만을 제거한다."""
        passed = [c for c in candidates if c.total_score >= self._config.min_score]
        passed.sort(key=lambda c: c.total_score, reverse=True)

        if candidates:
            cut_count = len(candidates) - len(passed)
            logger.info(
                "스코어링: %d종목 중 %d종목 통과 (min_score=%.2f, %d종목 컷)",
                len(candidates), len(passed), self._config.min_score, cut_count,
            )

        return passed
