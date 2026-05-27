"""공시 기반 매수 리스크 게이트 테스트.

KIS 종목마스터(market_actions) sync가 놓치는 종목을 DART 공시로 보완 차단한다.
최근 N일 내 해당 종목의 DISCLOSURE 공시 제목에 치명 키워드(상장폐지/정리매매/관리종목/
회생절차/감사의견거절/횡령/배임/부도/영업정지)가 있으면 매수를 차단한다(모델 미사용).
매도(청산)는 영향받지 않는다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine import TradingEngine
from src.utils.exceptions import OrderError


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._holding_quantity = AsyncMock(return_value=0)  # type: ignore[method-assign]
    engine._suppress_or_replace_pending = AsyncMock(return_value=False)  # type: ignore[method-assign]
    engine._record_order_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_trade_to_db = MagicMock()  # type: ignore[method-assign]
    engine._record_metric = MagicMock()  # type: ignore[method-assign]
    return engine


# ── 순수 키워드 매처 ──────────────────────────────────

def test_match_blocks_delisting_and_liquidation() -> None:
    """상장폐지/정리매매 제목은 차단 사유로 잡힌다(230980 실제 케이스)."""
    titles = ["주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)"]
    assert TradingEngine._match_critical_disclosure(titles) == titles[0]


def test_match_blocks_embezzlement() -> None:
    """횡령·배임 제목 차단."""
    assert TradingEngine._match_critical_disclosure(["횡령ㆍ배임혐의발생"]) is not None


def test_match_ignores_trading_resume_only() -> None:
    """치명 키워드 없는 '거래정지해제'(거래 재개=호재)만 있으면 차단하지 않는다."""
    assert TradingEngine._match_critical_disclosure(["주권매매거래정지해제"]) is None


def test_match_ignores_normal_disclosure() -> None:
    """일반 호재 공시(공급계약 등)는 차단하지 않는다."""
    assert TradingEngine._match_critical_disclosure(["단일판매ㆍ공급계약체결"]) is None


def test_match_empty() -> None:
    assert TradingEngine._match_critical_disclosure([]) is None


# ── _check_disclosure_risk_block (설정/조회) ──────────

def test_gate_disabled_short_circuits() -> None:
    """게이트 비활성 시 DB 조회 없이 None."""
    engine = _make_engine()
    with patch("src.engine.settings") as s, \
         patch("src.engine.get_session") as gs, \
         patch("src.engine.NewsChunkRepository") as repo:
        s.trading.news_risk_gate_enabled = False
        result = engine._check_disclosure_risk_block("230980")
    assert result is None
    gs.assert_not_called()
    repo.assert_not_called()


def test_gate_enabled_returns_matched_title() -> None:
    """게이트 활성 + 치명 공시 존재 시 제목 반환."""
    engine = _make_engine()
    with patch("src.engine.settings") as s, \
         patch("src.engine.get_session"), \
         patch("src.engine.NewsChunkRepository") as repo_cls:
        s.trading.news_risk_gate_enabled = True
        s.trading.news_risk_lookback_days = 30
        repo_cls.return_value.get_recent_disclosure_titles.return_value = [
            "주권매매거래정지 (상장폐지 사유발생)",
        ]
        result = engine._check_disclosure_risk_block("464680")
    assert result is not None and "상장폐지" in result


def test_gate_swallows_db_error() -> None:
    """조회 실패는 매매를 막지 않도록 None(통과)."""
    engine = _make_engine()
    with patch("src.engine.settings") as s, \
         patch("src.engine.get_session", side_effect=Exception("db down")):
        s.trading.news_risk_gate_enabled = True
        s.trading.news_risk_lookback_days = 30
        assert engine._check_disclosure_risk_block("005930") is None


# ── _execute_buy 게이트 동작 ──────────────────────────

@pytest.mark.asyncio
async def test_buy_blocked_by_disclosure_risk() -> None:
    """치명 공시 감지 시 주문을 내지 않고 BUY_DISCLOSURE_BLOCK 기록."""
    engine = _make_engine()
    engine._order.buy = AsyncMock()  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_check_disclosure_risk_block",
                      return_value="주권매매거래정지 (상장폐지 사유발생)"):
        await engine._execute_buy("464680", "테스트종목", 100, 4000)

    engine._order.buy.assert_not_awaited()
    engine._record_trade_to_db.assert_not_called()
    metric_types = [c.args[0] for c in engine._record_metric.call_args_list]
    assert "BUY_DISCLOSURE_BLOCK" in metric_types


@pytest.mark.asyncio
async def test_buy_proceeds_when_no_disclosure_risk() -> None:
    """공시 리스크 없으면 게이트 통과 — 주문 단계까지 진행(이후 실패는 무관)."""
    engine = _make_engine()
    # 게이트 통과 입증용: 주문 단계 도달 여부만 확인하기 위해 buy를 즉시 예외 처리
    engine._order.buy = AsyncMock(side_effect=OrderError("기타 실패", rt_cd="1"))  # type: ignore[method-assign]
    with patch.object(engine, "_check_market_action_block", return_value=[]), \
         patch.object(engine, "_check_disclosure_risk_block", return_value=None):
        await engine._execute_buy("005930", "삼성전자", 10, 70000)

    engine._order.buy.assert_awaited_once()
    metric_types = [c.args[0] for c in engine._record_metric.call_args_list]
    assert "BUY_DISCLOSURE_BLOCK" not in metric_types
