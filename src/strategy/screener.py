"""종목 스크리닝 모듈 — 필터링 + 복수 소스 스코어링."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from src.api.quote import RankItem, VolumeRankItem
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
    volume_power_score: float = 0.0  # 0.0~1.0 (체결강도 rank-decay)
    quote_balance_score: float = 0.0  # 0.0~1.0 (호가 매수잔량 rank-decay)
    flow_score: float = 0.0  # [-1,1] 수급(기관·외국인 순매수) 가산 신호


@dataclass
class MergedCandidate:
    """복수 순위 소스를 병합한 후보 (멀티소스 스크리닝)."""

    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    volume: int
    market_cap: int | None  # 거래량순위 출처에서만 채워짐(신규 3종 미반환)
    ranks: dict[str, int]  # {source: source_rank}
    metrics: dict[str, float]  # {source: metric}


# 필터는 단일소스(VolumeRankItem)·멀티소스(MergedCandidate) 양쪽에 동작.
_ScreenT = TypeVar("_ScreenT", VolumeRankItem, MergedCandidate)


def _rank_decay(rank: int | None, top_n: int) -> float:
    """순위 → [0.0, 1.0] 점수. 1위=1.0, top_n위≈0.0, 미등장(None)=0.0."""
    if rank is None or rank < 1 or top_n < 1:
        return 0.0
    return max(0.0, 1.0 - (rank - 1) / top_n)


class ScreeningFilter:
    """스크리닝 사전 필터.

    거래량 상위 목록에서 부적합 종목을 빠르게 걸러낸다.
    """

    def __init__(self, config: ScreeningConfig | None = None) -> None:
        """ScreeningFilter를 초기화한다."""
        self._config = config or settings.screening

    def apply(
        self,
        items: list[_ScreenT],
        exclude_codes: set[str],
    ) -> list[_ScreenT]:
        """필터 조건을 적용하여 후보를 반환한다(단일·멀티소스 공통).

        Args:
            items: 순위 종목 목록 (VolumeRankItem 또는 MergedCandidate)
            exclude_codes: 제외할 종목코드 (관심종목 + 기발굴)

        Returns:
            필터를 통과한 종목 목록 (입력과 동일 타입)
        """
        cfg = self._config
        passed: list[_ScreenT] = []
        etf_count = 0

        for item in items:
            if item.stock_code in exclude_codes:
                continue
            if self._is_etf_etn(item.stock_code, item.stock_name):
                etf_count += 1
                continue
            if not self._pass_filter(item, cfg):
                continue
            passed.append(item)

        logger.info(
            "스크리닝 필터: %d → %d종목 (제외 %d, ETF/ETN %d)",
            len(items), len(passed), len(items) - len(passed), etf_count,
        )
        return passed

    @staticmethod
    def _pass_filter(
        item: VolumeRankItem | MergedCandidate, cfg: ScreeningConfig
    ) -> bool:
        """단일 종목의 필터 통과 여부를 판정한다.

        멀티소스 후보는 거래량순위 외 출처면 ``market_cap``이 None일 수 있다.
        이때 시총 필터는 **건너뛴다**(breadth 보존). 나머지 필터는 동일 적용.
        """
        if ScreeningFilter._is_etf_etn(item.stock_code, item.stock_name):
            return False
        if item.current_price < cfg.min_price or item.current_price > cfg.max_price:
            return False
        if item.market_cap is not None and item.market_cap < cfg.min_market_cap:
            return False
        if item.change_rate < cfg.change_rate_min or item.change_rate > cfg.change_rate_max:
            return False
        if item.volume < cfg.min_volume:
            return False
        return True

    _ETF_BRAND_KEYWORDS: tuple[str, ...] = (
        "KODEX", "TIGER", "KBSTAR", "ARIRANG", "SOL ", "ACE ",
        "HANARO", "ETN", "레버리지", "인버스", "2X", "곱버스",
        # 2024+ 리브랜딩·누락 브랜드 + 펀드형 상품 (2026-06-01 RISE 채권혼합 누수 대응)
        "RISE ", "PLUS ", "KOSEF", "KINDEX", "TIMEFOLIO", "히어로즈", "마이다스",
        "ETF", "채권혼합", "혼합형",
    )

    _ETF_BLOCKLIST: set[str] | None = None

    @staticmethod
    def _load_etf_blocklist() -> set[str]:
        """config/etf_blocklist.json에서 ETF 블록리스트를 로드한다."""
        if ScreeningFilter._ETF_BLOCKLIST is not None:
            return ScreeningFilter._ETF_BLOCKLIST
        try:
            path = Path(__file__).resolve().parents[2] / "config" / "etf_blocklist.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            ScreeningFilter._ETF_BLOCKLIST = set(data.get("codes", []))
        except Exception:
            logger.warning("ETF 블록리스트 로드 실패 — 빈 set으로 fallback")
            ScreeningFilter._ETF_BLOCKLIST = set()
        return ScreeningFilter._ETF_BLOCKLIST

    @staticmethod
    def _is_etf_etn(stock_code: str, stock_name: str) -> bool:
        """ETF/ETN/레버리지/인버스/펀드형 등 비(非)일반주 여부를 판별한다."""
        # 일반 상장주식은 6자리 숫자 코드. 문자 포함 코드(ETN Q…, ELW, 구조화상품
        # 0162Z0 등)는 일반주가 아니므로 제외한다.
        if not stock_code.isdigit():
            return True
        if stock_code in ScreeningFilter._load_etf_blocklist():
            return True
        if not stock_name or stock_name == stock_code:
            return True
        upper_name = stock_name.upper()
        for keyword in ScreeningFilter._ETF_BRAND_KEYWORDS:
            if keyword.upper() in upper_name:
                return True
        return False


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

    def score_merged(
        self, candidate: MergedCandidate, signal: Signal, flow_score: float = 0.0
    ) -> ScoredCandidate:
        """멀티소스 병합 후보를 5축 + 수급 가산항으로 스코어링한다.

        per-source rank를 rank-decay로 환산(미등장=0). 신규 가중치 기본 0.0이면
        체결강도/호가잔량은 total_score에 기여하지 않는다(현행 3축과 동치). 수급
        flow_score(-1~1)는 5축 합과 **별개**의 signed 가산항(weight_flow, 기본 0.0).
        """
        cfg = self._config
        top_n = cfg.top_n
        volume_rank_score = _rank_decay(candidate.ranks.get("volume"), top_n)
        change_rate_score = self._score_change_rate(candidate.change_rate)
        volume_power_score = _rank_decay(candidate.ranks.get("volume_power"), top_n)
        quote_balance_score = _rank_decay(candidate.ranks.get("quote_balance"), top_n)
        strategy_score = (
            signal.confidence if signal.signal_type == SignalType.BUY else 0.0
        )
        total_score = (
            cfg.weight_volume_rank * volume_rank_score
            + cfg.weight_change_rate * change_rate_score
            + cfg.weight_volume_power * volume_power_score
            + cfg.weight_quote_balance * quote_balance_score
            + cfg.weight_strategy * strategy_score
            + cfg.weight_flow * flow_score
        )
        return ScoredCandidate(
            stock_code=candidate.stock_code,
            stock_name=candidate.stock_name,
            volume_rank_score=round(volume_rank_score, 4),
            change_rate_score=round(change_rate_score, 4),
            strategy_score=round(strategy_score, 4),
            total_score=round(total_score, 4),
            signal=signal,
            volume=candidate.volume,
            change_rate=candidate.change_rate,
            current_price=candidate.current_price,
            volume_power_score=round(volume_power_score, 4),
            quote_balance_score=round(quote_balance_score, 4),
            flow_score=round(flow_score, 4),
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
        items: list[_ScreenT],
        exclude_codes: set[str],
    ) -> list[_ScreenT]:
        """사전 필터를 적용한다(단일·멀티소스 공통)."""
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

    def merge_rankings(
        self, sources: dict[str, list[RankItem]]
    ) -> list[MergedCandidate]:
        """복수 순위 소스를 code로 union+dedup. per-source rank/metric 보존.

        market_cap은 'volume' 소스에서만 propagate(신규 3종 미반환). 가격/이름/거래량은
        먼저 등장한 소스 값을 쓰되 빈 값(0/공백)은 후속 소스로 보강한다.
        """
        merged: dict[str, MergedCandidate] = {}
        for source, items in sources.items():
            for it in items:
                existing = merged.get(it.stock_code)
                if existing is None:
                    merged[it.stock_code] = MergedCandidate(
                        stock_code=it.stock_code,
                        stock_name=it.stock_name,
                        current_price=it.current_price,
                        change_rate=it.change_rate,
                        volume=it.volume,
                        market_cap=it.market_cap if source == "volume" else None,
                        ranks={source: it.source_rank},
                        metrics=({source: it.metric} if it.metric is not None else {}),
                    )
                    continue
                existing.ranks[source] = it.source_rank
                if it.metric is not None:
                    existing.metrics[source] = it.metric
                if source == "volume" and it.market_cap is not None:
                    existing.market_cap = it.market_cap
                if not existing.stock_name:
                    existing.stock_name = it.stock_name
                if existing.current_price == 0:
                    existing.current_price = it.current_price
        return list(merged.values())

    def prelim_score(self, candidate: MergedCandidate) -> float:
        """daily-price 분석 전 사전 점수(전략 제외 4축). 예산 가드 상위 컷용."""
        cfg = self._config
        top_n = cfg.top_n
        return (
            cfg.weight_volume_rank * _rank_decay(candidate.ranks.get("volume"), top_n)
            + cfg.weight_change_rate
            * ScreeningScorer._score_change_rate(candidate.change_rate)
            + cfg.weight_volume_power
            * _rank_decay(candidate.ranks.get("volume_power"), top_n)
            + cfg.weight_quote_balance
            * _rank_decay(candidate.ranks.get("quote_balance"), top_n)
        )

    def score_merged_candidate(
        self, candidate: MergedCandidate, signal: Signal, flow_score: float = 0.0
    ) -> ScoredCandidate:
        """멀티소스 병합 후보를 스코어링한다(ScreeningScorer.score_merged 위임)."""
        return self._scorer.score_merged(candidate, signal, flow_score)
