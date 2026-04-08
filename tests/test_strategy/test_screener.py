"""StockScreener 단위 테스트."""

from __future__ import annotations

import pytest

from src.api.quote import VolumeRankItem
from src.config import ScreeningConfig
from src.strategy.base import Signal, SignalType
from src.strategy.screener import (
    ScreeningFilter,
    ScreeningScorer,
    ScoredCandidate,
    StockScreener,
)


# ── 테스트 데이터 팩토리 ──────────────────────────


def _item(
    code: str = "005930",
    name: str = "삼성전자",
    price: int = 70000,
    change_rate: float = 3.0,
    volume: int = 1_000_000,
    market_cap: int = 500_000_000,
) -> VolumeRankItem:
    return VolumeRankItem(
        stock_code=code,
        stock_name=name,
        current_price=price,
        change_rate=change_rate,
        volume=volume,
        market_cap=market_cap,
    )


def _signal(
    signal_type: SignalType = SignalType.BUY,
    confidence: float = 0.7,
    reason: str = "골든크로스 발생",
) -> Signal:
    return Signal(signal_type=signal_type, confidence=confidence, reason=reason)


def _config(**overrides: object) -> ScreeningConfig:
    defaults = {
        "top_n": 20,
        "interval_cycles": 60,
        "max_screened": 15,
        "min_price": 1000,
        "max_price": 500000,
        "min_market_cap": 100_000_000,
        "change_rate_min": -5.0,
        "change_rate_max": 15.0,
        "min_volume": 10000,
        "weight_volume_rank": 0.3,
        "weight_change_rate": 0.3,
        "weight_strategy": 0.4,
        "min_score": 0.3,
    }
    defaults.update(overrides)
    return ScreeningConfig(**defaults)  # type: ignore[arg-type]


# ── ScreeningFilter 테스트 ────────────────────────


class TestScreeningFilter:
    """사전 필터 테스트."""

    def test_pass_normal_stock(self) -> None:
        """정상 종목은 통과한다."""
        f = ScreeningFilter(config=_config())
        result = f.apply([_item()], exclude_codes=set())
        assert len(result) == 1

    def test_exclude_codes(self) -> None:
        """제외 목록에 있는 종목은 걸러진다."""
        f = ScreeningFilter(config=_config())
        result = f.apply([_item()], exclude_codes={"005930"})
        assert len(result) == 0

    def test_filter_low_price(self) -> None:
        """최소 가격 미만 종목은 걸러진다."""
        f = ScreeningFilter(config=_config(min_price=2000))
        result = f.apply([_item(price=1500)], exclude_codes=set())
        assert len(result) == 0

    def test_filter_high_price(self) -> None:
        """최대 가격 초과 종목은 걸러진다."""
        f = ScreeningFilter(config=_config(max_price=50000))
        result = f.apply([_item(price=70000)], exclude_codes=set())
        assert len(result) == 0

    def test_filter_low_market_cap(self) -> None:
        """최소 시가총액 미만 종목은 걸러진다."""
        f = ScreeningFilter(config=_config(min_market_cap=1_000_000_000))
        result = f.apply([_item(market_cap=500_000_000)], exclude_codes=set())
        assert len(result) == 0

    def test_filter_extreme_change_rate(self) -> None:
        """등락률이 범위 밖인 종목은 걸러진다."""
        f = ScreeningFilter(config=_config(change_rate_max=10.0))
        result = f.apply([_item(change_rate=20.0)], exclude_codes=set())
        assert len(result) == 0

    def test_filter_low_volume(self) -> None:
        """최소 거래량 미만 종목은 걸러진다."""
        f = ScreeningFilter(config=_config(min_volume=500000))
        result = f.apply([_item(volume=100000)], exclude_codes=set())
        assert len(result) == 0

    def test_multiple_filters_combined(self) -> None:
        """여러 필터가 동시에 적용된다."""
        f = ScreeningFilter(config=_config())
        items = [
            _item(code="001", price=500),  # 가격 미달
            _item(code="002", change_rate=20.0),  # 등락률 초과
            _item(code="003"),  # 정상
            _item(code="004", volume=5000),  # 거래량 미달
        ]
        result = f.apply(items, exclude_codes=set())
        assert len(result) == 1
        assert result[0].stock_code == "003"


# ── ScreeningScorer 테스트 ────────────────────────


