# 트레일링 스톱 + 마감 청산 게이트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보유 종목의 이익 청산을 고점 대비 되돌림(트레일링 스톱)으로 전환하고, 장 마감 임박 시 이익 포지션을 강제 실현하는 독립 게이트를 추가한다.

**Architecture:** `RiskManager`에 순수 판정 메서드 2개(`should_trailing_stop`, `should_close_for_market_end`)를 추가하고, `engine._process_held_stock`의 청산 우선순위를 손절 > 마감게이트 > 트레일링 > 전략매도로 재구성한다. 고점(peak)은 엔진 인메모리 dict가 핫패스 단일 소스이며, `pre_market`에서 `portfolios.peak_price`로 1회 시드하고 기존 `sync_portfolio` 비동기 워커 경로로 영속화한다(핫패스 동기 DB 0개).

**Tech Stack:** Python 3.12+, SQLAlchemy 2.0, Alembic, PostgreSQL, pytest, dataclass(frozen) 설정 패턴.

**기준 브랜치:** `feat/trailing-stop` (PR #27 `fix/etn-risk-eval-no-daily` 위에 stack — `_evaluate_held_without_daily`/`_process_held_stock`이 이미 존재).

**검증 venv:** `/Users/songhansu/IdeaProjects/kis-autotrader/.venv/bin/python` (이하 `$PY`로 표기). worktree 내에서 실행.

---

### Task 1: 설정값 4개 추가 (`StrategySettings`)

**Files:**
- Modify: `src/config.py` (`StrategySettings`, `take_profit_ratio` 인접 — 현재 282-289행 근처)
- Test: `tests/test_config.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_config.py`에 추가:

```python
def test_trailing_stop_settings_defaults() -> None:
    """트레일링/마감게이트 설정 기본값을 검증한다."""
    from src.config import StrategySettings

    s = StrategySettings()
    assert s.trailing_stop_enabled is True
    assert s.trailing_activation_ratio == 0.05
    assert s.trailing_drawdown_ratio == 0.05
    assert s.min_profitable_close == 0.015
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -m pytest tests/test_config.py::test_trailing_stop_settings_defaults -v`
Expected: FAIL (`AttributeError: ... 'trailing_stop_enabled'`)

- [ ] **Step 3: 구현**

`src/config.py`의 `StrategySettings`에서 `min_confidence` 필드 바로 아래(289행 뒤)에 추가:

```python
    # 트레일링 스톱: 활성화 여부 (off면 기존 take_profit_ratio 고정 익절 폴백)
    trailing_stop_enabled: bool = field(
        default_factory=lambda: _env("TRAILING_STOP_ENABLED", "true").lower() == "true"
    )
    # 트레일링 무장 임계 (평균단가 대비 +x% 도달 시 추격 시작)
    trailing_activation_ratio: float = field(
        default_factory=lambda: _env_float("TRAILING_ACTIVATION_RATIO", 0.05)
    )
    # 트레일링 매도폭 (고점 대비 -x% 되돌림 시 청산)
    trailing_drawdown_ratio: float = field(
        default_factory=lambda: _env_float("TRAILING_DRAWDOWN_RATIO", 0.05)
    )
    # 마감 청산 게이트: 이 수익률 이상이면 마감 임박 시 강제 실현
    min_profitable_close: float = field(
        default_factory=lambda: _env_float("MIN_PROFITABLE_CLOSE", 0.015)
    )
```

- [ ] **Step 4: 통과 확인**

Run: `$PY -m pytest tests/test_config.py::test_trailing_stop_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat(config): 트레일링 스톱 + 마감 게이트 설정 4종 추가"
```

---

### Task 2: `RiskManager.should_trailing_stop` (순수 판정, 시간 무관)

**Files:**
- Modify: `src/strategy/risk.py` (`__init__` 56-60행 근처 + 신규 메서드)
- Test: `tests/test_strategy/test_risk.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_strategy/test_risk.py`에 추가:

```python
class TestShouldTrailingStop:
    """고점 대비 되돌림 청산 판정."""

    def setup_method(self) -> None:
        self.rm = RiskManager(
            trailing_activation_ratio=0.05, trailing_drawdown_ratio=0.05
        )

    def test_not_armed_returns_false(self) -> None:
        # 고점이 활성화 임계(+5%) 미만 → 미무장
        assert self.rm.should_trailing_stop(10_300, 10_000, 10_300) is False

    def test_armed_but_drawdown_insufficient(self) -> None:
        # 무장(고점 +27%), 되돌림 2%만 → 미달
        assert self.rm.should_trailing_stop(12_446, 10_000, 12_700) is False

    def test_armed_and_drawdown_triggers(self) -> None:
        # 무장(고점 +27%), 고점 대비 5% 되돌림 경계
        assert self.rm.should_trailing_stop(12_065, 10_000, 12_700) is True

    def test_zero_guard(self) -> None:
        assert self.rm.should_trailing_stop(100, 0, 100) is False
        assert self.rm.should_trailing_stop(100, 10_000, 0) is False
```

(`12_700 * 0.95 = 12_065` 정확히 경계, `12_446 = 12_700*0.98` 미달)

- [ ] **Step 2: 실패 확인**

Run: `$PY -m pytest tests/test_strategy/test_risk.py::TestShouldTrailingStop -v`
Expected: FAIL (`AttributeError: 'RiskManager' object has no attribute 'should_trailing_stop'` 또는 `__init__` TypeError)

- [ ] **Step 3: 구현**

`src/strategy/risk.py` `__init__` 시그니처에 인자 추가(기존 `take_profit_ratio` 인자 뒤):

```python
        take_profit_ratio: float | None = None,
        trailing_activation_ratio: float | None = None,
        trailing_drawdown_ratio: float | None = None,
        min_profitable_close: float | None = None,
```

`__init__` 본문에서 `self._take_profit_ratio = ...` 블록 뒤에 추가:

```python
        self._trailing_activation_ratio = (
            trailing_activation_ratio
            if trailing_activation_ratio is not None
            else settings.strategy.trailing_activation_ratio
        )
        self._trailing_drawdown_ratio = (
            trailing_drawdown_ratio
            if trailing_drawdown_ratio is not None
            else settings.strategy.trailing_drawdown_ratio
        )
        self._min_profitable_close = (
            min_profitable_close
            if min_profitable_close is not None
            else settings.strategy.min_profitable_close
        )
```

`should_take_profit` 메서드 뒤에 신규 메서드 추가:

```python
    def should_trailing_stop(
        self, current_price: float, avg_price: float, peak_price: float
    ) -> bool:
        """고점 대비 되돌림 청산 여부를 판단한다 (시간 무관).

        무장 조건: 고점이 평균단가 대비 활성화 임계 이상 상승.
        청산 조건: 무장 상태 AND 현재가가 고점 대비 매도폭 이상 하락.
        peak_price는 호출자(engine)가 보존·전달한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가
            peak_price: 보유 후 도달한 최고가

        Returns:
            True이면 트레일링 스톱 청산
        """
        if avg_price <= 0 or peak_price <= 0:
            return False

        peak_profit = (peak_price - avg_price) / avg_price
        if peak_profit < self._trailing_activation_ratio:
            return False  # 미무장

        drawdown = (peak_price - current_price) / peak_price
        should = drawdown >= self._trailing_drawdown_ratio
        if should:
            logger.info(
                "트레일링 시그널: 고점 %.0f 대비 %.2f%% 하락 >= %.2f%% (현재 %.0f)",
                peak_price, drawdown * 100,
                self._trailing_drawdown_ratio * 100, current_price,
            )
        return should
```

- [ ] **Step 4: 통과 확인**

Run: `$PY -m pytest tests/test_strategy/test_risk.py::TestShouldTrailingStop -v`
Expected: PASS (4 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/risk.py tests/test_strategy/test_risk.py
git commit -m "feat(risk): should_trailing_stop 고점 대비 되돌림 판정 추가"
```

---

### Task 3: `RiskManager.should_close_for_market_end` (마감 게이트, 이익 한정)

**Files:**
- Modify: `src/strategy/risk.py` (신규 메서드)
- Test: `tests/test_strategy/test_risk.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
class TestShouldCloseForMarketEnd:
    """마감 임박 강제 청산 게이트 (이익 포지션 한정)."""

    def setup_method(self) -> None:
        self.rm = RiskManager(min_profitable_close=0.015)

    def test_not_near_close_returns_false(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: False  # type: ignore[method-assign]
        assert self.rm.should_close_for_market_end(10_200, 10_000) is False

    def test_near_close_profit_below_min(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        # +1.0% < 1.5%
        assert self.rm.should_close_for_market_end(10_100, 10_000) is False

    def test_near_close_profit_meets_min(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        # +1.5% 경계
        assert self.rm.should_close_for_market_end(10_150, 10_000) is True

    def test_near_close_loss_excluded(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        # 손실 포지션은 게이트 대상 아님
        assert self.rm.should_close_for_market_end(9_500, 10_000) is False

    def test_zero_guard(self) -> None:
        self.rm.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
        assert self.rm.should_close_for_market_end(100, 0) is False
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -m pytest tests/test_strategy/test_risk.py::TestShouldCloseForMarketEnd -v`
Expected: FAIL (`AttributeError: ... 'should_close_for_market_end'`)

- [ ] **Step 3: 구현**

`src/strategy/risk.py`에 `should_trailing_stop` 뒤로 추가:

```python
    def should_close_for_market_end(
        self,
        current_price: float,
        avg_price: float,
        now: datetime | None = None,
    ) -> bool:
        """마감 임박 강제 청산 게이트 — 이익 포지션 한정.

        트레일링과 독립된 별도 규칙. 시간 의존은 이 게이트의 발동 조건뿐이며,
        손실 포지션(수익률 < min_profitable_close)은 대상에서 제외한다.

        Args:
            current_price: 현재가
            avg_price: 평균 매입가
            now: 판정 기준 시각 (None이면 현재 시각)

        Returns:
            True이면 마감 임박 + 최소 수익률 충족으로 청산
        """
        if avg_price <= 0:
            return False
        if not self.is_near_market_close(now):
            return False

        profit = (current_price - avg_price) / avg_price
        should = profit >= self._min_profitable_close
        if should:
            logger.info(
                "마감 청산 게이트: 수익률 %.2f%% >= %.2f%% (마감 임박)",
                profit * 100, self._min_profitable_close * 100,
            )
        return should
```

- [ ] **Step 4: 통과 확인**

Run: `$PY -m pytest tests/test_strategy/test_risk.py::TestShouldCloseForMarketEnd -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/risk.py tests/test_strategy/test_risk.py
git commit -m "feat(risk): should_close_for_market_end 마감 청산 게이트 추가"
```

---

### Task 4: DB 모델 — `Portfolio.peak_price` + `SellReason` 값 2종

**Files:**
- Modify: `src/db/models.py` (`SellReason` 54-60행, `Portfolio` 164행 근처)
- Test: `tests/test_db/test_models_trailing.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_db/test_models_trailing.py` 생성:

```python
"""트레일링 관련 모델 변경 검증."""

from __future__ import annotations

from src.db.models import Portfolio, SellReason


def test_sell_reason_has_trailing_and_market_close() -> None:
    assert SellReason.TRAILING_STOP.value == "TRAILING_STOP"
    assert SellReason.MARKET_CLOSE.value == "MARKET_CLOSE"


def test_portfolio_has_peak_price_column() -> None:
    assert "peak_price" in Portfolio.__table__.columns
    assert Portfolio.__table__.columns["peak_price"].nullable is True
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -m pytest tests/test_db/test_models_trailing.py -v`
Expected: FAIL (`AttributeError: TRAILING_STOP` / `peak_price` 미존재)

- [ ] **Step 3: 구현**

`src/db/models.py` `SellReason` enum에 값 추가(`MANUAL` 뒤):

```python
    TRAILING_STOP = "TRAILING_STOP"
    MARKET_CLOSE = "MARKET_CLOSE"
```

`Portfolio` 모델 `current_price` 매핑 뒤에 추가:

```python
    peak_price: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 4: 통과 확인**

Run: `$PY -m pytest tests/test_db/test_models_trailing.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/db/models.py tests/test_db/test_models_trailing.py
git commit -m "feat(db): Portfolio.peak_price 컬럼 + SellReason TRAILING_STOP/MARKET_CLOSE"
```

---

### Task 5: Alembic 마이그레이션 — 컬럼 + enum 값

**Files:**
- Create: `alembic/versions/<auto>_add_peak_price_and_sell_reasons.py`

> PG enum은 `ALTER TYPE ... ADD VALUE`가 트랜잭션 내 즉시 사용 불가하므로 `autocommit_block()`을 사용한다. down_revision은 현재 head `4ea33aed4c86`.

- [ ] **Step 1: 마이그레이션 파일 생성 (수동 작성)**

`alembic/versions/a1b2c3d4e5f6_add_peak_price_and_sell_reasons.py` 생성:

```python
"""add portfolios.peak_price and SellReason TRAILING_STOP/MARKET_CLOSE

Revision ID: a1b2c3d4e5f6
Revises: 4ea33aed4c86
Create Date: 2026-05-22

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "4ea33aed4c86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolios",
        sa.Column("peak_price", sa.Float(), nullable=True),
    )
    # PG enum 값 추가는 트랜잭션 밖에서 수행
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sell_reason_enum ADD VALUE IF NOT EXISTS 'TRAILING_STOP'")
        op.execute("ALTER TYPE sell_reason_enum ADD VALUE IF NOT EXISTS 'MARKET_CLOSE'")


def downgrade() -> None:
    op.drop_column("portfolios", "peak_price")
    # PG enum 값 제거는 비가역(라벨 삭제 미지원) — no-op
```

- [ ] **Step 2: 마이그레이션 검토 + 적용**

Run: `$PY -m alembic upgrade head`
Expected: `Running upgrade 4ea33aed4c86 -> a1b2c3d4e5f6` 출력, 에러 없음.

검증:
Run: `docker exec kis-postgres psql -U kis_user -d kis_trader -c "\d portfolios" | grep peak_price`
Expected: `peak_price | double precision | | |` 행 출력.
Run: `docker exec kis-postgres psql -U kis_user -d kis_trader -c "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid=t.oid WHERE t.typname='sell_reason_enum';"`
Expected: `TRAILING_STOP`, `MARKET_CLOSE` 포함.

- [ ] **Step 3: 커밋**

```bash
git add alembic/versions/a1b2c3d4e5f6_add_peak_price_and_sell_reasons.py
git commit -m "feat(db): peak_price 컬럼 + sell_reason enum 값 마이그레이션"
```

---

### Task 6: `PortfolioRepository` — peak_price upsert + 시드 조회

**Files:**
- Modify: `src/db/repository.py` (`PortfolioRepository.upsert` 301행, 신규 `get_peak_prices`)
- Test: `tests/test_db/test_portfolio_peak.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_db/test_portfolio_peak.py` 생성 (in-memory SQLite + 기존 conftest 세션 패턴 참고):

```python
"""PortfolioRepository peak_price 영속/조회 검증."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base
from src.db.repository import PortfolioRepository, StockRepository


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_upsert_persists_peak_price(session: Session) -> None:
    stock = StockRepository(session).create("760027", "ETN", "KOSPI")
    repo = PortfolioRepository(session)
    repo.upsert(stock_id=stock.id, quantity=100, avg_price=3565.0,
                current_price=4535.0, peak_price=5000.0)
    p = repo.get_by_stock(stock.id)
    assert p is not None
    assert p.peak_price == 5000.0


def test_get_peak_prices_returns_code_map(session: Session) -> None:
    stock = StockRepository(session).create("760027", "ETN", "KOSPI")
    repo = PortfolioRepository(session)
    repo.upsert(stock_id=stock.id, quantity=100, avg_price=3565.0,
                current_price=4535.0, peak_price=5000.0)
    assert repo.get_peak_prices() == {"760027": 5000.0}


def test_get_peak_prices_skips_null(session: Session) -> None:
    stock = StockRepository(session).create("005930", "삼성", "KOSPI")
    repo = PortfolioRepository(session)
    repo.upsert(stock_id=stock.id, quantity=10, avg_price=70000.0,
                current_price=71000.0)  # peak_price 미지정 → NULL
    assert repo.get_peak_prices() == {}
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -m pytest tests/test_db/test_portfolio_peak.py -v`
Expected: FAIL (`upsert() got unexpected keyword 'peak_price'` / `get_peak_prices` 미존재)

- [ ] **Step 3: 구현**

`src/db/repository.py` `PortfolioRepository.upsert` 시그니처에 추가:

```python
        current_price: float,
        peak_price: float | None = None,
    ) -> Portfolio:
```

생성 분기(`Portfolio(...)`)에 `peak_price=peak_price,` 추가. 갱신 분기에서 None이 아닐 때만 갱신(기존 고점 보존):

```python
        else:
            portfolio.quantity = quantity
            portfolio.avg_price = avg_price
            portfolio.current_price = current_price
            if peak_price is not None:
                portfolio.peak_price = peak_price
            portfolio.updated_at = datetime.now(UTC).replace(tzinfo=None)
```

`get_by_stock` 메서드 뒤에 신규 메서드 추가(같은 클래스 내):

```python
    def get_peak_prices(self) -> dict[str, float]:
        """보유 포지션의 (종목코드 → peak_price) 맵을 반환한다 (NULL 제외).

        engine.pre_market에서 인메모리 peak dict 시드용.
        """
        result: dict[str, float] = {}
        for p in self.get_all_positions():
            if p.peak_price is not None and p.stock is not None:
                result[p.stock.code] = float(p.peak_price)
        return result
```

> 주의: `get_all_positions`가 `stock` 관계를 lazy-load 한다. `p.stock.code`가 동작하는지 확인하고, 안 되면 `get_all_positions`에 join 추가. SQLite 테스트에서 통과해야 함.

- [ ] **Step 4: 통과 확인**

Run: `$PY -m pytest tests/test_db/test_portfolio_peak.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/db/repository.py tests/test_db/test_portfolio_peak.py
git commit -m "feat(db): PortfolioRepository peak_price upsert + get_peak_prices"
```

---

### Task 7: 비동기 영속화 배선 — 핸들러 + enqueue 페이로드

**Files:**
- Modify: `src/worker/handlers.py` (`SyncPortfolioHandler.execute` 111행 근처)
- Modify: `src/engine.py` (`_enqueue_sync_portfolio` 1415-1431행)
- Test: `tests/test_engine_trailing_stop.py` (신규, enqueue 페이로드 검증분)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_engine_trailing_stop.py` 생성 (Task 8과 공유; 여기선 enqueue 검증만 먼저):

```python
"""트레일링 스톱 + 마감 게이트 엔진 통합 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine import TradingEngine


def _make_engine() -> TradingEngine:
    with patch("src.engine.KISClient"), patch("src.engine.QuoteAPI"), \
         patch("src.engine.OrderAPI"), patch("src.engine.AccountAPI"), \
         patch("src.engine.TelegramNotifier"), patch("src.engine.StrategyRegistry"), \
         patch("src.engine.StrategySelector"):
        engine = TradingEngine(watchlist=["005930"])
    engine._risk.is_near_market_close = lambda *a, **kw: False  # type: ignore[method-assign]
    return engine


def test_enqueue_sync_portfolio_includes_peak_price() -> None:
    engine = _make_engine()
    engine._peak_prices = {"760027": 5000.0}
    balance = MagicMock()
    h = MagicMock()
    h.stock_code = "760027"
    h.stock_name = "ETN"
    h.quantity = 100
    h.avg_price = 3565.0
    h.current_price = 4535.0
    balance.holdings = [h]
    with patch.object(engine._task_queue, "enqueue") as mock_enq:
        engine._enqueue_sync_portfolio(balance)
        payload = mock_enq.call_args.kwargs["payload"]
        assert payload["holdings"][0]["peak_price"] == 5000.0
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -m pytest tests/test_engine_trailing_stop.py::test_enqueue_sync_portfolio_includes_peak_price -v`
Expected: FAIL (`KeyError: 'peak_price'` 또는 `AttributeError: _peak_prices`)

- [ ] **Step 3: 구현**

`src/engine.py` `_enqueue_sync_portfolio`의 holdings dict에 추가:

```python
            holdings.append({
                "stock_code": h.stock_code,
                "stock_name": getattr(h, "stock_name", h.stock_code),
                "quantity": h.quantity,
                "avg_price": float(h.avg_price),
                "current_price": float(h.current_price),
                "peak_price": self._peak_prices.get(h.stock_code),
            })
```

`src/worker/handlers.py` `SyncPortfolioHandler.execute`의 upsert 호출에 추가:

```python
                portfolio_repo.upsert(
                    stock_id=stock.id,
                    quantity=h["quantity"],
                    avg_price=h["avg_price"],
                    current_price=h["current_price"],
                    peak_price=h.get("peak_price"),
                )
```

> `engine.__init__`에 `self._peak_prices: dict[str, float] = {}`가 필요(Task 8 Step 3에서 추가하지만, 이 테스트 통과를 위해 여기서 먼저 추가). `__init__`의 dict 초기화 블록(예: `self._daily_cache` 인접)에 `self._peak_prices: dict[str, float] = {}` 추가.

- [ ] **Step 4: 통과 확인**

Run: `$PY -m pytest tests/test_engine_trailing_stop.py::test_enqueue_sync_portfolio_includes_peak_price -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/engine.py src/worker/handlers.py tests/test_engine_trailing_stop.py
git commit -m "feat(engine): peak_price를 sync_portfolio 비동기 영속화 경로에 배선"
```

---

### Task 8: 엔진 청산 우선순위 재구성 + peak dict 관리

**Files:**
- Modify: `src/engine.py` (`__init__` peak dict, `pre_market` 시드 246-256행, `_process_held_stock` 861-896행, `_execute_buy` 900행대, `_execute_sell` full-sell 시 pop, `_SELL_REASON_MAP` 1007-1011행)
- Test: `tests/test_engine_trailing_stop.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_engine_trailing_stop.py`에 추가:

```python
def _stub(engine, price, name="ETN"):
    cur = MagicMock()
    cur.current_price = price
    cur.stock_name = name
    engine._quote.get_current_price = AsyncMock(return_value=cur)


async def _run_held(engine, code, avg, qty=100):
    from src.engine import SignalType  # noqa
    engine._get_daily_df = AsyncMock(return_value=None)  # 일봉 없는 ETN 경로
    engine._execute_sell = AsyncMock()
    with patch.object(engine._task_queue, "enqueue"), \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code=code, deposit=1_000_000, is_held=True,
            holding_info={"avg_price": avg, "quantity": qty},
        )
    return engine._execute_sell


@pytest.mark.asyncio
async def test_trailing_fires_on_pullback() -> None:
    engine = _make_engine()
    engine._peak_prices = {"760027": 12_700.0}  # 고점 +27%
    _stub(engine, 12_000)  # 고점 대비 -5.5% → 트레일 발동
    sell = await _run_held(engine, "760027", 10_000.0)
    sell.assert_awaited_once()
    assert sell.call_args.kwargs["reason"] == "트레일링"


@pytest.mark.asyncio
async def test_trailing_not_fire_dead_zone() -> None:
    engine = _make_engine()
    engine._peak_prices = {"760027": 12_700.0}
    _stub(engine, 12_600)  # 고점 대비 -0.8% → 미발동
    sell = await _run_held(engine, "760027", 10_000.0)
    sell.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_close_gate_fires_on_profit() -> None:
    engine = _make_engine()
    engine._risk.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
    engine._peak_prices = {"760027": 10_200.0}  # 미무장(+2%)
    _stub(engine, 10_200)  # +2% >= 1.5% → 마감 게이트
    sell = await _run_held(engine, "760027", 10_000.0)
    sell.assert_awaited_once()
    assert sell.call_args.kwargs["reason"] == "마감청산"


@pytest.mark.asyncio
async def test_market_close_gate_excludes_loss() -> None:
    engine = _make_engine()
    engine._risk.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
    engine._peak_prices = {"760027": 10_000.0}
    _stub(engine, 9_500)  # 손실 → 게이트·트레일 모두 제외, 손절도 -5%라 발동
    sell = await _run_held(engine, "760027", 10_000.0)
    # 손실 -5%는 손절(-3%) 발동
    assert sell.call_args.kwargs["reason"] == "손절"


@pytest.mark.asyncio
async def test_stop_loss_priority_over_gate() -> None:
    engine = _make_engine()
    engine._risk.is_near_market_close = lambda *a, **kw: True  # type: ignore[method-assign]
    engine._peak_prices = {"005930": 70_000.0}
    _stub(engine, 67_000, "삼성")  # -4.3% → 손절 우선
    sell = await _run_held(engine, "005930", 70_000.0)
    assert sell.call_args.kwargs["reason"] == "손절"
```

- [ ] **Step 2: 실패 확인**

Run: `$PY -m pytest tests/test_engine_trailing_stop.py -v`
Expected: 신규 5건 FAIL (현재는 익절/손절 로직만 존재 → reason 불일치 또는 미발동)

- [ ] **Step 3: 구현 — peak dict 관리**

`src/engine.py` `__init__`에 (Task 7에서 미추가 시) `self._peak_prices: dict[str, float] = {}` 확인.

`pre_market`의 `self._daily_cache.clear()`(254행) 뒤에 시드 추가:

```python
        self._peak_prices = self._load_peak_prices()
```

신규 메서드 추가(`_get_daily_df` 인근, 동기 헬퍼):

```python
    def _load_peak_prices(self) -> dict[str, float]:
        """portfolios.peak_price를 읽어 인메모리 peak dict를 시드한다."""
        try:
            with get_session() as session:
                from src.db.repository import PortfolioRepository
                return PortfolioRepository(session).get_peak_prices()
        except Exception:
            logger.exception("peak_price 시드 로드 실패 — 빈 dict로 시작")
            return {}
```

- [ ] **Step 4: 구현 — `_process_held_stock` 재구성**

`src/engine.py` `_process_held_stock`의 `avg_price`/`quantity` 할당(861-862행) 뒤, 손절 분기 앞에 peak 갱신 추가:

```python
        # 고점(peak) 갱신 — 핫패스 인메모리 단일 소스
        prev = self._peak_prices.get(stock_code)
        seed = prev if prev is not None else max(avg_price, float(current_price))
        peak = max(seed, float(current_price))
        self._peak_prices[stock_code] = peak
```

기존 `should_take_profit` 분기(875-884행)를 다음으로 **교체**:

```python
        # 2순위: 마감 임박 강제 청산 게이트 (이익 포지션 한정, 트레일링과 독립)
        if self._risk.should_close_for_market_end(float(current_price), avg_price):
            logger.info(
                "[%s] 마감 청산 게이트 매도 (현재가: %d, 매입가: %.0f)",
                stock_code, current_price, avg_price,
            )
            await self._execute_sell(
                stock_code, quantity, current_price,
                reason="마감청산", avg_price=avg_price, stock_name=stock_name,
            )
            return

        # 3순위: 트레일링 스톱 (활성화 시 익절 대체) / 비활성 시 고정 익절 폴백
        if settings.strategy.trailing_stop_enabled:
            if self._risk.should_trailing_stop(float(current_price), avg_price, peak):
                logger.info(
                    "[%s] 트레일링 매도 (현재가: %d, 고점: %.0f, 매입가: %.0f)",
                    stock_code, current_price, peak, avg_price,
                )
                await self._execute_sell(
                    stock_code, quantity, current_price,
                    reason="트레일링", avg_price=avg_price, stock_name=stock_name,
                )
                return
        else:
            if self._risk.should_take_profit(float(current_price), avg_price):
                logger.info(
                    "[%s] 익절 매도 실행 (현재가: %d, 매입가: %.0f)",
                    stock_code, current_price, avg_price,
                )
                await self._execute_sell(
                    stock_code, quantity, current_price,
                    reason="익절", avg_price=avg_price, stock_name=stock_name,
                )
                return
```

(손절 분기 864-873행, 전략매도 분기 886-896행은 그대로 유지)

- [ ] **Step 5: 구현 — peak dict 라이프사이클 (buy/sell)**

`_execute_buy`의 매수 성공 직후(주문 성공 분기 끝, DB 기록 후)에 추가:

```python
            # 신규/추가 매수 — 다음 사이클에 max(avg, current)로 재시드
            self._peak_prices.pop(stock_code, None)
```

`_execute_sell`의 매도 성공 직후(체결 로그 뒤)에 추가:

```python
            # 청산 — 고점 추적 종료
            self._peak_prices.pop(stock_code, None)
```

> 위치: 두 메서드 모두 주문 성공(`result`) 분기 내부, DB enqueue 직후. 실패 경로(except)에는 넣지 않는다.

- [ ] **Step 6: 구현 — `_SELL_REASON_MAP`**

`src/engine.py` `_SELL_REASON_MAP`(1007행)에 매핑 추가:

```python
    _SELL_REASON_MAP: dict[str, SellReason] = {
        "손절": SellReason.STOP_LOSS,
        "익절": SellReason.TAKE_PROFIT,
        "전략매도": SellReason.STRATEGY,
        "트레일링": SellReason.TRAILING_STOP,
        "마감청산": SellReason.MARKET_CLOSE,
    }
```

- [ ] **Step 7: 통과 확인**

Run: `$PY -m pytest tests/test_engine_trailing_stop.py -v`
Expected: PASS (enqueue 1 + 신규 5 = 6 tests)

- [ ] **Step 8: 커밋**

```bash
git add src/engine.py tests/test_engine_trailing_stop.py
git commit -m "feat(engine): 청산 우선순위 재구성(손절>마감게이트>트레일링>전략) + peak dict 관리"
```

---

### Task 9: 전체 회귀 검증 + 기존 익절 테스트 정합성

**Files:**
- 확인: `tests/test_strategy/test_risk.py`(기존 `should_take_profit` 테스트는 유지 — 메서드 잔존), `tests/test_engine_risk_only_eval.py`(ETN 경로 — 트레일/게이트 영향 확인)

- [ ] **Step 1: 기존 ETN 경로 테스트 영향 확인**

`tests/test_engine_risk_only_eval.py`의 `test_held_no_daily_triggers_take_profit`는 현재가 12,700(+27%)으로 익절을 기대한다. 트레일링 활성 기본값에서는 peak가 없으면 seed=max(avg,current)=12,700 → 고점 대비 되돌림 0% → 트레일링 미발동, 마감게이트도 비마감이라 미발동 → **매도 안 됨**으로 동작이 바뀐다.

조치: 해당 테스트를 트레일링 의미에 맞게 갱신한다. `engine._peak_prices = {"760027": 13_500.0}`를 주입하고 현재가 12_700(고점 대비 -5.9%)로 트레일링 발동(reason "트레일링")을 기대하도록 수정. 손절/데드존/미보유 케이스는 유지.

```python
# test_held_no_daily_triggers_take_profit → test_held_no_daily_triggers_trailing 로 개명/수정
@pytest.mark.asyncio
async def test_held_no_daily_triggers_trailing() -> None:
    engine = _make_engine()
    engine._get_daily_df = AsyncMock(return_value=None)
    engine._peak_prices = {"760027": 13_500.0}  # 고점 +35%
    _stub_current_price(engine, price=12_700)    # 고점 대비 -5.9% → 트레일
    engine._execute_sell = AsyncMock()
    with patch.object(engine._task_queue, "enqueue"), \
         patch.object(engine, "_update_stock_name_if_needed"), \
         patch.object(engine, "_resolve_stock_name", return_value=""):
        await engine._process_stock(
            stock_code="760027", deposit=1_000_000, is_held=True,
            holding_info={"avg_price": 10_000.0, "quantity": 100},
        )
    engine._execute_sell.assert_awaited_once()
    assert engine._execute_sell.call_args.kwargs["reason"] == "트레일링"
```

> `_make_engine`에 `engine._peak_prices` 기본 `{}`가 보장돼야 한다(Task 7/8에서 `__init__` 추가). 데드존 테스트는 `_peak_prices`를 현재가와 동일하게 두어 트레일 미발동 유지.

- [ ] **Step 2: 전체 테스트**

Run: `$PY -m pytest tests/ -q`
Expected: 전체 PASS (신규 포함). 실패 시 해당 테스트의 트레일/게이트 가정을 점검.

- [ ] **Step 3: 타입/린트**

Run: `$PY -m mypy src/` → 신규 에러 0 (사전 부채는 baseline 대비 증가 없음).
Run: `ruff check src/` → All checks passed.

- [ ] **Step 4: 커밋**

```bash
git add tests/
git commit -m "test: ETN 경로 테스트를 트레일링 의미로 갱신 + 전체 회귀 통과"
```

---

### Task 10: 문서 + 운영 반영 (실행 시점)

- [ ] **Step 1: 구현 이력 기록**

```bash
$PY scripts/record_implementation.py \
  --title "트레일링 스톱 + 마감 청산 게이트" \
  --category feature \
  --proposal "docs/superpowers/specs/2026-05-22-trailing-stop-and-market-close-gate-design.md" \
  --files '{"src/strategy/risk.py":"should_trailing_stop/should_close_for_market_end","src/engine.py":"청산 우선순위 재구성 + peak dict","src/config.py":"설정 4종","src/db/*":"peak_price 컬럼 + SellReason 2값","alembic":"마이그레이션"}' \
  --verification "pytest 전체 PASS | mypy 신규 0 | ruff ✅" \
  --background "고정 +5% 익절이 고점 대비 되돌림을 못 잡음(760027 +27%→되돌림 무한보유)" \
  --effect "트레일링이 익절 대체, 마감 게이트로 이익 포지션 강제 실현, 손실 포지션 제외"
```

- [ ] **Step 2: CHANGELOG rolling 갱신**

`docs/CHANGELOG.md` 최상단에 신규 항목 추가, 가장 오래된 항목 제거(5건 유지). README의 매매 전략/환경변수 섹션에 트레일링/MIN_PROFITABLE_CLOSE 반영.

- [ ] **Step 3: 최종 커밋**

```bash
git add docs/ README.md
git commit -m "docs: 트레일링 스톱 + 마감 게이트 CHANGELOG/README 갱신"
```

> 운영자 액션(머지 후): 메인 체크아웃에서 `alembic upgrade head` + `launchctl stop/start com.kis.autotrader`.

---

## 비고 / 실행 순서 주의

- Task 5(마이그레이션 적용)는 공유 `kis-postgres`에 실제 DDL을 수행한다. enum `ADD VALUE`는 비가역이므로 운영 DB 영향 인지하에 진행.
- Task 7의 `self._peak_prices` `__init__` 초기화는 Task 8보다 먼저 필요하므로 Task 7 Step 3에서 추가한다.
- 트레일링 활성 기본값이므로 기존 `should_take_profit` 기반 테스트(`tests/test_strategy/test_risk.py::TestShouldTakeProfit`)는 메서드 잔존으로 그대로 통과해야 한다(라이브 경로에서만 호출 제거).
