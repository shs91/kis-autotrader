"""매매 전략 추상 클래스 정의."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class SignalType(Enum):
    """매매 시그널 유형."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    """매매 시그널 데이터 클래스.

    Attributes:
        signal_type: 시그널 유형 (BUY/SELL/HOLD)
        confidence: 시그널 신뢰도 (0.0 ~ 1.0)
        target_price: 목표가
        stop_loss_price: 손절가
        reason: 시그널 발생 근거
    """

    signal_type: SignalType
    confidence: float
    target_price: float | None = None
    stop_loss_price: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        """신뢰도 값의 유효성을 검증한다."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"신뢰도는 0.0에서 1.0 사이여야 합니다: {self.confidence}"
            )


class BaseStrategy(ABC):
    """매매 전략 추상 클래스.

    모든 매매 전략은 이 클래스를 상속하여 구현한다.
    시세 데이터를 pandas DataFrame으로 전달받아 분석 후
    매매 시그널을 반환한다.
    """

    @abstractmethod
    def analyze(self, market_data: pd.DataFrame) -> Signal:
        """시장 데이터를 분석하여 매매 시그널을 생성한다.

        Args:
            market_data: 시장 데이터 DataFrame

        Returns:
            매매 시그널
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """전략 이름을 반환한다."""
        ...
