# 일봉 데이터 부족 / 평가 조기 종료 진단 메트릭 추가

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-02
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/engine.py

## 현상 분석

### W18 매매 0건 + 시그널 0건 + SIGNAL_SKIP 0건의 모순

W17(4/20~4/24)부터 W18(4/27~5/2)까지 5주 연속 매매 0건 / 시그널 0건이 지속되고 있다. 04-27 이후 5건의 순차 수정(파이프라인 단절·타임존·재시작·신뢰도 임계값 등)이 적용되었으며, 04-30 타임존 수정 이후 EVAL_TARGETS에 `screening: 10`이 정상 포함됨이 5/1 일간 리포트에서 확인되었다.

그럼에도 불구하고 W18 데이터에서 다음 모순이 관측된다:

| 지표 | 관측치 | 정상이라면 |
|------|--------|-----------|
| EVAL_TARGETS.total | 17/사이클 (스크리닝 10 + watchlist 7) | 17 |
| signals 테이블 적재 | 0건 (5주 연속) | 17 × 사이클수 중 일부 BUY/SELL |
| system_metrics SIGNAL_SKIP | 0건 (W18 전체) | HOLD 시그널마다 1건씩 기록되어야 함 |
| system_metrics SIGNAL_SUMMARY | 0건 | 사이클당 1건씩 적재되어야 함 (04-27 구현) |
| `_cycle_max_confidence` | 0.0 지속 추정 | 평가가 일어났다면 0이 아닌 사이클 존재 가능 |

`_record_signal_skip()`은 `_process_stock()`에서 HOLD 시그널이 반환되었을 때만 호출된다(engine.py:666-671). 즉 SIGNAL_SKIP 0건은 `strategy.analyze(df)` 호출 자체가 거의 일어나지 않았다는 의미다.

### 가설 — `_get_daily_df()`의 36건 임계값에서 전량 조기 종료

`engine.py:180`:
```python
if len(daily_prices) < 36:
    logger.info("[%s] 일봉 데이터 부족 (%d건), 스킵", stock_code, len(daily_prices))
    return None
```

`_process_stock()`은 `_get_daily_df()`가 None을 반환하면 line 604에서 즉시 return하므로:
- 전략 분석(`strategy.analyze`) 호출 안 됨
- 시그널 카운터(`_cycle_buy_count`/`_cycle_hold_count`/`_cycle_max_confidence`) 갱신 안 됨
- `_record_signal_skip()` 호출 안 됨
- signals 테이블 기록 안 됨
- SIGNAL_SUMMARY/SIGNAL_SKIP 메트릭 모두 미적재

이는 W18에서 관측된 모든 모순(EVAL_TARGETS는 17이지만 시그널 0, SIGNAL_SKIP 0, SIGNAL_SUMMARY 0)을 일관되게 설명한다.

### 직접 근거 데이터

- 04-29 일간 리포트: "관심종목 7개 전부 '일봉 데이터 부족 (30건)'으로 스킵" 명시
- 04-29 사이클 1,984회 정상 완료, 시그널 0건 — 평가 자체가 안 일어났을 가능성이 매우 높음
- `_get_daily_df()` 임계값 36 vs 04-29 관측 30건 → 임계값 미달로 watchlist 전량 스킵
- 04-20 "일봉 조회량 부족 수정" 이후에도 30건만 반환되는 종목 존재 → API 측 문제 또는 종목별 상장기간 등 변수 미점검

### 04-27 SIGNAL_SUMMARY 구현이 작동하지 않는 이유

04-27 `signal-diagnosis-db-persistence.md`는 `_run_cycle()` 종료 시점에 사이클 카운터(BUY/SELL/HOLD/max_conf)를 SIGNAL_SUMMARY 메트릭으로 적재하는 구조다. 그러나 평가 자체가 일어나지 않으면 카운터가 모두 0이고, 카운터가 0인 사이클은 적재 분기를 통과하지 않을 가능성이 있다(또는 적재되지만 의미 없는 빈 데이터).

**현재 진단 메트릭은 "시그널이 발생했지만 묻혔을 때"는 추적할 수 있어도, "시그널이 발생할 기회조차 없었을 때"는 침묵한다.**

## 제안 내용

평가 조기 종료(early-return) 시점마다 별도 메트릭을 적재하여, 시그널 가뭄 원인을 데이터로 분리한다. 다음 두 가지를 추가한다:

