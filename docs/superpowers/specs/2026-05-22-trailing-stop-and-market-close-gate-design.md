# 트레일링 스톱 + 마감 청산 게이트 설계

- 작성일: 2026-05-22
- 카테고리: feature
- 담당 모듈: src/strategy/risk.py, src/engine.py, src/config.py, src/db/{models,repository}.py, alembic

## 1. 배경 / 문제

현재 보유 종목의 이익 청산은 `RiskManager.should_take_profit`(평균단가 대비 +5% 고정,
14:30 이후 +2.5%로 절반 하향)뿐이다. 이 구조는 고점 대비 되돌림을 잡지 못한다.

실제 사례(760027 키움 인버스 2X 전력 TOP5 ETN): 5/13 매수 후 평균단가 3,565원 →
고점 +27% 부근까지 상승 후 되돌림. 고정 익절은 +5% 도달 즉시 팔리거나(또는
ETN 일봉 0건 이슈로 평가 자체가 스킵되어) 어느 쪽이든 run-up 수익을 지키지 못한다.

## 2. 목표

1. **트레일링 스톱**으로 고점 대비 되돌림을 청산한다 (기존 +5% 고정 익절을 대체).
2. **마감 임박 강제 청산 게이트**를 트레일링과 **독립된 별도 규칙**으로 추가해, 이익
   포지션을 장 마감 전에 실현한다(오버나잇 리스크 회피). 단 손실 포지션은 제외.
3. 손절 규칙은 일절 건드리지 않는다.

## 3. 비목표 (YAGNI)

- 강제 EOD 전량 청산(손실 포함) — 하지 않는다. 게이트는 이익 포지션 한정.
- 트레일 폭/활성화 임계의 시간대별 가변 — 하지 않는다. 시간 의존은 게이트 발동 조건뿐.
- 백테스트 엔진의 익절 로직 변경 — 범위 밖. `should_take_profit` 메서드는 잔존시킨다.
- 다단계(계단식) 트레일링, ATR 기반 동적 폭 — 범위 밖.

## 4. 청산 우선순위 (`engine._process_held_stock`)

평균단가 `avg`, 현재가 `cur`, 보존 고점 `peak` 기준.

| 순위 | 규칙 | 조건 | reason | 비고 |
|------|------|------|--------|------|
| 1 | 손절 | `cur ≤ avg×(1−MAX_LOSS_RATE)` | `"손절"` | **미변경** |
| 2 | 마감 청산 게이트 | `is_near_market_close()` AND `(cur−avg)/avg ≥ MIN_PROFITABLE_CLOSE` | `"마감청산"` | 신규·독립, 이익 포지션만 |
| 3 | 트레일링 | 무장 AND `cur ≤ peak×(1−TRAILING_DRAWDOWN_RATIO)` | `"트레일링"` | 신규, 익절 대체 |
| 4 | 전략매도 | `signal==SELL AND confidence ≥ 0.1` | `"전략매도"` | **미변경** |

- **무장(arm)**: `peak`가 `avg×(1+TRAILING_ACTIVATION_RATIO)`를 한 번이라도 도달하면 무장.
  peak가 보존되므로 sticky(한 번 무장되면 이후 수익이 임계 아래로 내려가도 유지).
- **손실 포지션 처리**: 트레일링은 무장(=이익 ≥ +5% 도달) 포지션만 대상이므로 손실
  포지션에는 적용되지 않는다. 마감 게이트도 이익 ≥ MIN_PROFITABLE_CLOSE만 대상이라
  손실 포지션은 제외된다. 손실 포지션은 손절 규칙에만 맡긴다.
- **일봉 없는 경로**(`_evaluate_held_without_daily`)도 `_process_held_stock`을 거치므로
  760027 같은 ETN에 트레일링·마감 게이트가 동일하게 적용된다(HOLD 시그널이라 4순위
  전략매도만 스킵).
- `TRAILING_STOP_ENABLED=false`이면 3순위를 기존 `should_take_profit`(+5% 고정,
  마감임박 +2.5%) 호출로 폴백한다. 이 경우 2순위 마감 게이트는 그대로 동작한다.

## 5. RiskManager — 규칙 분리 (독립 단위 테스트 가능)

`src/strategy/risk.py`에 순수 메서드 2개 추가. 둘은 서로 의존하지 않는다.

```python
def should_trailing_stop(
    self, current_price: float, avg_price: float, peak_price: float
) -> bool:
    """고점 대비 되돌림 청산 여부. 시간 무관, peak는 인자로 받아 상태 비보유 유지.

    무장 조건: peak가 avg×(1+activation) 이상.
    청산 조건: 무장 AND current ≤ peak×(1−drawdown).
    avg_price<=0 또는 peak_price<=0이면 False.
    """

def should_close_for_market_end(
    self, current_price: float, avg_price: float, now: datetime | None = None
) -> bool:
    """마감 임박 강제 청산 게이트 (이익 포지션 한정).

    조건: is_near_market_close(now) AND (current−avg)/avg ≥ MIN_PROFITABLE_CLOSE.
    avg_price<=0이면 False. 시간 기반은 이 게이트의 발동 조건뿐.
    """
```

- `should_stop_loss` **미변경**.
- `should_take_profit` **잔존**(라이브 보유 경로에서 호출만 제거, 백테스트/폴백 호환).
- 새 임계는 `RiskManager.__init__`에서 `settings.strategy`(또는 trading)로부터 로드.

## 6. 설정 (`src/config.py`, env, config_overrides.json)

