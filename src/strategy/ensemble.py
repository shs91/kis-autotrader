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
        """투표 집계 상세를 meta dict로 구성한다."""
        return {
            "method": self._method,
            "votes": [
                {
                    "strategy": s.name,
                    "action": sig.signal_type.value,
                    "confidence": round(sig.confidence, 4),
                }
                for s, sig in zip(self._strategies, signals)
            ],
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
        """가중 투표를 수행한다."""
        buy_w = sum(s.confidence for s in signals if s.signal_type == SignalType.BUY)
        sell_w = sum(s.confidence for s in signals if s.signal_type == SignalType.SELL)

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
        else:
            winner_type = SignalType.SELL
            winner_weight, loser_weight = sell_w, buy_w

        confidence = winner_weight / len(signals)
        return Signal(
            signal_type=winner_type,
            confidence=min(confidence, 1.0),
            reason=(
                f"앙상블 가중투표: {winner_type.value} "
                f"{winner_weight:.2f} vs {loser_weight:.2f}"
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
