"""앙상블 전략 — 복수 전략의 시그널을 투표로 통합한다."""

from __future__ import annotations

import pandas as pd

from src.strategy.base import BaseStrategy, Signal, SignalType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

MAJORITY: str = "majority"
WEIGHTED: str = "weighted"
PERFORMANCE: str = "performance"


class EnsembleStrategy(BaseStrategy):
    """복수 전략의 시그널을 투표로 통합하는 앙상블 전략."""

    def __init__(
        self,
        strategies: list[BaseStrategy],
        method: str = MAJORITY,
        strategy_weights: dict[str, float] | None = None,
    ) -> None:
        """앙상블 전략을 초기화한다.

        Args:
            strategies: 하위 전략 목록 (최소 2개)
            method: 투표 방식 ("majority", "weighted", "performance")
            strategy_weights: 전략별 가중치 (performance 모드 시).
                키는 전략 name, 값은 0.0~1.0 승률. None이면 동일 가중치.

        Raises:
            ValueError: strategies가 2개 미만이거나 method가 올바르지 않을 때
        """
        if len(strategies) < 2:
            raise ValueError("앙상블 전략은 최소 2개의 하위 전략이 필요합니다.")
        if method not in (MAJORITY, WEIGHTED, PERFORMANCE):
            raise ValueError(f"지원하지 않는 투표 방식입니다: {method}")
        self._strategies = strategies
        self._method = method
        self._strategy_weights = strategy_weights or {}

    @property
    def name(self) -> str:
        """앙상블 전략 이름을 반환한다."""
        names = "+".join(s.name for s in self._strategies)
        return f"앙상블({names})"

    def update_weights(self, weights: dict[str, float]) -> None:
        """전략별 성과 가중치를 업데이트한다.

        Args:
            weights: {전략명: 승률(0.0~1.0)} 딕셔너리
        """
        self._strategy_weights = weights
        logger.info("앙상블 가중치 업데이트: %s", weights)

    def _build_vote_meta(self, signals: list[Signal]) -> dict[str, object]:
        """투표 집계 상세를 meta dict로 구성한다.

        각 하위 전략의 ``Signal.meta``(series_len·nan_ratio·last_value·
        guard_triggered 등 관측 필드)를 vote 항목에 병합하여, 전원
        ``confidence=0`` HOLD로 수렴할 때 어느 단계에서 방어 분기에
        진입했는지 데이터로 추적할 수 있도록 한다. 기존 shape
        ``{strategy, action, confidence}``는 유지하고, 서브 meta 키만
        append한다.
        """
        votes: list[dict[str, object]] = []
        for s, sig in zip(self._strategies, signals):
            vote: dict[str, object] = {
                "strategy": s.name,
                "action": sig.signal_type.value,
                "confidence": round(sig.confidence, 4),
            }
            if sig.meta:
                # 기존 키(strategy/action/confidence)는 sub-meta에 의해
                # 덮어쓰이지 않도록 보호한다.
                for k, v in sig.meta.items():
                    if k not in vote:
                        vote[k] = v
            votes.append(vote)
        return {
            "method": self._method,
            "votes": votes,
        }

    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """모든 하위 전략의 시그널을 수집하여 투표로 결정한다."""
        signals = [s.analyze(market_data) for s in self._strategies]
        if self._method == MAJORITY:
            result = self._majority_vote(signals)
        elif self._method == PERFORMANCE:
            result = self._performance_vote(signals)
        else:
            result = self._weighted_vote(signals)
        if result.signal_type == SignalType.HOLD:
            result.meta = self._build_vote_meta(signals)
        return result

    def _majority_vote(self, signals: list[Signal]) -> Signal:
        """다수결 투표를 수행한다."""
        non_hold = [
            (s, i) for i, s in enumerate(signals) if s.signal_type != SignalType.HOLD
        ]
        if not non_hold:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블: 모든 전략 HOLD",
            )

        counts: dict[SignalType, list[Signal]] = {}
        for sig, _idx in non_hold:
            counts.setdefault(sig.signal_type, []).append(sig)

        buy_sigs = counts.get(SignalType.BUY, [])
        sell_sigs = counts.get(SignalType.SELL, [])

        if len(buy_sigs) == len(sell_sigs):
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블 다수결: 동수 → HOLD",
            )

        if len(buy_sigs) > len(sell_sigs):
            winner_type = SignalType.BUY
            winner_sigs = buy_sigs
        else:
            winner_type = SignalType.SELL
            winner_sigs = sell_sigs

        avg_conf = sum(s.confidence for s in winner_sigs) / len(winner_sigs)
        total = len(non_hold)
        return Signal(
            signal_type=winner_type,
            confidence=avg_conf,
            reason=f"앙상블 다수결: {winner_type.value} {len(winner_sigs)}/{total}",
        )

    def _weighted_vote(self, signals: list[Signal]) -> Signal:
        """가중 투표를 수행한다.

        HOLD는 기권으로 보아 신뢰도를 희석하지 않는다. 승자 방향에 최소 2개
        전략이 동의(``n_win >= 2``)해야 매매로 전환한다(단독표 억제). 신뢰도는
        승자 평균 강도(base)와 승자 우세도(opp)의 곱으로 산출한다.

            base = W / n_win,  opp = W / (W + L),  conf = min(base * opp, 1.0)

        여기서 W=승자 가중치 합, L=패자 가중치 합, n_win=승자 방향 투표 수.
        """
        hold_count = sum(1 for s in signals if s.signal_type == SignalType.HOLD)
        if hold_count > len(signals) * 3 / 4:
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason=f"앙상블 가중투표: HOLD 대다수 ({hold_count}/{len(signals)})",
            )

        buy_sigs = [s for s in signals if s.signal_type == SignalType.BUY]
        sell_sigs = [s for s in signals if s.signal_type == SignalType.SELL]
        buy_w = sum(s.confidence for s in buy_sigs)
        sell_w = sum(s.confidence for s in sell_sigs)

        if buy_w == 0.0 and sell_w == 0.0:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블: 모든 전략 HOLD",
            )

        if buy_w == sell_w:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블 가중투표: 동수 → HOLD",
            )

        if buy_w > sell_w:
            winner_type = SignalType.BUY
            winner_weight, loser_weight = buy_w, sell_w
            n_win = len(buy_sigs)
        else:
            winner_type = SignalType.SELL
            winner_weight, loser_weight = sell_w, buy_w
            n_win = len(sell_sigs)

        # 단독표 억제: 승자 방향 동의가 2개 미만이면 매매 전환하지 않음
        if n_win < 2:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason=f"앙상블 가중투표: 승자표 부족 (n_win={n_win}) → HOLD",
            )

        base = winner_weight / n_win
        opp = winner_weight / (winner_weight + loser_weight)
        confidence = min(base * opp, 1.0)
        return Signal(
            signal_type=winner_type,
            confidence=confidence,
            reason=(
                f"앙상블 가중투표: {winner_type.value} n_win={n_win} "
                f"W={winner_weight:.2f} L={loser_weight:.2f} "
                f"(base={base:.2f}×opp={opp:.2f})"
            ),
        )

    def _performance_vote(self, signals: list[Signal]) -> Signal:
        """성과 기반 가중 투표를 수행한다.

        각 전략의 과거 승률을 가중치로 사용한다.
        승률이 높은 전략의 시그널에 더 큰 비중을 부여한다.
        """
        buy_w = 0.0
        sell_w = 0.0
        for strategy, signal in zip(self._strategies, signals):
            weight = self._strategy_weights.get(strategy.name, 0.5)
            if signal.signal_type == SignalType.BUY:
                buy_w += signal.confidence * weight
            elif signal.signal_type == SignalType.SELL:
                sell_w += signal.confidence * weight

        if buy_w == 0.0 and sell_w == 0.0:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블 성과기반: 모든 전략 HOLD",
            )

        if buy_w == sell_w:
            return Signal(
                signal_type=SignalType.HOLD, confidence=0.0,
                reason="앙상블 성과기반: 동수 → HOLD",
            )

        if buy_w > sell_w:
            winner_type = SignalType.BUY
            winner_weight, loser_weight = buy_w, sell_w
        else:
            winner_type = SignalType.SELL
            winner_weight, loser_weight = sell_w, buy_w

        total_w = winner_weight + loser_weight
        confidence = winner_weight / total_w if total_w > 0 else 0.0
        return Signal(
            signal_type=winner_type,
            confidence=min(confidence, 1.0),
            reason=(
                f"앙상블 성과기반: {winner_type.value} "
                f"{winner_weight:.2f} vs {loser_weight:.2f}"
            ),
        )