| 키 | 기본값 | 의미 | 튜닝 |
|----|--------|------|------|
| `TRAILING_STOP_ENABLED` | `true` | 기능 on/off (off → +5% 고정 익절 폴백) | env |
| `TRAILING_ACTIVATION_RATIO` | `0.05` | 트레일링 무장 임계 | config_overrides |
| `TRAILING_DRAWDOWN_RATIO` | `0.05` | 고점 대비 매도폭 | config_overrides |
| `MIN_PROFITABLE_CLOSE` | `0.015` | 마감 청산 최소 수익률 | config_overrides |

- `_env_float`/`_env_bool` 헬퍼 패턴을 따른다. 네 키 모두 `StrategySettings` dataclass에
  `take_profit_ratio` 인접 위치로 추가한다(청산/이익실현 파라미터는 strategy 측에 응집).
  `RiskManager.__init__`은 이들을 `settings.strategy`에서 로드한다.
- 기본값 ±50% 범위는 BRIDGE_SPEC 자동 튜닝 허용 범위로 자연스럽게 들어간다.

## 7. 고점(peak) 보존 — 핫패스 동기 DB 0개

공유 Postgres 락 고갈 이력을 고려해 사이클 핫패스에 동기 DB 쿼리를 추가하지 않는다.

- **인메모리 dict** `engine._peak_prices: dict[str, float]`가 핫패스 단일 소스.
  각 보유 종목 평가 시작에서 `peak = max(peak.get(code, seed), current_price)`로 갱신.
  - seed(최초 관측/0·NULL): `max(avg_price, current_price)`.
- **시작 시 시드**: `pre_market()`에서 `portfolios.peak_price`를 1회 배치 read 하여 dict 시드.
  재시작/장 간에도 진짜 고점 복원. (기존 `_daily_cache.clear()` 등 초기화 블록 근처)
- **비동기 영속화**: 이미 매 사이클 호출되는 `_enqueue_sync_portfolio(balance)` →
  `_sync_portfolio`(async 워커) 경로에 `peak_price`를 함께 적재. 핫패스 추가 동기 쿼리 없음.
  영속값은 최대 1사이클 지연 — 허용.
- **포지션 라이프사이클**: 신규 매수 시 해당 코드 seed 재설정(`max(avg, current)`),
  전량 청산 시 dict·DB(`peak_price`)에서 제거(또는 0). `_sync_portfolio`가 잔고 기준으로
  포지션 목록을 동기화하므로 사라진 종목의 peak도 함께 정리.

## 8. DB 변경

- **alembic 마이그레이션 1건**:
  - `portfolios.peak_price` 컬럼 추가 (`Double`, nullable, 기본 NULL).
  - `SellReason` PG enum에 값 추가: `ALTER TYPE sell_reason_enum ADD VALUE 'TRAILING_STOP'`,
    `... ADD VALUE 'MARKET_CLOSE'` (PG는 enum 값 추가에 `ADD VALUE` 사용, 트랜잭션 제약 주의).
- `src/db/models.py`: `Portfolio.peak_price` 매핑, `SellReason`에 `TRAILING_STOP`/`MARKET_CLOSE` 추가.
- `src/db/repository.py`: `PortfolioRepository` upsert/sync에 `peak_price` 반영. `pre_market`
  시드용 조회(전 포지션 peak_price) 메서드 추가.
- `src/engine.py` `_SELL_REASON_MAP`: `"트레일링" → SellReason.TRAILING_STOP`,
  `"마감청산" → SellReason.MARKET_CLOSE` 매핑 추가.

## 9. 테스트

**단위 (분리)**
- `should_trailing_stop`: 미무장(고점이 활성화 임계 미만)→False / 무장+되돌림 미달→False /
  무장+되돌림 경계 도달→True / avg·peak ≤0 가드.
- `should_close_for_market_end`: 마감 전(now 주입)→False / 마감 임박+이익 미달→False /
  마감 임박+이익 충족→True / 손실 포지션→False / avg ≤0 가드.

**엔진 통합**
- 트레일링 발동(무장 후 되돌림) → `_execute_sell(reason="트레일링")`.
- 트레일링 미발동(데드존/미무장) → 매도 없음.
- 마감 게이트 발동(이익 포지션) → `_execute_sell(reason="마감청산")`, 손실 포지션은 미발동.
- 우선순위: 손절 > 마감게이트 > 트레일링 > 전략매도 (각 1건 검증).
- 일봉 없는 ETN 경로(`_evaluate_held_without_daily`)에서도 트레일링·게이트 동작.
- peak 시드(`pre_market`이 portfolios.peak_price로 dict 시드) / 영속화(sync 페이로드에 peak 포함).
- `TRAILING_STOP_ENABLED=false` 폴백 시 기존 익절 경로 동작.

**검증 명령**: `pytest tests/`, `python -m mypy src/`, `ruff check src/`.

## 10. 리스크 / 주의

- **PG enum `ADD VALUE`**: 일부 PG/트랜잭션 모드에서 같은 트랜잭션 내 즉시 사용 제약이
  있다. 마이그레이션에서 enum 추가와 사용을 분리하거나 autocommit 처리 검토.
- **마감 게이트와 트레일링 동시 충족**: 우선순위(게이트가 트레일링보다 위)로 결정적 처리.
- **peak 영속 지연(1사이클)**: 재시작 직후 첫 사이클은 DB 시드값 사용 → 그 사이 신고점은
  다음 사이클에 반영. 허용 가능한 수준.
- **운영자 액션**: 배포 후 `alembic upgrade head` + `com.kis.autotrader` 재시작 필요.
