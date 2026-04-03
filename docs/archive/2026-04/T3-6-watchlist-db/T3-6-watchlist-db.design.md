# T3-6: 관심종목 DB 관리 — 상세 설계

> 작성일: 2026-04-03
> 상태: Design
> Plan 문서: `docs/01-plan/features/T3-6-watchlist-db.plan.md`

---

## 1. 파일 목록

### 수정 파일

| 파일 | 변경 |
|------|------|
| `src/db/models.py` | Stock에 `is_watchlist` 컬럼 추가 |
| `src/db/repository.py` | `WatchlistRepository` 클래스 추가 |
| `src/engine.py` | DB 기반 관심종목 조회 + `.env` 시드 |
| `main.py` | `/watch`, `/unwatch`, `/watchlist` 봇 명령 등록 |

### 신규 파일

| 파일 | 설명 |
|------|------|
| `alembic/versions/xxxx_add_is_watchlist.py` | 마이그레이션 |
| `tests/test_db/test_watchlist.py` | WatchlistRepository 테스트 |

---

## 2. 상세 설계

### 2.1 `src/db/models.py` — Stock 모델 확장

```python
class Stock(Base):
    """종목 마스터 테이블."""

    __tablename__ = "stocks"

    # 기존 필드 유지
    id: Mapped[int] = ...
    code: Mapped[str] = ...
    name: Mapped[str] = ...
    market: Mapped[str] = ...
    created_at: Mapped[datetime] = ...
    updated_at: Mapped[datetime] = ...

    # 신규 필드
    is_watchlist: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    # 기존 relationship 유지
    orders: Mapped[list[Order]] = ...
    portfolio: Mapped[Portfolio | None] = ...
```

`Boolean` import 추가: `from sqlalchemy import ..., Boolean`

---

### 2.2 `src/db/repository.py` — WatchlistRepository

```python
class WatchlistRepository:
    """관심종목 관리 레포지토리."""

    def __init__(self, session: Session) -> None:
        """초기화."""
        self._session = session

    def get_codes(self) -> list[str]:
        """관심종목 코드 목록을 반환한다 (코드 정렬).

        Returns:
            관심종목 코드 리스트
        """
        stmt = (
            select(Stock.code)
            .where(Stock.is_watchlist == True)  # noqa: E712
            .order_by(Stock.code)
        )
        return list(self._session.execute(stmt).scalars().all())

    def add(self, stock_code: str, stock_name: str = "") -> bool:
        """종목을 관심종목에 추가한다.

        종목이 stocks 테이블에 없으면 새로 생성한다.
        이미 관심종목이면 False를 반환한다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명 (없으면 코드로 대체)

        Returns:
            True: 추가됨, False: 이미 관심종목
        """
        stock = self._get_or_create(stock_code, stock_name)
        if stock.is_watchlist:
            return False
        stock.is_watchlist = True
        stock.updated_at = datetime.utcnow()
        self._session.flush()
        logger.info("관심종목 추가: %s (%s)", stock.name, stock.code)
        return True

    def remove(self, stock_code: str) -> bool:
        """종목을 관심종목에서 제거한다.

        종목 자체는 삭제하지 않고 is_watchlist만 False로 변경.

        Args:
            stock_code: 종목코드

        Returns:
            True: 제거됨, False: 관심종목이 아니었음
        """
        stock = StockRepository(self._session).get_by_code(stock_code)
        if stock is None or not stock.is_watchlist:
            return False
        stock.is_watchlist = False
        stock.updated_at = datetime.utcnow()
        self._session.flush()
        logger.info("관심종목 제거: %s (%s)", stock.name, stock.code)
        return True

    def is_watched(self, stock_code: str) -> bool:
        """관심종목 여부를 확인한다.

        Args:
            stock_code: 종목코드

        Returns:
            관심종목이면 True
        """
        stmt = (
            select(Stock.is_watchlist)
            .where(Stock.code == stock_code)
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is True

    def count(self) -> int:
        """관심종목 수를 반환한다."""
        from sqlalchemy import func
        stmt = select(func.count()).select_from(Stock).where(
            Stock.is_watchlist == True  # noqa: E712
        )
        return self._session.execute(stmt).scalar_one()

    def _get_or_create(self, stock_code: str, stock_name: str = "") -> Stock:
        """종목을 조회하거나 없으면 생성한다."""
        stock_repo = StockRepository(self._session)
        stock = stock_repo.get_by_code(stock_code)
        if stock is None:
            stock = stock_repo.create(
                stock_code, stock_name or stock_code, "KOSPI"
            )
        return stock
```

