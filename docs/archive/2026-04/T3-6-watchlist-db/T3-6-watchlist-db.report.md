# T3-6: 관심종목 DB 관리 — PDCA 완료 보고서

> 작성일: 2026-04-03
> PDCA 결과: **PASS (Match Rate 95%)**

## 1. 개요

| 항목 | 내용 |
|------|------|
| 문제 | 관심종목이 .env 고정 → 재시작 없이 변경 불가 |
| 해결 | stocks 테이블에 is_watchlist 컬럼 → DB에서 동적 관리 |
| Match Rate | **95%** |
| 전체 테스트 | **255 passed** |

## 2. 변경 사항

| 파일 | 변경 |
|------|------|
| `src/db/models.py` | `is_watchlist: bool` 컬럼 추가 |
| `alembic/versions/414303a37a97_...` | 마이그레이션 (적용 완료) |
| `src/db/repository.py` | WatchlistRepository (add/remove/get_codes/is_watched/count) |
| `src/engine.py` | `_get_watchlist_codes()` DB 조회 + .env 폴백, `_seed_watchlist_from_env()` |
| `main.py` | `/watch`, `/unwatch`, `/watchlist` Telegram 봇 명령 |

## 3. 사용법

```
Telegram 명령:
/watch 005930       → 관심종목 추가 (즉시 반영, 재시작 불필요)
/unwatch 005930     → 관심종목 제거
/watchlist          → 관심종목 목록 조회
```

## 4. 안전장치

- DB 조회 실패 → `.env` WATCHLIST_CODES 자동 폴백
- `TradingEngine(watchlist=[...])` 기존 방식 하위 호환 유지
- 종목 자체는 삭제하지 않음 (is_watchlist 플래그만 토글)

## 5. PDCA 완료

```
[Plan] ✅ → [Design] ✅ → [Do] ✅ → [Check] ✅ (95%) → [Report] ✅
```
