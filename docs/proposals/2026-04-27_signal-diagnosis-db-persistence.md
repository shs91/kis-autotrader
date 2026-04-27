# 시그널 가뭄 진단 정보 DB 적재 — 사이클별 평가 요약을 system_metrics에 기록

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-27
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/engine.py, tests/test_engine_db_integration.py

## 현상 분석

04-24 implemented된 `signal-drought-diagnosis-logging` 제안서는 사이클별 BUY/SELL/HOLD 카운터(`_cycle_buy_count`, `_cycle_sell_count`, `_cycle_hold_count`, `_cycle_max_confidence`)를 추가하고 사이클 종료 직전에 평가 요약을 출력하도록 했다. 그러나 출력 경로가 `logger.info()`(파일 로그) 한 곳뿐이어서, **DB 분석으로는 시그널 가뭄 원인을 추적할 수 없는 상태**가 유지되고 있다.

### 04-24 ~ 04-27 데이터 (DB 스코프)

| 항목 | 04-24 | 04-25 (토) | 04-26 (일) | 04-27 (오늘) |
|------|-------|-----------|-----------|--------------|
| 사이클 시작 | 57 | (휴장) | (휴장) | 1,754 |
| 시그널 (전 유형) | 0 | 0 | 0 | 0 |
| 매매 | 0 | 0 | 0 | 0 |
| 스크리닝 | 30 | 30 | 30 | 147 |

`signals` 테이블 04-24 이후 누계 0건. `event_logs`에는 trade INFO 4건만 존재. 즉 **DB에는 진단 데이터가 전혀 없다**. 코드(`src/engine.py:393~404`)에서 `total_evaluated > 0`일 때 `logger.info(...)`로 사이클별 요약을 출력하지만, 이 정보는 파일에만 남아 SQL 분석에 활용할 수 없다.

### 영향
- 04-24 6개 제안서 패키지 적용 후 **시그널 0건의 원인을 SQL로 진단 불가**.
- 매매 후보 풀 통과 종목 중 4개 서브전략(MA·RSI·MACD·Bollinger)이 어느 단계에서 HOLD를 반환하는지, max_confidence 분포가 어떤지를 파일 로그 grep 외에 분석할 수 없다.
- 후속 파라미터 튜닝 제안의 근거 데이터가 부재.

## 제안 내용

사이클 종료 직전(`src/engine.py:393~404`) `logger.info()` 호출 다음에 `SystemMetricRepository.record_metric()`을 호출하여 동일 정보를 `system_metrics` 테이블에 `metric_type='SIGNAL_SUMMARY'`로 기록한다. `system_metrics.metric_type`은 `String(50)`이며 enum 제약이 없어 신규 값 추가가 자유롭다(`src/db/models.py:333`). 스키마 변경(=alembic 마이그레이션) 불필요.

`detail` JSONB 컬럼에는 사이클 번호, 평가 종목 수, BUY/SELL/HOLD 카운트, max_confidence, 스크리닝 종목 수를 함께 기록한다.

## 변경 스펙

### 파일별 변경사항

#### `src/engine.py`

기존 (L390~404):

```python
total_evaluated = (
    self._cycle_buy_count + self._cycle_sell_count + self._cycle_hold_count
)
if total_evaluated > 0:
    logger.info(
        "사이클 #%d 전략 요약: 평가 %d종목, BUY %d / SELL %d / HOLD %d, "
        "max_confidence=%.3f, 스크리닝 %d종목",
        self._cycle_count,
        total_evaluated,
        self._cycle_buy_count,
        self._cycle_sell_count,
        self._cycle_hold_count,
        self._cycle_max_confidence,
        len(self._screened_codes),
    )
```

변경 후:

```python
total_evaluated = (
    self._cycle_buy_count + self._cycle_sell_count + self._cycle_hold_count
)
if total_evaluated > 0:
    logger.info(
        "사이클 #%d 전략 요약: 평가 %d종목, BUY %d / SELL %d / HOLD %d, "
        "max_confidence=%.3f, 스크리닝 %d종목",
        self._cycle_count,
        total_evaluated,
        self._cycle_buy_count,
        self._cycle_sell_count,
        self._cycle_hold_count,
        self._cycle_max_confidence,
        len(self._screened_codes),
    )
    self._record_metric("SIGNAL_SUMMARY", {
        "cycle": self._cycle_count,
        "evaluated": total_evaluated,
        "buy_count": self._cycle_buy_count,
        "sell_count": self._cycle_sell_count,
        "hold_count": self._cycle_hold_count,
        "max_confidence": round(self._cycle_max_confidence, 4),
        "screened_count": len(self._screened_codes),
    })
```

> `_record_metric()`은 이미 engine.py 내에서 `ERROR`/`API_LIMIT` 등에 사용 중이므로 동일 패턴을 따른다. `metric_type`이 String(50)이라 신규 값 'SIGNAL_SUMMARY' 추가에 스키마 변경이 필요 없다.

### 추가 테스트

`tests/test_engine_db_integration.py`:
- 사이클 1회 실행 후 `system_metrics` 테이블에 `metric_type='SIGNAL_SUMMARY'` 행이 1개 추가되는지 검증.
- `detail` JSON에 `cycle`, `evaluated`, `buy_count`, `sell_count`, `hold_count`, `max_confidence`, `screened_count` 키가 모두 존재하는지 검증.
- `total_evaluated == 0` 케이스에서는 SIGNAL_SUMMARY가 기록되지 않는지 검증(기존 if 가드 유지).

## 기대 효과

- 다음 영업일부터 `system_metrics`에 사이클별 BUY/SELL/HOLD/max_confidence 시계열이 적재된다.
- 다음 일일 분석에서 다음 SQL이 가능해진다:
  ```sql
  SELECT
    AVG((detail->>'max_confidence')::float) AS avg_max_conf,
    SUM((detail->>'hold_count')::int) AS total_holds,
    SUM((detail->>'buy_count')::int) AS total_buys
  FROM system_metrics
  WHERE metric_type = 'SIGNAL_SUMMARY'
    AND (recorded_at AT TIME ZONE 'Asia/Seoul')::date = ...;
  ```
- HOLD가 어떤 max_confidence 분포를 갖는지 → MIN_CONFIDENCE 추가 조정 근거.
- 평가 종목 수 / 스크리닝 종목 수 → 매매 후보 풀이 0인지 확인 가능.
- **시그널 가뭄 원인을 SQL 한 줄로 분리할 수 있어 후속 파라미터 튜닝 제안의 근거 데이터가 확보**된다.

정량 목표:
- 익일 리포트에서 `SELECT COUNT(*) FROM system_metrics WHERE metric_type='SIGNAL_SUMMARY' AND (recorded_at AT TIME ZONE 'Asia/Seoul')::date = today` 결과 ≥ 100건 이상.
- avg max_confidence가 MIN_CONFIDENCE(0.08) 미만인지 또는 이상인지 정량 판정 가능.

## 롤백

`src/engine.py`에서 추가된 `self._record_metric("SIGNAL_SUMMARY", {...})` 호출 7줄을 제거. `system_metrics`에 기록된 `SIGNAL_SUMMARY` 행은 분석용 데이터이므로 별도 정리 불필요(누적되어도 시스템 동작에 영향 없음).

테스트 변경 분도 git 단위로 함께 원복.