class TestScreeningScorer:
    """스코어링 테스트."""

    def test_top_rank_gets_highest_volume_score(self) -> None:
        """1위는 거래량 점수 1.0을 받는다."""
        scorer = ScreeningScorer(config=_config())
        result = scorer.score(_item(), rank_index=0, total_count=20, signal=_signal())
        assert result.volume_rank_score == 1.0

    def test_last_rank_gets_lowest_volume_score(self) -> None:
        """꼴찌는 거래량 점수 0.0을 받는다."""
        scorer = ScreeningScorer(config=_config())
        result = scorer.score(_item(), rank_index=19, total_count=20, signal=_signal())
        assert result.volume_rank_score == 0.0

    def test_positive_change_rate_scores_higher(self) -> None:
        """양의 등락률이 0보다 높은 점수를 받는다."""
        scorer = ScreeningScorer(config=_config())
        r1 = scorer.score(_item(change_rate=5.0), 0, 10, _signal())
        r2 = scorer.score(_item(change_rate=-2.0), 0, 10, _signal())
        assert r1.change_rate_score > r2.change_rate_score

    def test_overheat_change_rate_penalized(self) -> None:
        """15% 이상 급등은 감점된다."""
        scorer = ScreeningScorer(config=_config())
        r_normal = scorer.score(_item(change_rate=8.0), 0, 10, _signal())
        r_overheat = scorer.score(_item(change_rate=18.0), 0, 10, _signal())
        assert r_normal.change_rate_score > r_overheat.change_rate_score

    def test_sell_signal_gets_zero_strategy_score(self) -> None:
        """매도 시그널은 전략 점수 0을 받는다."""
        scorer = ScreeningScorer(config=_config())
        sell_signal = _signal(signal_type=SignalType.SELL, confidence=0.9)
        result = scorer.score(_item(), 0, 10, sell_signal)
        assert result.strategy_score == 0.0

    def test_hold_signal_gets_zero_strategy_score(self) -> None:
        """HOLD 시그널은 전략 점수 0을 받는다."""
        scorer = ScreeningScorer(config=_config())
        hold_signal = _signal(signal_type=SignalType.HOLD, confidence=0.5)
        result = scorer.score(_item(), 0, 10, hold_signal)
        assert result.strategy_score == 0.0

    def test_total_score_weighted_sum(self) -> None:
        """종합 점수는 가중합산 값이다."""
        cfg = _config(
            weight_volume_rank=0.3,
            weight_change_rate=0.3,
            weight_strategy=0.4,
        )
        scorer = ScreeningScorer(config=cfg)
        result = scorer.score(
            _item(change_rate=10.0),  # change_rate_score = 1.0
            rank_index=0,  # volume_rank_score = 1.0
            total_count=10,
            signal=_signal(confidence=1.0),  # strategy_score = 1.0
        )
        assert result.total_score == pytest.approx(1.0, abs=0.01)


# ── StockScreener 통합 테스트 ─────────────────────


class TestStockScreener:
    """스크리너 통합 테스트."""

    def test_rank_candidates_sorts_by_score(self) -> None:
        """후보가 종합 점수 내림차순으로 정렬된다."""
        screener = StockScreener(config=_config(min_score=0.0))
        scorer = ScreeningScorer(config=_config())

        items = [
            _item(code="A", change_rate=1.0),
            _item(code="B", change_rate=8.0),
        ]
        scored = [
            scorer.score(items[0], 1, 2, _signal(confidence=0.2)),
            scorer.score(items[1], 0, 2, _signal(confidence=0.9)),
        ]

        ranked = screener.rank_candidates(scored)
        assert ranked[0].stock_code == "B"
        assert ranked[0].total_score >= ranked[-1].total_score

    def test_rank_candidates_cuts_below_min_score(self) -> None:
        """최소 점수 미만 후보는 제거된다."""
        screener = StockScreener(config=_config(min_score=0.5))
        scorer = ScreeningScorer(config=_config())

        low_signal = _signal(signal_type=SignalType.HOLD, confidence=0.0)
        high_signal = _signal(confidence=0.9)

        scored = [
            scorer.score(_item(code="A", change_rate=-1.0), 9, 10, low_signal),
            scorer.score(_item(code="B", change_rate=8.0), 0, 10, high_signal),
        ]

        ranked = screener.rank_candidates(scored)
        codes = [c.stock_code for c in ranked]
        assert "A" not in codes
        assert "B" in codes

    def test_end_to_end_filter_and_rank(self) -> None:
        """필터 → 스코어링 → 정렬 파이프라인 통합 테스트."""
        cfg = _config(min_score=0.2)
        screener = StockScreener(config=cfg)

        items = [
            _item(code="001", price=500),  # 필터 탈락
            _item(code="002", change_rate=5.0, volume=500000),
            _item(code="003", change_rate=8.0, volume=800000),
        ]

        filtered = screener.filter_candidates(items, exclude_codes=set())
        assert len(filtered) == 2

        scored = []
        for idx, item in enumerate(filtered):
            scored.append(
                screener.score_candidate(item, idx, len(filtered), _signal(confidence=0.6))
            )

        ranked = screener.rank_candidates(scored)
        assert len(ranked) >= 1
        assert all(c.total_score >= cfg.min_score for c in ranked)