---

### 2.3 `src/engine.py` — 변경 사항

#### 변경 1: `__init__` — `_fixed_watchlist` 제거, `_use_db_watchlist` 플래그

```python
def __init__(
    self,
    watchlist: list[str] | None = None,
    strategy: BaseStrategy | None = None,
    selector: StrategySelector | None = None,
) -> None:
    ...
    # 관심종목: 직접 지정 시 고정, 미지정 시 DB에서 매 사이클 조회
    if watchlist is not None:
        self._fixed_watchlist: list[str] | None = watchlist
    else:
        self._fixed_watchlist = None  # DB 모드
```

#### 변경 2: `_get_watchlist_codes()` 신규 메서드

```python
def _get_watchlist_codes(self) -> list[str]:
    """관심종목 코드를 반환한다.

    직접 지정된 watchlist가 있으면 그대로 사용,
    없으면 DB에서 매번 조회한다.

    Returns:
        관심종목 코드 리스트
    """
    if self._fixed_watchlist is not None:
        return self._fixed_watchlist
    try:
        with get_session() as session:
            repo = WatchlistRepository(session)
            codes = repo.get_codes()
        if codes:
            return codes
        # DB에 관심종목이 없으면 .env fallback
        return settings.trading.watchlist_codes
    except Exception:
        logger.exception("관심종목 DB 조회 실패, .env 폴백")
        return settings.trading.watchlist_codes
```

#### 변경 3: `pre_market()` — `.env` 시드

```python
async def pre_market(self) -> None:
    ...
    # 기존 _ensure_watchlist_stocks 대체
    self._seed_watchlist_from_env()
    ...

def _seed_watchlist_from_env(self) -> None:
    """최초 실행 시 .env의 관심종목을 DB에 시드한다."""
    try:
        with get_session() as session:
            repo = WatchlistRepository(session)
            for code in settings.trading.watchlist_codes:
                repo.add(code)
    except Exception:
        logger.exception("관심종목 시드 실패")
```

#### 변경 4: 기존 `self._fixed_watchlist` 참조 → `self._get_watchlist_codes()` 호출

| 기존 코드 | 변경 |
|-----------|------|
| `self._fixed_watchlist` (property `_watchlist`) | `self._get_watchlist_codes()` |
| `for code in self._fixed_watchlist:` (pre_market 일봉 캐싱) | `for code in self._get_watchlist_codes():` |
| `len(self._fixed_watchlist)` (로그) | `len(watchlist_codes)` (변수 캐시 후 사용) |
| `self._fixed_watchlist` in `_build_monitor_targets` | `self._get_watchlist_codes()` |
| `self._fixed_watchlist` in `_screen_stocks` | `self._get_watchlist_codes()` |

---

### 2.4 `main.py` — Telegram 봇 명령 추가

```python
def _register_bot_commands(bot, engine, scheduler) -> None:
    ...
    # 기존 명령 유지 (status, balance, today, help)

    async def cmd_watch(args: str) -> str:
        """관심종목을 추가한다."""
        stock_code = args.strip()
        if not stock_code:
            return "사용법: /watch 005930"
        if len(stock_code) != 6 or not stock_code.isdigit():
            return f"잘못된 종목코드: {stock_code} (6자리 숫자)"
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                added = repo.add(stock_code)
            if added:
                return f"✅ {stock_code} 관심종목에 추가했습니다."
            return f"ℹ️ {stock_code}은(는) 이미 관심종목입니다."
        except Exception as e:
            return f"❌ 추가 실패: {e!s:.100}"

    async def cmd_unwatch(args: str) -> str:
        """관심종목에서 제거한다."""
        stock_code = args.strip()
        if not stock_code:
            return "사용법: /unwatch 005930"
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                removed = repo.remove(stock_code)
            if removed:
                return f"✅ {stock_code} 관심종목에서 제거했습니다."
            return f"ℹ️ {stock_code}은(는) 관심종목이 아닙니다."
        except Exception as e:
            return f"❌ 제거 실패: {e!s:.100}"

    async def cmd_watchlist(_args: str) -> str:
        """관심종목 목록을 반환한다."""
        try:
            with get_session() as session:
                repo = WatchlistRepository(session)
                codes = repo.get_codes()
            if not codes:
                return "관심종목이 없습니다."
            return f"<b>[관심종목]</b> ({len(codes)}건)\n" + ", ".join(codes)
        except Exception as e:
            return f"❌ 조회 실패: {e!s:.100}"

    bot.register("watch", cmd_watch)
    bot.register("unwatch", cmd_unwatch)
    bot.register("watchlist", cmd_watchlist)

    # cmd_help 업데이트
    async def cmd_help(_args: str) -> str:
        return (
            "<b>[명령어]</b>\n"
            "/status — 시스템 상태\n"
            "/balance — 잔고 조회\n"
            "/today — 당일 현황\n"
            "/watch 종목코드 — 관심종목 추가\n"
            "/unwatch 종목코드 — 관심종목 제거\n"
            "/watchlist — 관심종목 목록\n"
            "/help — 명령어 목록"
        )
```

