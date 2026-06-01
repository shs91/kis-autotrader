"""``src.scheduler.jobs`` 단위 테스트.

장중 매매 사이클 간격 산출(``_calculate_trading_interval``)의 하한 적용을 검증한다.
스크리닝 의존(WATCHLIST 비움)으로 셋업 시 0종목이면 1초 폭주가 발생하던 회귀를
방지한다 — 0종목/소수 종목 모두 설정 하한(기본 10초)을 따라야 한다.
"""

from __future__ import annotations

import types

import pytest

from src.scheduler import jobs


def _fake_settings(per_second: int = 20, min_interval: float = 10.0) -> types.SimpleNamespace:
    """``_calculate_trading_interval``이 참조하는 settings 최소 스텁."""
    return types.SimpleNamespace(
        rate_limit=types.SimpleNamespace(per_second=per_second),
        trading=types.SimpleNamespace(min_trading_interval_seconds=min_interval),
    )


@pytest.mark.parametrize("stock_count", [0, -1])
def test_zero_or_negative_stock_count_uses_min_interval(
    monkeypatch: pytest.MonkeyPatch, stock_count: int
) -> None:
    """종목 미확정(0/음수) 시 1초가 아니라 설정 하한을 반환해야 한다(회귀 방지)."""
    monkeypatch.setattr(jobs, "settings", _fake_settings(per_second=20, min_interval=10.0))
    assert jobs._calculate_trading_interval(stock_count) == 10.0


def test_small_stock_count_is_floored_to_min_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """소수 종목(산출값<하한)은 하한으로 바닥이 받쳐져야 한다."""
    monkeypatch.setattr(jobs, "settings", _fake_settings(per_second=20, min_interval=10.0))
    # 5종목: (5*2+1)/20*1.2 = 0.66 → 하한 10초로 상향
    assert jobs._calculate_trading_interval(5) == 10.0


def test_large_stock_count_exceeds_min_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """종목이 많아 산출값이 하한을 넘으면 산출값을 그대로 사용한다."""
    monkeypatch.setattr(jobs, "settings", _fake_settings(per_second=20, min_interval=10.0))
    # 100종목: (100*2+1)/20*1.2 = 12.06 → ceil(120.6)/10 = 12.1
    assert jobs._calculate_trading_interval(100) == pytest.approx(12.1)


def test_min_interval_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """하한은 설정값(TRADING_MIN_INTERVAL_SECONDS)으로 조절된다."""
    monkeypatch.setattr(jobs, "settings", _fake_settings(per_second=20, min_interval=5.0))
    assert jobs._calculate_trading_interval(0) == 5.0
    # 5종목 산출값(0.66)은 여전히 하한(5초) 미만 → 5초
    assert jobs._calculate_trading_interval(5) == 5.0
