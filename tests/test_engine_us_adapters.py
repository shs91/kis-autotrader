"""TradingEngine 멀티마켓 얇은 어댑터(P3c-2) 테스트.

시세/주문/잔고 호출의 is_overseas 분기 집약, 거래소 resolve, float 정규화,
US 지정가 주문, KRX 행동불변(passthrough)을 검증한다.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.config as cfg
from src.api.account import Balance
from src.api.quote import CurrentPrice
from src.engine import TradingEngine
from src.market.profile import US_PROFILE


def _us_engine(**kw: object) -> TradingEngine:
    """모든 overseas provider를 MagicMock으로 주입한 US 엔진."""
    return TradingEngine(
        watchlist=kw.get("watchlist", ["AAPL"]),  # type: ignore[arg-type]
        market_profile=US_PROFILE,
        overseas_quote=kw.get("oq") or MagicMock(),
        overseas_order=kw.get("oo") or MagicMock(),
        overseas_account=kw.get("oa") or MagicMock(),
    )


# ── Task 1: provider 주입 + 거래소 resolve ────────────────────


def test_us_engine_has_overseas_providers() -> None:
    oq, oo, oa = MagicMock(), MagicMock(), MagicMock()
    e = _us_engine(oq=oq, oo=oo, oa=oa)
    assert e._overseas_quote is oq
    assert e._overseas_order is oo
    assert e._overseas_account is oa


def test_krx_engine_overseas_providers_none() -> None:
    e = TradingEngine(watchlist=["005930"])
    assert e._overseas_quote is None
    assert e._overseas_order is None
    assert e._overseas_account is None


def test_exchange_of_krx_is_empty() -> None:
    e = TradingEngine(watchlist=["005930"])
    assert e._exchange_of("005930") == ""


def test_exchange_of_us_from_seeded_map() -> None:
    e = _us_engine()
    e._exchanges["AAPL"] = "NASD"
    e._exchanges["KO"] = "NYSE"
    assert e._exchange_of("AAPL") == "NASD"
    assert e._exchange_of("KO") == "NYSE"


def test_exchange_of_us_unresolved_falls_back_to_first() -> None:
    e = _us_engine()
    # 미시드 종목 → 첫 거래소(NASD) fallback
    assert e._exchange_of("ZZZZ") == "NASD"


def test_quote_excd_converts_4digit_to_3digit() -> None:
    e = _us_engine()
    e._exchanges["AAPL"] = "NASD"
    assert e._quote_excd("AAPL") == "NAS"  # OVRS_EXCG_CD(4) → EXCD(3)


def test_trading_config_parses_watchlist_us(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHLIST_CODES_US", "AAPL:NASD, MSFT:NASD ,KO:NYSE")
    parsed = cfg.TradingConfig().watchlist_us
    assert parsed == [("AAPL", "NASD"), ("MSFT", "NASD"), ("KO", "NYSE")]


# ── Task 2: 시세 어댑터 + float DTO + 포맷/정규화 ──────────────


@pytest.mark.asyncio
async def test_get_current_us_decimal_to_float() -> None:
    from src.api.overseas_quote import OverseasCurrentPrice

    oq = MagicMock()
    oq.get_current_price = AsyncMock(
        return_value=OverseasCurrentPrice(
            symbol="AAPL",
            exchange="NAS",
            last=Decimal("150.25"),
            base=Decimal("149"),
            change_rate=0.8,
            volume=100,
            high=Decimal("151"),
            low=Decimal("149"),
            open=Decimal("150"),
            raw_data={},
        )
    )
    e = _us_engine(oq=oq)
    e._exchanges["AAPL"] = "NASD"
    q = await e._get_current("AAPL")
    assert q.current_price == 150.25
    assert isinstance(q.current_price, float)
    oq.get_current_price.assert_awaited_with("AAPL", "NAS")  # EXCD 3자리


@pytest.mark.asyncio
async def test_get_current_krx_passthrough() -> None:
    q_api = MagicMock()
    q_api.get_current_price = AsyncMock(
        return_value=CurrentPrice(
            stock_code="005930",
            stock_name="삼성전자",
            current_price=70000,
            change_price=100,
            change_rate=0.1,
            volume=10,
            high_price=70100,
            low_price=69900,
            open_price=70000,
            raw_data={},
        )
    )
    e = TradingEngine(watchlist=["005930"], quote=q_api)
    q = await e._get_current("005930")
    assert q.current_price == 70000.0
    assert q.stock_name == "삼성전자"
    q_api.get_current_price.assert_awaited_with("005930")  # 국내 인자 1개


@pytest.mark.asyncio
async def test_fetch_daily_us_close_float() -> None:
    from src.api.overseas_quote import OverseasDailyPriceItem

    oq = MagicMock()
    oq.get_daily_price = AsyncMock(
        return_value=[
            OverseasDailyPriceItem(
                date="20260616",
                open=Decimal("149"),
                high=Decimal("151"),
                low=Decimal("148"),
                close=Decimal("150.25"),
                volume=100,
            )
        ]
    )
    e = _us_engine(oq=oq)
    e._exchanges["AAPL"] = "NASD"
    bars = await e._fetch_daily("AAPL")
    assert bars[0].close == 150.25
    assert bars[0].date == "20260616"
    oq.get_daily_price.assert_awaited_with("AAPL", "NAS")


def test_fmt_price_integer_valued_no_decimal() -> None:
    e = TradingEngine(watchlist=["005930"])
    assert e._fmt_price(70000.0) == "70,000"  # KRX 바이트 불변
    assert e._fmt_price(5.0) == "5"
    e_us = _us_engine()
    assert e_us._fmt_price(150.25) == "150.25"  # US 센트


def test_norm_price_krx_int_us_round_half_up() -> None:
    assert TradingEngine(watchlist=["005930"])._norm_price(70000.0) == 70000
    e = _us_engine()
    assert e._norm_price(150.256) == 150.26
    assert e._norm_price(150.255) == 150.26  # HALF_UP (banker's rounding 아님)


def test_order_price_decimal_quantize() -> None:
    e = _us_engine()
    assert e._order_price(150.255) == Decimal("150.26")
    assert e._order_price(4.5) == Decimal("4.50")


# ── Task 3: 잔고 어댑터 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_get_balance_us_normalizes_and_seeds_exchange() -> None:
    from src.api.overseas_account import OverseasBalance, OverseasHolding

    def _bal(exchange: str, currency: str = "USD") -> OverseasBalance:
        holdings = (
            [
                OverseasHolding(
                    symbol="AAPL",
                    exchange=exchange,
                    quantity=3,
                    avg_price=Decimal("100.50"),
                    current_price=Decimal("150.25"),
                    eval_amount=Decimal("450.75"),
                    profit_loss=Decimal("149.25"),
                    profit_rate=49.5,
                    currency=currency,
                )
            ]
            if exchange == "NASD"
            else []
        )
        return OverseasBalance(holdings=holdings, currency=currency, raw_response={})

    oa = MagicMock()
    oa.get_balance = AsyncMock(side_effect=_bal)
    e = _us_engine(oa=oa)
    bal = await e._get_balance(force=True)

    assert isinstance(bal, Balance)
    assert bal.deposit == 1000  # us_cash_budget 기본값
    h = next(x for x in bal.holdings if x.stock_code == "AAPL")
    assert h.quantity == 3
    assert h.avg_price == 100.50  # 센트 보존(float)
    assert e._exchange_of("AAPL") == "NASD"  # 잔고에서 거래소 시드됨
    # 3개 거래소 모두 호출
    assert oa.get_balance.await_count == 3
    called = {c.args[0] for c in oa.get_balance.await_args_list}
    assert called == {"NASD", "NYSE", "AMEX"}


def _us_holding(exchange: str, currency: str = "USD") -> object:
    from src.api.overseas_account import OverseasBalance, OverseasHolding

    holdings = (
        [
            OverseasHolding(
                symbol="AAPL", exchange=exchange, quantity=3,
                avg_price=Decimal("100.50"), current_price=Decimal("150.25"),
                eval_amount=Decimal("450.75"), profit_loss=Decimal("149.25"),
                profit_rate=49.5, currency=currency,
            )
        ]
        if exchange == "NASD"
        else []
    )
    return OverseasBalance(holdings=holdings, currency=currency, raw_response={})


@pytest.mark.asyncio
async def test_fetch_overseas_balance_uses_present_balance() -> None:
    """present-balance 유효 시 총평가/손익/환율 반영, deposit은 예산 캡 유지(보수 사이징)."""
    from src.api.overseas_account import OverseasPresentBalance

    oa = MagicMock()
    oa.get_balance = AsyncMock(side_effect=_us_holding)
    oa.get_present_balance = AsyncMock(
        return_value=OverseasPresentBalance(
            deposit=Decimal("9999.00"),  # 통합증거금 큰 매수여력
            total_eval=Decimal("450.75"),
            total_profit_loss=Decimal("200.00"), profit_rate=12.5,
            fx_rate=Decimal("1385.20"), currency="USD", valid=True, raw={},
        )
    )
    e = _us_engine(oa=oa)
    bal = await e._get_balance(force=True)

    assert bal.currency == "USD"
    # deposit(사이징 기준)은 us_cash_budget 캡 — pb.deposit(9999) 미반영(과대주문 방지)
    assert bal.deposit == 1000
    assert bal.total_profit_loss == 200.00  # present-balance 실손익
    assert bal.total_eval_amount == 450.75
    assert bal.total_profit_rate == 12.5
    assert e._fx_rate == 1385.20  # 고시환율 갱신
    h = next(x for x in bal.holdings if x.stock_code == "AAPL")
    assert h.current_price == 150.25  # int(round) 제거 → 센트 보존
    assert h.eval_amount == 450.75
    assert h.currency == "USD"


@pytest.mark.asyncio
async def test_fetch_overseas_balance_falls_back_when_invalid() -> None:
    """present-balance 무효 시 보유 합산 + us_cash_budget 폴백(라이브 오표기 방지)."""
    from src.api.overseas_account import OverseasPresentBalance

    oa = MagicMock()
    oa.get_balance = AsyncMock(side_effect=_us_holding)
    oa.get_present_balance = AsyncMock(
        return_value=OverseasPresentBalance(
            deposit=Decimal("0"), total_eval=Decimal("0"),
            total_profit_loss=Decimal("0"), profit_rate=0.0,
            fx_rate=Decimal("0"), currency="USD", valid=False, raw={},
        )
    )
    e = _us_engine(oa=oa)
    bal = await e._get_balance(force=True)

    assert bal.deposit == 1000  # us_cash_budget 폴백
    assert bal.total_eval_amount == 450.75  # 보유 합산
    assert bal.total_profit_loss == 149.25  # 보유 합산
    assert e._fx_rate == cfg.settings.trading.fx_usd_krw  # 환율 미갱신(설정 폴백)


@pytest.mark.asyncio
async def test_get_buyable_qty_us() -> None:
    from src.api.overseas_account import OverseasBuyable

    oa = MagicMock()
    oa.get_buyable_amount = AsyncMock(
        return_value=OverseasBuyable(
            orderable_cash=Decimal("1000"), orderable_qty=6, raw={}
        )
    )
    e = _us_engine(oa=oa)
    e._exchanges["AAPL"] = "NASD"
    qty = await e._get_buyable_qty("AAPL", 150.25)
    assert qty == 6
    oa.get_buyable_amount.assert_awaited_with("AAPL", "NASD", Decimal("150.25"))


@pytest.mark.asyncio
async def test_get_executions_us_noop() -> None:
    e = _us_engine()
    assert await e._get_executions() == []


# ── Task 4: 주문 어댑터 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_place_buy_us_limit_order() -> None:
    from src.api.order import OrderResult

    oo = MagicMock()
    oo.buy = AsyncMock(return_value=OrderResult("ODNO1", "0930", "ok", {}))
    e = _us_engine(oo=oo)
    e._exchanges["AAPL"] = "NASD"
    await e._place_buy("AAPL", 2, 150.25)
    oo.buy.assert_awaited_with(
        symbol="AAPL",
        exchange="NASD",
        quantity=2,
        price=Decimal("150.25"),
        order_type="00",
    )


@pytest.mark.asyncio
async def test_place_buy_krx_market_order_passthrough() -> None:
    from src.api.order import OrderResult

    o_api = MagicMock()
    o_api.buy = AsyncMock(return_value=OrderResult("O1", "t", "ok", {}))
    e = TradingEngine(watchlist=["005930"], order=o_api)
    await e._place_buy("005930", 5, 70000.0)
    # 시장가: 수량만, price/order_type 미전달
    o_api.buy.assert_awaited_with(stock_code="005930", quantity=5)


@pytest.mark.asyncio
async def test_place_sell_us_limit_order() -> None:
    from src.api.order import OrderResult

    oo = MagicMock()
    oo.sell = AsyncMock(return_value=OrderResult("ODNO2", "0931", "ok", {}))
    e = _us_engine(oo=oo)
    e._exchanges["AAPL"] = "NASD"
    await e._place_sell("AAPL", 1, 151.0)
    oo.sell.assert_awaited_with(
        symbol="AAPL",
        exchange="NASD",
        quantity=1,
        price=Decimal("151.00"),
        order_type="00",
    )


@pytest.mark.asyncio
async def test_cancel_order_us_uses_exchange() -> None:
    oo = MagicMock()
    oo.cancel = AsyncMock()
    e = _us_engine(oo=oo)
    e._exchanges["AAPL"] = "NASD"
    await e._cancel_order("AAPL", "ODNO1", 2)
    oo.cancel.assert_awaited_with(
        order_no="ODNO1", symbol="AAPL", exchange="NASD", quantity=2
    )


@pytest.mark.asyncio
async def test_cancel_order_krx_passthrough() -> None:
    o_api = MagicMock()
    o_api.cancel = AsyncMock()
    e = TradingEngine(watchlist=["005930"], order=o_api)
    await e._cancel_order("005930", "O1", 5)
    o_api.cancel.assert_awaited_with(order_no="O1", stock_code="005930", quantity=5)


# ── P3c-4: DB payload market/currency 배선 ────────────────────


def _enqueued_payload(engine: TradingEngine, task_type: str) -> dict:
    for call in engine._task_queue.enqueue.call_args_list:  # type: ignore[attr-defined]
        if call.kwargs.get("task_type") == task_type:
            return call.kwargs["payload"]
    raise AssertionError(f"{task_type} 미적재")


def test_record_trade_payload_market_currency_us() -> None:
    from src.db.models import TradeType

    e = _us_engine()
    e._task_queue = MagicMock()
    e._record_trade_to_db("AAPL", "AAPL", TradeType.BUY, 2, 150.25)
    p = _enqueued_payload(e, "record_trade")
    assert p["market"] == "US"
    assert p["currency"] == "USD"


def test_record_trade_payload_market_currency_krx() -> None:
    from src.db.models import TradeType

    e = TradingEngine(watchlist=["005930"])
    e._task_queue = MagicMock()
    e._record_trade_to_db("005930", "삼성전자", TradeType.BUY, 1, 70000)
    p = _enqueued_payload(e, "record_trade")
    assert p["market"] == "KRX"
    assert p["currency"] == "KRW"


def test_sync_portfolio_payload_market_currency_and_key_us() -> None:
    e = _us_engine()
    e._task_queue = MagicMock()
    bal = Balance(
        deposit=1000, total_eval_amount=0, total_profit_loss=0,
        total_profit_rate=0.0, holdings=[], raw_response={},
    )
    e._enqueue_sync_portfolio(bal)
    call = e._task_queue.enqueue.call_args
    assert call.kwargs["payload"]["market"] == "US"
    assert call.kwargs["payload"]["currency"] == "USD"
    # 시장별 네임스페이스 idempotency 키(KRX/US 충돌 방지)
    assert "_US_" in call.kwargs["idempotency_key"]


def _enqueue_key(engine: TradingEngine, method: str, **kw: object) -> str:
    engine._task_queue = MagicMock()
    getattr(engine, method)(**kw)
    return str(engine._task_queue.enqueue.call_args.kwargs["idempotency_key"])


def test_settlement_idempotency_keys_market_namespaced() -> None:
    """결산 enqueue 멱등키가 시장 네임스페이스 — US가 KRX 결산을 선점·디듑하던 버그 차단."""
    bal = Balance(
        deposit=0, total_eval_amount=0, total_profit_loss=0,
        total_profit_rate=0.0, holdings=[], raw_response={},
    )
    cases: list[tuple[str, dict[str, object]]] = [
        ("_enqueue_calendar_event",
         {"trades": [], "realized_profit_loss": 0, "realized_rate": 0.0}),
        ("_enqueue_telegram_daily_summary",
         {"balance": bal, "buy_count": 0, "sell_count": 0,
          "realized_profit_loss": 0, "realized_rate": 0.0}),
        ("_enqueue_telegram_diagnostics", {"diag": {"deposit": 0}}),
        ("_enqueue_daily_summary", {"today_str": "2026-06-18"}),
        ("_enqueue_daily_performance", {"balance": bal, "trades": []}),
    ]
    for method, kw in cases:
        us_key = _enqueue_key(_us_engine(), method, **kw)
        krx_key = _enqueue_key(TradingEngine(watchlist=["005930"]), method, **kw)
        assert "_US_" in us_key, f"{method}: US 키 네임스페이스 누락 ({us_key})"
        assert "_KRX_" in krx_key, f"{method}: KRX 키 네임스페이스 누락 ({krx_key})"
        assert us_key != krx_key, f"{method}: KRX/US 멱등키 충돌 ({us_key})"


def test_board_label_krx_literal_us_exchange() -> None:
    krx = TradingEngine(watchlist=["005930"])
    assert krx._board_label("005930", "KOSPI") == "KOSPI"  # market_stats 필터 호환
    assert krx._board_label("005930", "UNKNOWN") == "UNKNOWN"
    us = _us_engine()
    us._exchanges["AAPL"] = "NASD"
    us._exchanges["KO"] = "NYSE"
    # US는 거래소코드 — 워커가 쓴 stocks.market과 일관(주문 라우팅 시드 유지)
    assert us._board_label("AAPL", "KOSPI") == "NASD"
    assert us._board_label("KO", "KOSPI") == "NYSE"
    # 미상 종목 → _exchange_of 폴백(첫 거래소), 'US' 리터럴 아님
    assert us._board_label("ZZZZ", "KOSPI") == us._market.exchanges[0]


# ── P4: 미국 보수 한도 (야간 무인 실전 안전장치) ──────────────


def test_us_engine_uses_conservative_risk_limits() -> None:
    e = _us_engine()
    t = cfg.settings.trading
    # US는 us_* 보수 한도 사용(기본 포지션 10%·일일 5건·종목당 1회)
    assert e._risk._max_position_ratio == t.us_max_position_ratio
    assert e._risk._daily_trade_limit == t.us_daily_trade_limit
    assert e._max_daily_trades_per_stock == t.us_max_daily_trades_per_stock
    # KRX 대비 보수적(작거나 같음)
    assert e._risk._max_position_ratio <= t.max_position_ratio
    assert e._max_daily_trades_per_stock <= t.max_daily_trades_per_stock


def test_krx_engine_uses_default_risk_limits() -> None:
    e = TradingEngine(watchlist=["005930"])
    t = cfg.settings.trading
    # KRX는 전역 settings 그대로(불변) — 튜닝값과 무관하게 일치
    assert e._risk._max_position_ratio == t.max_position_ratio
    assert e._risk._daily_trade_limit == t.daily_trade_limit
    assert e._max_daily_trades_per_stock == t.max_daily_trades_per_stock
