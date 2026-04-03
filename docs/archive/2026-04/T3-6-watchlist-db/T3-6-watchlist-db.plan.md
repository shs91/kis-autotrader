# T3-6: 관심종목 DB 관리

> 작성일: 2026-04-03
> 상태: Plan
> 의존성: 없음

---

## 1. 문제

현재 관심종목은 `.env`의 `WATCHLIST_CODES=005930,000660,035420`으로 관리.
- **재시작 없이 종목 추가/제거 불가** — 매번 `.env` 수정 후 프로세스 재기동 필요
- Telegram 봇이나 대시보드에서 종목 관리 불가
- 종목별 메모(왜 추가했는지) 기록 불가

---

## 2. 해결 방안

기존 `stocks` 테이블에 `is_watchlist: bool` 컬럼을 추가하여 관심종목 여부를 DB에서 관리.

### 장점
- 새 테이블 불필요 — 기존 `stocks` 테이블 활용
- 운영 중 실시간 종목 추가/제거 가능
- Telegram 봇 명령(`/watch`, `/unwatch`)으로 원격 제어
- `.env`의 `WATCHLIST_CODES`는 **초기 시드(seed)** 용도로만 유지

---

## 3. 핵심 요구사항

| ID | 요구사항 | 설명 |
|----|----------|------|
| R1 | stocks 테이블 확장 | `is_watchlist: bool` 컬럼 추가 (Alembic 마이그레이션) |
| R2 | WatchlistRepository | 관심종목 CRUD — add, remove, list, is_watched |
| R3 | 엔진 통합 | `TradingEngine._fixed_watchlist`를 DB에서 매 사이클 조회 |
| R4 | 초기 시드 | 최초 실행 시 `.env`의 `WATCHLIST_CODES`를 DB에 시드 |
| R5 | Telegram 봇 명령 | `/watch 005930` (추가), `/unwatch 005930` (제거), `/watchlist` (목록) |

---

## 4. 아키텍처

### 4.1 변경 대상

```
src/db/models.py          (수정) Stock 테이블에 is_watchlist 추가
src/db/repository.py      (수정) WatchlistRepository 추가
src/engine.py             (수정) DB에서 관심종목 조회하도록 변경
src/notify/bot.py         (수정) /watch, /unwatch, /watchlist 명령 추가
main.py                   (수정) 봇 명령 등록
alembic/versions/         (신규) 마이그레이션 파일
```

### 4.2 데이터 흐름

```
[현재]
.env WATCHLIST_CODES → config → engine._fixed_watchlist (불변)

[변경 후]
DB stocks.is_watchlist → WatchlistRepository.get_codes() → engine 매 사이클 조회
                              ↑
                  Telegram /watch, /unwatch 명령
                  Dashboard (향후)
```

### 4.3 초기 시드 흐름

```
engine.pre_market()
  ↓
_seed_watchlist_from_env()
  ↓
.env WATCHLIST_CODES 읽기
  ↓
DB에 없는 종목 → stocks 테이블에 INSERT (is_watchlist=True)
  ↓
이미 있는 종목 → is_watchlist=True로 UPDATE
```

---

## 5. 주요 변경 설계

### 5.1 Stock 모델 확장

```python
# src/db/models.py — Stock 클래스에 추가
is_watchlist: Mapped[bool] = mapped_column(
    Boolean, default=False, nullable=False, server_default="false"
)
```

### 5.2 WatchlistRepository

```python
class WatchlistRepository:
    """관심종목 관리 레포지토리."""

    def get_codes(self) -> list[str]:
        """관심종목 코드 목록을 반환한다."""

    def add(self, stock_code: str, stock_name: str = "") -> bool:
        """종목을 관심종목에 추가한다. 이미 있으면 False."""

    def remove(self, stock_code: str) -> bool:
        """종목을 관심종목에서 제거한다. 없으면 False."""

    def is_watched(self, stock_code: str) -> bool:
        """관심종목 여부를 확인한다."""
```

### 5.3 엔진 변경

```python
# 현재
self._fixed_watchlist = watchlist or settings.trading.watchlist_codes

# 변경: 매 사이클 DB에서 조회
def _get_watchlist_codes(self) -> list[str]:
    """DB에서 관심종목 코드를 조회한다."""
    with get_session() as session:
        repo = WatchlistRepository(session)
        return repo.get_codes()
```

`pre_market()`에서 `.env` 시드, `run_trading_cycle()`에서 매 사이클 DB 조회.

### 5.4 Telegram 봇 명령

| 명령 | 동작 | 응답 예시 |
|------|------|-----------|
| `/watch 005930` | 관심종목 추가 | "005930 관심종목에 추가했습니다." |
| `/unwatch 005930` | 관심종목 제거 | "005930 관심종목에서 제거했습니다." |
| `/watchlist` | 관심종목 목록 | "관심종목 (3건): 005930, 000660, 035420" |

---

## 6. 구현 순서

| 순서 | 파일 | 내용 |
|------|------|------|
| 1 | `src/db/models.py` | Stock에 is_watchlist 추가 |
| 2 | `alembic/versions/` | 마이그레이션 생성/실행 |
| 3 | `src/db/repository.py` | WatchlistRepository 추가 |
| 4 | `src/engine.py` | DB 기반 관심종목 조회 + 시드 |
| 5 | `src/notify/bot.py` + `main.py` | Telegram 명령 추가 |
| 6 | `tests/` | 단위 테스트 |

---

## 7. 하위 호환성

| 항목 | 처리 |
|------|------|
| `.env` WATCHLIST_CODES | 유지 — 초기 시드 용도. DB에 종목 없을 때만 사용 |
| `TradingEngine(watchlist=[...])` | 유지 — 테스트/백테스트용 직접 지정 |
| 기존 stocks 데이터 | 마이그레이션에서 `is_watchlist=False` 기본값 설정 |

---

## 8. 검증 기준

- [ ] DB에서 관심종목 추가/제거 후 다음 사이클에 반영
- [ ] Telegram `/watch`, `/unwatch`, `/watchlist` 동작
- [ ] 최초 실행 시 `.env` 시드 → DB 등록
- [ ] 기존 `TradingEngine(watchlist=[...])` 하위 호환
- [ ] Alembic 마이그레이션 적용/롤백 정상
- [ ] `pytest` + `ruff` + `mypy` 통과