1. **일봉 데이터 부족 메트릭 (`DAILY_DATA_INSUFFICIENT`)**: `_get_daily_df()`에서 None을 반환할 때마다 종목코드·실제 반환건수·최소요구건수를 메트릭으로 적재.

2. **평가 조기 종료 메트릭 (`EVAL_SKIP`)**: `_process_stock()`이 일봉 부족 외 사유(현재가 조회 실패 등)로 조기 return할 때 사유 코드를 메트릭으로 적재.

이를 통해 "EVAL_TARGETS=17이지만 시그널 0건"의 갭을 정량 추적할 수 있다.

## 변경 스펙

### 파일별 변경사항

#### 1. `src/engine.py` — `_get_daily_df()` 수정

변경 전 (engine.py:178-182):
```python
# API 호출
daily_prices = await self._quote.get_daily_price(stock_code)
if len(daily_prices) < 36:
    logger.info("[%s] 일봉 데이터 부족 (%d건), 스킵", stock_code, len(daily_prices))
    return None
```

변경 후:
```python
# API 호출
daily_prices = await self._quote.get_daily_price(stock_code)
if len(daily_prices) < 36:
    logger.info("[%s] 일봉 데이터 부족 (%d건), 스킵", stock_code, len(daily_prices))
    self._record_metric("DAILY_DATA_INSUFFICIENT", {
        "stock_code": stock_code,
        "returned_count": len(daily_prices),
        "required_count": 36,
        "cycle": self._cycle_count,
    })
    return None
```

#### 2. `src/engine.py` — `_process_stock()`에 EVAL_SKIP 메트릭 추가

변경 전 (engine.py:602-608):
```python
# 1. 일봉 데이터 (캐시 활용)
df = await self._get_daily_df(stock_code)
if df is None:
    return

# 2. 현재가 조회 (실시간)
current = await self._quote.get_current_price(stock_code)
```

변경 후:
```python
# 1. 일봉 데이터 (캐시 활용)
df = await self._get_daily_df(stock_code)
if df is None:
    self._record_metric("EVAL_SKIP", {
        "stock_code": stock_code,
        "skip_reason": "daily_data_insufficient",
        "cycle": self._cycle_count,
    })
    return

# 2. 현재가 조회 (실시간)
current = await self._quote.get_current_price(stock_code)
```

> 주: `DAILY_DATA_INSUFFICIENT`는 캐시 미스 시(API 실제 호출 시점)만 적재되고, `EVAL_SKIP`은 캐시 미스/히트 모두에서 일봉 부족이 확정될 때 적재된다. 두 메트릭은 보완 관계이며 둘 다 적재되는 것이 정상.

### 추가 테스트

`tests/test_engine_db_integration.py`에 다음 케이스 추가:
- `test_daily_data_insufficient_metric_recorded`: `quote.get_daily_price()`를 35건 반환하도록 mock → `_get_daily_df()` 호출 → `record_metric` 큐에 `DAILY_DATA_INSUFFICIENT` 적재 확인
- `test_eval_skip_metric_recorded_on_daily_insufficient`: `_process_stock("000660", ...)` 호출 시 `EVAL_SKIP` 메트릭이 `daily_data_insufficient` 사유로 기록되는지 확인

## 기대 효과

- **시그널 가뭄의 진짜 원인 데이터 확인**: W19 거래일(05-04~05-08) 가동 후 즉시 SQL 분석으로 "EVAL_TARGETS=17 vs 실제 평가 N회"의 차이를 정량 측정 가능.
- **`DAILY_DATA_INSUFFICIENT` 종목별 분포**: 어느 종목이 일봉 부족으로 차단되는지 파악 → API 호출 파라미터·종목 선정 기준 후속 개선 근거 확보.
- **04-27 SIGNAL_SUMMARY의 사각지대 해소**: 평가 자체가 일어나지 않은 사이클도 추적 가능 → 시그널 가뭄 진단의 완전성 확보.
- 매주 W19 이후 주간 리포트의 "스크리닝→평가 전환율" 지표 신설 가능 (EVAL_TARGETS 대비 실제 평가 건수의 비율).

## 롤백

`src/engine.py`의 두 변경(라인 추가)을 `git restore`로 원복. 메트릭 미적재 외 부작용 없음.
