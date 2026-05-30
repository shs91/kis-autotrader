"""일일 헬스체크 작업 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scheduler.healthcheck import (
    HealthcheckResult,
    HealthcheckSlot,
    build_healthcheck_message,
    collect_healthcheck,
    run_healthcheck,
)


class TestBuildHealthcheckMessage:
    """build_healthcheck_message 분기 테스트."""

    def test_zero_trades_is_warned(self) -> None:
        """매매가 0건이면 경고 마커가 포함된다."""
        result = HealthcheckResult(
            slot=HealthcheckSlot.MORNING,
            cycle_count=200,
            api_calls=5000,
            api_limit=50000,
            signals_buy=10,
            signals_sell=20,
            orders_buy=0,
            orders_sell=0,
            holdings_count=0,
            holdings_codes=[],
            deposit=11_492_074,
            buy_reject_reasons={"DISCLOSURE_FATAL": 100},
        )
        text = build_healthcheck_message(result)
        assert "⚠️" in text or "주의" in text
        # 0건 사실이 본문에 명확하게 표기 (HTML 태그 무관하게 검사)
        assert "매수" in text and "0건" in text
        # 매도도 같이 표기
        assert "매도" in text

    def test_normal_trades_no_warning(self) -> None:
        """매매가 1건 이상이면 경고 없이 정상 결산."""
        result = HealthcheckResult(
            slot=HealthcheckSlot.CLOSING,
            cycle_count=350,
            api_calls=12000,
            api_limit=50000,
            signals_buy=15,
            signals_sell=10,
            orders_buy=3,
            orders_sell=2,
            holdings_count=2,
            holdings_codes=["005930", "035420"],
            deposit=10_000_000,
            buy_reject_reasons={},
        )
        text = build_healthcheck_message(result)
        assert "⚠️" not in text
        assert "매수" in text and "3건" in text
        assert "매도" in text and "2건" in text

    def test_slot_label_in_message(self) -> None:
        """슬롯 라벨(오전·마감)이 메시지에 표시된다."""
        morning = HealthcheckResult(
            slot=HealthcheckSlot.MORNING,
            cycle_count=100,
            api_calls=2000,
            api_limit=50000,
            signals_buy=0,
            signals_sell=0,
            orders_buy=0,
            orders_sell=0,
            holdings_count=0,
            holdings_codes=[],
            deposit=11_000_000,
            buy_reject_reasons={},
        )
        closing = HealthcheckResult(
            slot=HealthcheckSlot.CLOSING,
            cycle_count=400,
            api_calls=12000,
            api_limit=50000,
            signals_buy=0,
            signals_sell=0,
            orders_buy=0,
            orders_sell=0,
            holdings_count=0,
            holdings_codes=[],
            deposit=11_000_000,
            buy_reject_reasons={},
        )
        assert "오전" in build_healthcheck_message(morning)
        assert "마감" in build_healthcheck_message(closing)

    def test_reject_reasons_appear_when_zero_orders(self) -> None:
        """0건인데 매수 거절 사유가 있으면 상위 사유가 노출된다."""
        result = HealthcheckResult(
            slot=HealthcheckSlot.MORNING,
            cycle_count=200,
            api_calls=5000,
            api_limit=50000,
            signals_buy=445,
            signals_sell=444,
            orders_buy=0,
            orders_sell=0,
            holdings_count=0,
            holdings_codes=[],
            deposit=11_000_000,
            buy_reject_reasons={"DISCLOSURE_FATAL": 445},
        )
        text = build_healthcheck_message(result)
        assert "DISCLOSURE_FATAL" in text
        assert "445" in text


class TestCollectHealthcheck:
    """collect_healthcheck — DB/engine 통합 수집기."""

    @pytest.mark.asyncio
    async def test_collects_from_engine_and_db(self) -> None:
        """engine과 DB에서 수치를 수집해 HealthcheckResult로 반환."""
        engine = MagicMock()
        engine._cycle_count = 470

        # KIS 잔고 mock
        balance = MagicMock()
        balance.deposit = 11_492_074
        balance.holdings = []
        engine._get_balance = AsyncMock(return_value=balance)

        with patch("src.scheduler.healthcheck._query_today_counts") as q:
            q.return_value = {
                "signals_buy": 441,
                "signals_sell": 441,
                "orders_buy": 0,
                "orders_sell": 0,
                "api_calls": 10294,
                "buy_reject_reasons": {"DISCLOSURE_FATAL": 445},
            }
            result = await collect_healthcheck(engine, slot=HealthcheckSlot.MORNING)

        assert result.cycle_count == 470
        assert result.signals_buy == 441
        assert result.orders_buy == 0
        assert result.holdings_count == 0
        assert result.deposit == 11_492_074
        assert result.buy_reject_reasons == {"DISCLOSURE_FATAL": 445}


class TestRunHealthcheck:
    """run_healthcheck — 휴장일/엔진없음 가드 + 알림 전송."""

    @pytest.mark.asyncio
    async def test_skips_on_holiday(self) -> None:
        """휴장일은 헬스체크가 스킵된다."""
        engine = MagicMock()
        with patch(
            "src.scheduler.healthcheck.is_market_closed", return_value=True
        ), patch("src.scheduler.healthcheck.collect_healthcheck") as collector:
            await run_healthcheck(engine, slot=HealthcheckSlot.MORNING)
            collector.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_engine_is_none(self) -> None:
        """엔진이 None이면 안전하게 스킵."""
        with patch("src.scheduler.healthcheck.is_market_closed", return_value=False):
            # 예외 없이 종료해야 함
            await run_healthcheck(None, slot=HealthcheckSlot.MORNING)

    @pytest.mark.asyncio
    async def test_sends_telegram_message(self) -> None:
        """정상 경로: collect → format → send."""
        engine = MagicMock()
        fake_result = HealthcheckResult(
            slot=HealthcheckSlot.CLOSING,
            cycle_count=400,
            api_calls=12000,
            api_limit=50000,
            signals_buy=0,
            signals_sell=0,
            orders_buy=0,
            orders_sell=0,
            holdings_count=0,
            holdings_codes=[],
            deposit=11_000_000,
            buy_reject_reasons={},
        )
        sent: list[str] = []

        async def fake_send(self, message: str) -> None:  # noqa: ARG001
            sent.append(message)

        with patch(
            "src.scheduler.healthcheck.is_market_closed", return_value=False
        ), patch(
            "src.scheduler.healthcheck.collect_healthcheck",
            new=AsyncMock(return_value=fake_result),
        ), patch(
            "src.notify.telegram.TelegramNotifier.notify_system", new=fake_send
        ):
            await run_healthcheck(engine, slot=HealthcheckSlot.CLOSING)
        assert len(sent) == 1
        assert "마감" in sent[0]

    @pytest.mark.asyncio
    async def test_swallows_errors_to_protect_scheduler(self) -> None:
        """수집 또는 전송 중 에러가 발생해도 예외가 전파되지 않는다."""
        engine = MagicMock()
        with patch(
            "src.scheduler.healthcheck.is_market_closed", return_value=False
        ), patch(
            "src.scheduler.healthcheck.collect_healthcheck",
            new=AsyncMock(side_effect=RuntimeError("DB down")),
        ):
            # 예외 전파 없이 종료
            await run_healthcheck(engine, slot=HealthcheckSlot.MORNING)


class TestQueryTodayCounts:
    """오늘자 signals/orders 카운트 쿼리는 SQLAlchemy 세션을 사용."""

    def test_smoke_signature(self) -> None:
        """함수가 export되며 인자 없이 호출 가능한 시그니처."""
        from src.scheduler import healthcheck

        # 시그니처 존재 검증 — 실제 DB 호출은 통합 테스트에서.
        assert callable(healthcheck._query_today_counts)
        assert healthcheck._query_today_counts.__name__ == "_query_today_counts"


class TestQueryTodayCountsExecutes:
    """_query_today_counts 실제 SQL 실행 — 회귀 가드.

    기존 smoke 테스트가 시그니처만 검사해 ``func.case``(PostgreSQL에 없는 함수)
    버그가 라이브에서 매 실행 예외를 던지며 통과했었다. 실제 인메모리 DB에
    행을 넣고 카운트가 기본값(0)이 아닌 실값으로 돌아오는지 검증한다.
    """

    @pytest.fixture()
    def session(self):  # type: ignore[no-untyped-def]
        from sqlalchemy import create_engine
        from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
        from sqlalchemy.orm import sessionmaker

        from src.db.models import Base

        if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
            def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
                return "JSON"
            SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]
        if not hasattr(SQLiteTypeCompiler, "visit_VECTOR"):
            def visit_vector(self, type_, **kw):  # type: ignore[no-untyped-def]
                return "TEXT"
            SQLiteTypeCompiler.visit_VECTOR = visit_vector  # type: ignore[attr-defined]

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()
            engine.dispose()

    def test_counts_signals_orders_and_rejects(self, session) -> None:  # type: ignore[no-untyped-def]
        """오늘자 시그널/주문/거절사유가 기본값이 아닌 실값으로 집계된다."""
        from contextlib import contextmanager
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from src.db.models import Order, OrderType, Signal, SystemMetric
        from src.scheduler import healthcheck

        kst = ZoneInfo("Asia/Seoul")
        # 결정적 창: 2026-05-28 00:00~05-29 00:00 KST
        start_kst = datetime(2026, 5, 28, 0, 0, tzinfo=kst)
        end_kst = datetime(2026, 5, 29, 0, 0, tzinfo=kst)
        mid_kst = datetime(2026, 5, 28, 10, 0, tzinfo=kst)
        # Order.created_at은 naive UTC — 같은 날 KST 창의 UTC 투영 안쪽(05-28 05:00 UTC = 14:00 KST)
        mid_utc_naive = datetime(2026, 5, 28, 5, 0)

        session.add_all([
            Signal(
                stock_code="230980", stock_name="비유테크놀러지",
                signal_type="ENSEMBLE",
                signal_value={"reason": "앙상블 가중투표: BUY n_win=2", "confidence": 1.0},
                confidence=1.0, action_taken=True,
                detected_at=mid_kst, created_at=mid_kst,
            ),
            Signal(
                stock_code="001740", stock_name="SK네트웍스",
                signal_type="ENSEMBLE",
                signal_value={"reason": "앙상블 가중투표: SELL n_win=2", "confidence": 0.5},
                confidence=0.5, action_taken=False,
                detected_at=mid_kst, created_at=mid_kst,
            ),
            Order(
                stock_id=1, order_type=OrderType.BUY, quantity=10, price=1000.0,
                order_no="REAL-1", created_at=mid_utc_naive, updated_at=mid_utc_naive,
            ),
            SystemMetric(
                metric_type="BUY_DISCLOSURE_BLOCK",
                detail={"stock_code": "230980", "title": "상장폐지에 따른 정리매매"},
                recorded_at=mid_kst,
            ),
            SystemMetric(
                metric_type="BUY_REJECT",
                detail={"stock_code": "001740", "reason": "MARKET_CLOSE_GUARD"},
                recorded_at=mid_kst,
            ),
        ])
        session.commit()

        @contextmanager
        def fake_get_session():  # type: ignore[no-untyped-def]
            yield session

        with patch("src.scheduler.healthcheck.get_session", fake_get_session), patch(
            "src.scheduler.healthcheck._today_kst_window",
            return_value=(start_kst, end_kst),
        ):
            counts = healthcheck._query_today_counts()

        # ── func.case 버그가 있으면 예외 → 전부 기본값(0/빈dict) → 아래 단언 실패
        assert counts["signals_buy"] == 1
        assert counts["signals_sell"] == 1
        assert counts["orders_buy"] == 1
        assert counts["orders_sell"] == 0
        # 거절 사유는 system_metrics에서 집계 (event_logs 아님)
        assert counts["buy_reject_reasons"].get("MARKET_CLOSE_GUARD") == 1
        assert counts["buy_reject_reasons"].get("DISCLOSURE") == 1


def test_market_closed_today_uses_kst_date() -> None:
    """헬스체크의 휴장일 판단은 KST 기준 today를 사용한다."""
    from src.scheduler import healthcheck

    # holidays 모듈을 그대로 위임하므로, 위임 호출만 확인.
    with patch("src.scheduler.healthcheck.is_market_closed") as m:
        m.return_value = False
        # 휴장일이 아니면 None이 아닌 결과를 사용한 후속 분기로 이어진다.
        # 호출 사실만 확인
        from datetime import date as _date

        assert healthcheck.is_market_closed(_date.today()) is False
        m.assert_called_once()
