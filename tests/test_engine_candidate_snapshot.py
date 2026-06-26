"""엔진 미보유 후보종목 스냅샷 enqueue 테스트 (shadow 검증)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from src.engine import TradingEngine
from src.market.profile import US_PROFILE
from src.strategy.base import Signal, SignalType


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), \
         patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), \
         patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), \
         patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        return TradingEngine(watchlist=["005930"])


def test_enqueue_candidate_snapshot_payload() -> None:
    engine = _make_engine()
    signal = Signal(signal_type=SignalType.BUY, confidence=0.65, reason="MA cross")
    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_candidate_snapshot("005930", "KRX", 70123.0, signal)

    mock_enq.assert_called_once()
    kwargs = mock_enq.call_args.kwargs
    assert kwargs["task_type"] == "candidate_snapshot"
    assert kwargs["priority"] == 0  # 최저 우선순위 회귀 가드
    payload = kwargs["payload"]
    assert payload["stock_code"] == "005930"
    assert payload["market"] == "KRX"
    assert payload["price"] == 70123  # KRX 정수 정규화
    assert payload["ensemble_action"] == "BUY"
    assert payload["ensemble_confidence"] == 0.65
    assert payload["ensemble_reason"] == "MA cross"


def test_enqueue_candidate_snapshot_empty_reason_becomes_none() -> None:
    """빈 reason은 None으로 정규화되어 적재된다."""
    engine = _make_engine()
    signal = Signal(signal_type=SignalType.HOLD, confidence=0.0, reason="")
    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_candidate_snapshot("005930", "KRX", 70000.0, signal)

    payload = mock_enq.call_args.kwargs["payload"]
    assert payload["ensemble_action"] == "HOLD"
    assert payload["ensemble_reason"] is None


def test_enqueue_candidate_snapshot_ignores_none_return() -> None:
    """enqueue가 None을 반환해도(큐 가득참 등) 헬퍼는 정상 반환해야 한다."""
    engine = _make_engine()
    signal = Signal(signal_type=SignalType.BUY, confidence=0.5)
    with patch.object(engine._task_queue, "enqueue", return_value=None) as mock_enq:
        result = engine._enqueue_candidate_snapshot("005930", "KRX", 70123.0, signal)
    assert result is None
    mock_enq.assert_called_once()


def test_enqueue_candidate_snapshot_us_normalization() -> None:
    """US 프로파일에서 소수점 2자리 보존·시장 필드 검증."""
    engine = _make_engine()
    engine._market = US_PROFILE  # KRX → US 교체
    signal = Signal(signal_type=SignalType.SELL, confidence=0.8, reason="rsi")

    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_candidate_snapshot("AAPL", "US", 123.456, signal)

    payload = mock_enq.call_args.kwargs["payload"]
    assert payload["stock_code"] == "AAPL"
    assert payload["market"] == "US"
    assert payload["price"] == 123.46  # 소수점 2자리 HALF_UP 반올림
    assert payload["ensemble_action"] == "SELL"


def test_enqueue_candidate_snapshot_throttled_per_stock() -> None:
    """종목당 최소 간격 내 중복 호출은 enqueue를 생략한다(볼륨 억제)."""
    engine = _make_engine()
    signal = Signal(signal_type=SignalType.HOLD, confidence=0.1, reason="x")
    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        # 1회차: 첫 적재 → enqueue
        engine._enqueue_candidate_snapshot("005930", "KRX", 70000.0, signal)
        # 2회차(즉시, 간격 내): throttle → 생략
        engine._enqueue_candidate_snapshot("005930", "KRX", 70100.0, signal)
        assert mock_enq.call_count == 1
        # 다른 종목은 독립적으로 적재
        engine._enqueue_candidate_snapshot("000660", "KRX", 120000.0, signal)
        assert mock_enq.call_count == 2
        # 간격 경과 후(last를 과거로 되돌림) → 재적재
        engine._last_candidate_snapshot_at["005930"] = datetime.now(
            engine._tz
        ) - timedelta(seconds=61)
        engine._enqueue_candidate_snapshot("005930", "KRX", 70200.0, signal)
        assert mock_enq.call_count == 3
