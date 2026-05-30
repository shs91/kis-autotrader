"""단기 신호 반전 관측(SIGNAL_REVERSAL) 테스트 (proposal 2026-05-30).

동일 종목의 직전 BUY/SELL 신호를 인메모리로 기억하고, 새 신호가 직전과 반대 방향이며
설정 윈도(기본 600초) 이내이면 ``SIGNAL_REVERSAL`` 메트릭을 1건 적재한다.
순수 관측 경로이며 매매 동작은 변경하지 않는다. HOLD는 반전 판정·기억 모두에서 제외된다.

기존 ``tests/test_engine_untradable_blacklist.py``의 엔진 인스턴스 구성 패턴을 따른다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine import TradingEngine
from src.strategy.base import Signal, SignalType


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._record_metric = MagicMock()  # type: ignore[method-assign]
    return engine


def _signal(signal_type: SignalType, confidence: float = 0.7) -> Signal:
    return Signal(signal_type=signal_type, confidence=confidence)


def _reversals(engine: TradingEngine) -> list[dict]:
    """기록된 SIGNAL_REVERSAL 메트릭 detail 목록."""
    out: list[dict] = []
    for call in engine._record_metric.call_args_list:  # type: ignore[attr-defined]
        if call.args and call.args[0] == "SIGNAL_REVERSAL":
            out.append(call.args[1] if len(call.args) > 1 else {})
    return out


def _seed_prev(
    engine: TradingEngine, stock_code: str, signal_type: SignalType,
    confidence: float, seconds_ago: float,
) -> None:
    """직전 신호 상태를 지정 시각으로 주입한다."""
    prev_time = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    engine._last_signal_by_stock[stock_code] = (signal_type, confidence, prev_time)


# 1. BUY→SELL, 윈도 이내 → 1건 기록 + detail 검증
def test_reversal_within_window_records_metric() -> None:
    engine = _make_engine()
    _seed_prev(engine, "062970", SignalType.BUY, 0.8, seconds_ago=42)
    with patch("src.engine.settings") as s:
        s.trading.signal_reversal_window_seconds = 600
        engine._observe_signal_reversal("062970", _signal(SignalType.SELL, 0.65))

    revs = _reversals(engine)
    assert len(revs) == 1
    d = revs[0]
    assert d["stock_code"] == "062970"
    assert d["prev_type"] == "BUY"
    assert d["new_type"] == "SELL"
    assert d["prev_confidence"] == 0.8
    assert d["new_confidence"] == 0.65
    assert 41.0 <= d["gap_seconds"] <= 60.0


# 2. BUY→SELL, 윈도 초과(gap > window) → 미기록
def test_reversal_beyond_window_not_recorded() -> None:
    engine = _make_engine()
    _seed_prev(engine, "062970", SignalType.BUY, 0.8, seconds_ago=900)
    with patch("src.engine.settings") as s:
        s.trading.signal_reversal_window_seconds = 600
        engine._observe_signal_reversal("062970", _signal(SignalType.SELL))

    assert _reversals(engine) == []
    # 직전 신호 상태는 새 신호로 갱신된다(반전 미기록이어도 기억은 유지)
    assert engine._last_signal_by_stock["062970"][0] == SignalType.SELL


# 3. BUY→BUY(동일 방향) → 미기록
def test_same_direction_not_recorded() -> None:
    engine = _make_engine()
    _seed_prev(engine, "005930", SignalType.BUY, 0.7, seconds_ago=30)
    with patch("src.engine.settings") as s:
        s.trading.signal_reversal_window_seconds = 600
        engine._observe_signal_reversal("005930", _signal(SignalType.BUY, 0.9))

    assert _reversals(engine) == []
    assert engine._last_signal_by_stock["005930"][0] == SignalType.BUY


# 4. 다른 종목 신호 → 미기록(상태 분리)
def test_different_stock_state_isolated() -> None:
    engine = _make_engine()
    _seed_prev(engine, "062970", SignalType.BUY, 0.8, seconds_ago=30)
    with patch("src.engine.settings") as s:
        s.trading.signal_reversal_window_seconds = 600
        # 다른 종목의 SELL은 062970의 직전 BUY와 비교되지 않는다
        engine._observe_signal_reversal("005930", _signal(SignalType.SELL))

    assert _reversals(engine) == []
    # 062970 상태는 손대지 않고, 005930만 새로 기억
    assert engine._last_signal_by_stock["062970"][0] == SignalType.BUY
    assert engine._last_signal_by_stock["005930"][0] == SignalType.SELL


# 5. HOLD는 비교·기억 대상에서 제외
def test_hold_excluded_from_compare_and_memory() -> None:
    engine = _make_engine()
    _seed_prev(engine, "062970", SignalType.BUY, 0.8, seconds_ago=30)
    with patch("src.engine.settings") as s:
        s.trading.signal_reversal_window_seconds = 600
        # HOLD는 무행동 — 직전 BUY가 있어도 반전 미기록
        engine._observe_signal_reversal("062970", _signal(SignalType.HOLD, 0.0))

    assert _reversals(engine) == []
    # HOLD로는 상태를 갱신하지 않는다(직전 BUY 그대로 유지)
    assert engine._last_signal_by_stock["062970"][0] == SignalType.BUY


# 6. pre_market(일자 변경) 후 _last_signal_by_stock 비워짐
@pytest.mark.asyncio
async def test_pre_market_clears_last_signal_state() -> None:
    """거래일이 바뀌면(pre_market) 직전 신호 상태가 초기화된다.

    리셋은 외부 I/O(토큰/스크리닝) 이전 동기 구간에서 일어난다. 토큰 조회를 실패시켜
    이후 본문을 단락시키되(pre_market은 내부에서 예외를 삼킴) 리셋 결과만 검증한다.
    """
    engine = _make_engine()
    _seed_prev(engine, "062970", SignalType.BUY, 0.8, seconds_ago=10)
    engine._client._auth.get_access_token = AsyncMock(  # type: ignore[attr-defined]
        side_effect=Exception("stop after resets")
    )
    with patch.object(engine, "_load_peak_prices", return_value={}):
        await engine.pre_market()

    assert engine._last_signal_by_stock == {}


# (보강) 직전 신호가 없으면 미기록, 상태만 기억
def test_first_signal_only_remembers() -> None:
    engine = _make_engine()
    with patch("src.engine.settings") as s:
        s.trading.signal_reversal_window_seconds = 600
        engine._observe_signal_reversal("005930", _signal(SignalType.BUY, 0.7))

    assert _reversals(engine) == []
    assert engine._last_signal_by_stock["005930"][0] == SignalType.BUY
