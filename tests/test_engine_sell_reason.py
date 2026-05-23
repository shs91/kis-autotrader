"""엔진 매도 기록 시 sell_reason ↔ 실현 PL 부호 보정(layer 1) 테스트.

proposal 2026-05-23: 게이트는 조회 시점 시세로 sell_reason을 정하지만 PL은
체결가로 계산된다. 시세 stale 시 STOP_LOSS 라벨에 양수 PL이 붙는 anomaly를
큐 적재 직전에 보정한다.
"""

from __future__ import annotations

from unittest.mock import patch

from src.db.models import TradeType
from tests.test_engine_buy_gate_metric import _make_engine


def _extract_record_trade(mock_enqueue) -> dict:  # type: ignore[no-untyped-def]
    """enqueue mock에서 record_trade payload를 추출."""
    for call in mock_enqueue.call_args_list:
        if call.kwargs.get("task_type") == "record_trade":
            return call.kwargs["payload"]
    raise AssertionError("record_trade 큐 적재 없음")


def _extract_metric(mock_enqueue, metric_type: str) -> list[dict]:  # type: ignore[no-untyped-def]
    out = []
    for call in mock_enqueue.call_args_list:
        if call.kwargs.get("task_type") != "record_metric":
            continue
        payload = call.kwargs.get("payload") or {}
        if payload.get("metric_type") == metric_type:
            out.append(payload)
    return out


class TestSellReasonReconciliation:
    """``_record_trade_to_db``의 sell_reason 보정 검증."""

    def test_stop_loss_with_profit_relabeled(self) -> None:
        """손절 게이트로 결정됐으나 체결 PL이 양수면 TAKE_PROFIT으로 기록."""
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            # 매입가 3565, 체결가 4226 → PL +18.54% (760027 시나리오)
            engine._record_trade_to_db(
                "760027", "키움 인버스 ETN", TradeType.SELL,
                quantity=942, price=4226, reason="손절", avg_price=3565.0,
            )
            payload = _extract_record_trade(mock_enqueue)
            assert payload["sell_reason"] == "TAKE_PROFIT"
            assert payload["profit_loss_pct"] > 0
            corrected = _extract_metric(mock_enqueue, "SELL_REASON_CORRECTED")
            assert len(corrected) == 1
            assert corrected[0]["detail"]["from"] == "STOP_LOSS"
            assert corrected[0]["detail"]["to"] == "TAKE_PROFIT"

    def test_take_profit_with_loss_relabeled(self) -> None:
        """익절 게이트로 결정됐으나 체결 PL이 음수면 STOP_LOSS로 기록."""
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_trade_to_db(
                "005930", "삼성전자", TradeType.SELL,
                quantity=10, price=68000, reason="익절", avg_price=70000.0,
            )
            payload = _extract_record_trade(mock_enqueue)
            assert payload["sell_reason"] == "STOP_LOSS"
            assert payload["profit_loss_pct"] < 0

    def test_consistent_stop_loss_unchanged(self) -> None:
        """정상 손절(PL<0)은 그대로 STOP_LOSS, 보정 메트릭 없음."""
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_trade_to_db(
                "005930", "삼성전자", TradeType.SELL,
                quantity=10, price=67900, reason="손절", avg_price=70000.0,
            )
            payload = _extract_record_trade(mock_enqueue)
            assert payload["sell_reason"] == "STOP_LOSS"
            assert _extract_metric(mock_enqueue, "SELL_REASON_CORRECTED") == []

    def test_trailing_stop_with_profit_unchanged(self) -> None:
        """트레일링은 PL 부호와 무관하게 TRAILING_STOP 유지."""
        engine = _make_engine()
        with patch.object(engine._task_queue, "enqueue") as mock_enqueue:
            engine._record_trade_to_db(
                "005930", "삼성전자", TradeType.SELL,
                quantity=10, price=72000, reason="트레일링", avg_price=70000.0,
            )
            payload = _extract_record_trade(mock_enqueue)
            assert payload["sell_reason"] == "TRAILING_STOP"
            assert _extract_metric(mock_enqueue, "SELL_REASON_CORRECTED") == []
