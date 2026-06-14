"""StockScreener 단위 테스트."""

from __future__ import annotations

import pytest

from src.api.quote import RankItem, VolumeRankItem
from src.config import ScreeningConfig
from src.strategy.base import Signal, SignalType
from src.strategy.screener import (
    MergedCandidate,
    ScreeningFilter,
    ScreeningScorer,
    StockScreener,
    _rank_decay,
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


def _rank(
    code: str,
    rank: int,
    *,
    name: str = "종목",
    price: int = 10000,
    change_rate: float = 3.0,
    volume: int = 1_000_000,
    market_cap: int | None = None,
    metric: float | None = None,
) -> RankItem:
    return RankItem(
        stock_code=code,
        stock_name=name,
        current_price=price,
        change_rate=change_rate,
        volume=volume,
        source_rank=rank,
        market_cap=market_cap,
        metric=metric,
    )


# ── 멀티소스 병합·스코어 (증분1) ──────────────────


class TestMultiSourceScreener:
    """멀티소스 병합·rank-decay·default-off 동등성."""

    def test_merge_union_dedup_and_ranks(self) -> None:
        scr = StockScreener(_config())
        sources = {
            "volume": [
                _rank("005930", 1, market_cap=500_000_000),
                _rank("000660", 2, market_cap=300_000_000),
            ],
            "volume_power": [
                _rank("005930", 3, metric=145.0),
                _rank("035720", 1, metric=130.0),
            ],
        }
        by_code = {m.stock_code: m for m in scr.merge_rankings(sources)}
        assert set(by_code) == {"005930", "000660", "035720"}
        assert by_code["005930"].ranks == {"volume": 1, "volume_power": 3}
        assert by_code["005930"].market_cap == 500_000_000
        assert by_code["035720"].market_cap is None
        assert by_code["005930"].metrics.get("volume_power") == 145.0

    def test_merge_market_cap_propagates_when_volume_later(self) -> None:
        scr = StockScreener(_config())
        sources = {
            "volume_power": [_rank("005930", 1, metric=120.0)],
            "volume": [_rank("005930", 5, market_cap=500_000_000)],
        }
        m = {x.stock_code: x for x in scr.merge_rankings(sources)}["005930"]
        assert m.market_cap == 500_000_000
        assert m.ranks == {"volume_power": 1, "volume": 5}

    def test_filter_allows_unknown_market_cap(self) -> None:
        flt = ScreeningFilter(_config(min_market_cap=100_000_000))
        cand = MergedCandidate(
            stock_code="035720", stock_name="카카오", current_price=50000,
            change_rate=3.0, volume=1_000_000, market_cap=None,
            ranks={"volume_power": 1}, metrics={},
        )
        assert len(flt.apply([cand], set())) == 1

    def test_filter_blocks_known_low_market_cap(self) -> None:
        flt = ScreeningFilter(_config(min_market_cap=100_000_000))
        cand = MergedCandidate(
            stock_code="005930", stock_name="삼성전자", current_price=50000,
            change_rate=3.0, volume=1_000_000, market_cap=1_000_000,
            ranks={"volume": 1}, metrics={},
        )
        assert flt.apply([cand], set()) == []

    def test_rank_decay_bounds(self) -> None:
        assert _rank_decay(1, 20) == 1.0
        assert _rank_decay(None, 20) == 0.0
        assert _rank_decay(21, 20) == 0.0
        assert 0.0 < _rank_decay(11, 20) < 1.0

    def test_score_merged_default_off_no_new_contribution(self) -> None:
        scr = StockScreener(_config())  # vp=qb 가중치 0.0 (default)
        cand = MergedCandidate(
            stock_code="005930", stock_name="삼성전자", current_price=70000,
            change_rate=3.0, volume=1_000_000, market_cap=500_000_000,
            ranks={"volume": 1, "volume_power": 1, "quote_balance": 1}, metrics={},
        )
        scored = scr.score_merged_candidate(cand, _signal(SignalType.BUY, 0.7))
        # 신규 컴포넌트는 계산되지만(1.0) 가중치 0이라 total 미반영
        assert scored.volume_power_score == 1.0
        assert scored.quote_balance_score == 1.0
        # 0.3*1 + 0.3*0.3 + 0.4*0.7
        assert scored.total_score == pytest.approx(0.67)

    def test_score_merged_new_signals_when_weighted(self) -> None:
        cfg = _config(
            weight_volume_rank=0.2, weight_change_rate=0.2, weight_strategy=0.4,
            weight_volume_power=0.1, weight_quote_balance=0.1,
        )
        scr = StockScreener(cfg)
        cand = MergedCandidate(
            stock_code="005930", stock_name="삼성전자", current_price=70000,
            change_rate=3.0, volume=1_000_000, market_cap=500_000_000,
            ranks={"volume": 1, "volume_power": 1, "quote_balance": 1}, metrics={},
        )
        scored = scr.score_merged_candidate(cand, _signal(SignalType.BUY, 0.7))
        # 0.2*1 + 0.2*0.3 + 0.4*0.7 + 0.1*1 + 0.1*1
        assert scored.total_score == pytest.approx(0.74)

    def test_prelim_score_excludes_strategy(self) -> None:
        cfg = _config(
            weight_volume_rank=0.5, weight_change_rate=0.5, weight_strategy=0.0,
        )
        scr = StockScreener(cfg)
        top = MergedCandidate(
            stock_code="A", stock_name="A", current_price=10000, change_rate=10.0,
            volume=1, market_cap=None, ranks={"volume": 1}, metrics={},
        )
        low = MergedCandidate(
            stock_code="B", stock_name="B", current_price=10000, change_rate=0.0,
            volume=1, market_cap=None, ranks={"volume": 20}, metrics={},
        )
        assert scr.prelim_score(top) > scr.prelim_score(low)

    def test_score_merged_flow_additive(self) -> None:
        cfg = _config(
            weight_volume_rank=0.3, weight_change_rate=0.3, weight_strategy=0.4,
            weight_flow=0.2,
        )
        scr = StockScreener(cfg)
        cand = MergedCandidate(
            stock_code="005930", stock_name="삼성전자", current_price=70000,
            change_rate=3.0, volume=1_000_000, market_cap=500_000_000,
            ranks={"volume": 1}, metrics={},
        )
        sig = _signal(SignalType.BUY, 0.7)
        base = scr.score_merged_candidate(cand, sig, flow_score=0.0)
        pos = scr.score_merged_candidate(cand, sig, flow_score=1.0)
        neg = scr.score_merged_candidate(cand, sig, flow_score=-1.0)
        # weight_flow=0.2 → total ± 0.2 (signed 가산)
        assert pos.total_score == pytest.approx(base.total_score + 0.2)
        assert neg.total_score == pytest.approx(base.total_score - 0.2)
        assert pos.flow_score == 1.0

    def test_score_merged_flow_default_off(self) -> None:
        scr = StockScreener(_config())  # weight_flow 0.0 (default)
        cand = MergedCandidate(
            stock_code="005930", stock_name="삼성전자", current_price=70000,
            change_rate=3.0, volume=1_000_000, market_cap=500_000_000,
            ranks={"volume": 1}, metrics={},
        )
        sig = _signal(SignalType.BUY, 0.7)
        a = scr.score_merged_candidate(cand, sig, flow_score=0.0)
        b = scr.score_merged_candidate(cand, sig, flow_score=-1.0)
        # weight_flow=0 → flow_score가 total에 영향 없음(필드엔 기록)
        assert a.total_score == b.total_score
        assert b.flow_score == -1.0


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


# ── ETF/ETN 필터 테스트 ─────────────────────────


class TestETFFilter:
    """ETF/ETN/레버리지 필터 테스트."""

    @pytest.fixture(autouse=True)
    def _reset_blocklist_cache(self) -> None:
        """테스트 간 블록리스트 캐시를 초기화한다."""
        ScreeningFilter._ETF_BLOCKLIST = None

    def test_is_etf_etn_filters_kodex(self) -> None:
        """KODEX ETF 종목이 필터링된다."""
        assert ScreeningFilter._is_etf_etn("252670", "KODEX 200선물인버스2X")

    def test_is_etf_etn_filters_tiger(self) -> None:
        """TIGER ETF 종목이 필터링된다."""
        assert ScreeningFilter._is_etf_etn("102110", "TIGER 200")

    def test_is_etf_etn_filters_etn_code(self) -> None:
        """Q로 시작하는 ETN 코드가 필터링된다."""
        assert ScreeningFilter._is_etf_etn("Q530036", "삼성 인버스 2X WTI원유 선물 ETN")

    def test_is_etf_etn_filters_leverage(self) -> None:
        """레버리지/인버스 키워드가 필터링된다."""
        assert ScreeningFilter._is_etf_etn("123456", "테스트 레버리지 종목")
        assert ScreeningFilter._is_etf_etn("123456", "테스트 인버스 종목")

    def test_is_etf_etn_passes_normal_stock(self) -> None:
        """일반 종목(삼성전자 등)은 통과한다."""
        assert not ScreeningFilter._is_etf_etn("005930", "삼성전자")
        assert not ScreeningFilter._is_etf_etn("000660", "SK하이닉스")

    def test_is_etf_etn_filters_blocklist_code(self) -> None:
        """블록리스트에 있는 ETF 코드가 필터링된다."""
        assert ScreeningFilter._is_etf_etn("252670", "알수없는종목")

    def test_is_etf_etn_filters_rise_bond_mixed(self) -> None:
        """RISE 채권혼합형 ETF가 필터링된다 (2026-06-01 실전 누수 회귀 방지)."""
        assert ScreeningFilter._is_etf_etn("0162Z0", "RISE 삼성전자SK하이닉스채권혼합50")

    def test_is_etf_etn_filters_nonnumeric_code(self) -> None:
        """6자리 숫자가 아닌 코드(ETN/ELW/구조화상품)는 일반주가 아니므로 필터링된다."""
        assert ScreeningFilter._is_etf_etn("0162Z0", "아무이름")
        assert ScreeningFilter._is_etf_etn("580099K", "구조화상품")

    def test_is_etf_etn_filters_rise_numeric_code(self) -> None:
        """숫자 코드의 RISE ETF도 브랜드 키워드로 필터링된다."""
        assert ScreeningFilter._is_etf_etn("123450", "RISE 200")

    def test_is_etf_etn_filters_bond_mixed_keyword(self) -> None:
        """채권혼합/ETF 키워드가 필터링된다."""
        assert ScreeningFilter._is_etf_etn("123450", "한투 채권혼합형")
        assert ScreeningFilter._is_etf_etn("123450", "아무 ETF")
        assert ScreeningFilter._is_etf_etn("069500", "알수없는종목")

    def test_is_etf_etn_filters_name_equals_code(self) -> None:
        """stock_name이 stock_code와 동일하면 필터링된다."""
        assert ScreeningFilter._is_etf_etn("252670", "252670")

    def test_is_etf_etn_filters_empty_name(self) -> None:
        """stock_name이 빈 문자열이면 필터링된다."""
        assert ScreeningFilter._is_etf_etn("123456", "")

    def test_screening_excludes_etf(self) -> None:
        """스크리닝 결과에서 ETF가 제외된다."""
        f = ScreeningFilter(config=_config())
        items = [
            _item(code="005930", name="삼성전자"),
            _item(code="252670", name="KODEX 200선물인버스2X"),
            _item(code="Q530036", name="삼성 인버스 2X WTI원유 선물 ETN"),
        ]
        result = f.apply(items, exclude_codes=set())
        assert len(result) == 1
        assert result[0].stock_code == "005930"