`cmd_today`도 수정: `engine._fixed_watchlist` → `engine._get_watchlist_codes()`

---

### 2.5 Alembic 마이그레이션

```python
"""add is_watchlist to stocks

Revision ID: auto
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "stocks",
        sa.Column(
            "is_watchlist",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("stocks", "is_watchlist")
```

---

## 3. 데이터 흐름

```
[초기 실행]
pre_market() → _seed_watchlist_from_env()
  .env WATCHLIST_CODES → WatchlistRepository.add(code) → stocks.is_watchlist=True

[매 사이클]
run_trading_cycle() → _get_watchlist_codes()
  → WatchlistRepository.get_codes() → DB에서 관심종목 조회
  → (DB 실패 시) .env fallback

[Telegram 원격 제어]
/watch 005930 → WatchlistRepository.add("005930")
/unwatch 005930 → WatchlistRepository.remove("005930")
→ 다음 사이클부터 자동 반영 (재시작 불필요)
```

---

## 4. 에러 처리

| 상황 | 처리 |
|------|------|
| DB 조회 실패 | `.env` WATCHLIST_CODES 폴백 |
| 시드 실패 | 로그 경고, 기존 DB 데이터 유지 |
| 잘못된 종목코드 (`/watch abc`) | "잘못된 종목코드" 응답 |
| 이미 관심종목인 종목 추가 | "이미 관심종목입니다" 응답 |
| 관심종목이 아닌 종목 제거 | "관심종목이 아닙니다" 응답 |
| 마이그레이션 전 DB 접근 | `server_default="false"` 보장 |

---

## 5. 구현 순서

| 순서 | 파일 | 의존성 | 테스트 |
|------|------|--------|--------|
| 1 | `src/db/models.py` | - | - |
| 2 | `alembic/versions/` | models.py | 마이그레이션 실행 |
| 3 | `src/db/repository.py` | models.py | `test_watchlist.py` |
| 4 | `src/engine.py` | repository | 기존 테스트 통과 확인 |
| 5 | `main.py` | repository | - |
| 6 | `tests/test_db/test_watchlist.py` | 전체 | - |

---

## 6. 테스트 설계

### `test_watchlist.py`

| 테스트 | 검증 |
|--------|------|
| `test_add_new_stock` | 새 종목 추가 → True, is_watchlist=True |
| `test_add_existing_stock` | 기존 종목(is_watchlist=False) → True, is_watchlist=True |
| `test_add_already_watched` | 이미 관심종목 → False |
| `test_remove` | 관심종목 제거 → True, is_watchlist=False |
| `test_remove_not_watched` | 관심종목 아닌 종목 → False |
| `test_remove_unknown` | 미존재 종목 → False |
| `test_get_codes` | 관심종목만 반환, 정렬 확인 |
| `test_get_codes_empty` | 관심종목 없음 → 빈 리스트 |
| `test_is_watched` | True/False 정확히 반환 |
| `test_count` | 관심종목 수 정확 |

---

## 7. 하위 호환성

| 기존 사용 | 변경 후 |
|-----------|---------|
| `TradingEngine(watchlist=[...])` | 동일 동작 (고정 목록) |
| `TradingEngine()` | DB에서 조회, DB 비면 `.env` 폴백 |
| `.env` WATCHLIST_CODES | 초기 시드 용도, 삭제 불필요 |
| `engine._fixed_watchlist` (main.py cmd_today) | `engine._get_watchlist_codes()` |
