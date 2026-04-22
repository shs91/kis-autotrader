# ScreeningWorker 일봉 조회 메서드명 불일치 수정

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-22
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/worker/screener.py

## 현상 분석

### 스크리닝 전환율 0% — 7일 연속 지속

04-16부터 7일간 스크리닝이 매일 30~145종목을 발굴하지만, `converted_to_trade=True`인 종목이 **단 한 건도 없다**.

| 날짜(KST) | 발굴 | 전환 | 전환율 |
|------------|------|------|--------|
| 04-22 | 143 | 0 | 0.0% |
| 04-21 | 138 | 0 | 0.0% |
| 04-20 | 110 | 0 | 0.0% |
| 04-19 | 30 | 0 | 0.0% |
| 04-18 | 30 | 0 | 0.0% |
| 04-17 | 124 | 0 | 0.0% |
| 04-16 | 145 | 0 | 0.0% |

### 근본 원인 특정

`src/worker/screener.py:133`에서 호출하는 메서드명이 실제 API 클래스에 존재하지 않는다:

**호출 코드** (`src/worker/screener.py:133`):
```python
df = await self._quote.get_daily_prices(
    stock_code=item.stock_code, count=60,
)
```

**실제 메서드** (`src/api/quote.py:143`):
```python
async def get_daily_price(
    self, stock_code: str, period: str = "D", adjusted: bool = True,
) -> list[DailyPrice]:
```

- 호출: `get_daily_prices()` (복수형, `count` 파라미터)
- 실제: `get_daily_price()` (단수형, `count` 파라미터 없음)

이로 인해 **매 종목마다 `AttributeError: 'QuoteAPI' object has no attribute 'get_daily_prices'`** 가 발생한다.

`src/worker/screener.py:147-148`의 `except Exception: logger.debug(...)` 가 이 에러를 무조건 삼키므로:
1. `scored` 리스트가 항상 빈 리스트
2. `top_candidates = self._screener.rank_candidates([])` → 빈 리스트
3. `new_codes` 빈 리스트 → `candidate_set` 빈 집합
4. 모든 종목이 `converted_to_trade=False`로 DB에 기록

### 영향 범위

- **스크리닝 파이프라인 완전 중단**: 단 한 종목도 전략 평가 → 매매 대상 전환이 이루어지지 않음
- **매매 다양성 소실**: 메인 엔진이 워치리스트 7종목만 반복 평가하는 공회전 상태
- **8일째 무거래 직접 원인**: 워치리스트 7종목이 모두 HOLD를 반환하고, 스크리닝 종목이 평가 대상에 유입되지 않아 매매 기회 0

## 제안 내용

1. `get_daily_prices` → `get_daily_price`로 메서드명을 수정한다.
2. `get_daily_price`의 반환 타입은 `list[DailyPrice]`이므로, DataFrame 변환 로직을 추가한다 (메인 엔진의 `_get_daily_df()`와 동일 패턴).
3. `count=60` 파라미터는 `get_daily_price`에 존재하지 않으므로 제거한다. 대신 04-20에 구현된 날짜 범위 파라미터(`FID_INPUT_DATE_1/DATE_2`)가 자동으로 100거래일분 데이터를 가져온다.

## 변경 스펙

### 파일별 변경사항

- `src/worker/screener.py`: L130-137 수정

**변경 전**:
```python
            try:
                df = await self._quote.get_daily_prices(
                    stock_code=item.stock_code, count=60,
                )
                if df is None or df.empty:
                    continue
```

**변경 후**:
```python
            try:
                daily_prices = await self._quote.get_daily_price(item.stock_code)
                if len(daily_prices) < 36:
                    continue

                df = pd.DataFrame(
                    [
                        {"close": p.close_price, "date": p.date}
                        for p in reversed(daily_prices)
                    ]
                )
```

> `reversed(daily_prices)`: KIS API는 최신→과거순으로 반환하므로 시계열 정순으로 변환 (engine.py:181과 동일 패턴).
> `< 36`: MACD(26,9) 최소 요구량 = slow + signal + 1 = 36 (engine.py:174와 동일 가드).

**추가 import** (파일 상단):
```python
import pandas as pd
```

### 변경 파일 수 (1개)
1. `src/worker/screener.py` — 메서드명 수정 + DataFrame 변환 로직 추가

### 추가 테스트 (필요 시)

- 기존 `tests/` 디렉토리에 ScreeningWorker 단위 테스트가 있는 경우, mock 대상 메서드명을 `get_daily_price`로 갱신.
- 없는 경우, `tests/test_strategy/test_screener_worker.py`에 `get_daily_price` mock + DataFrame 변환 검증 테스트 추가 권장.

## 기대 효과

- **스크리닝 파이프라인 정상화**: `get_daily_price` 호출 성공 → 전략 분석 실행 → 종합 점수 산출 → `converted_to_trade=True` 종목 발생
- **전환율 복원**: strategy_score=0이더라도 volume_rank(0.2) + change_rate(0.3) 합산으로 최대 0.5점 가능. `min_score=0.25` 기준 상위 종목은 통과 가능. strategy가 BUY를 반환하면 추가 0.5점 가산.
- **매매 교착 해소**: 스크리닝 종목이 메인 엔진의 평가 대상(`_screened_codes`)에 유입되면, 7종목 이상의 다양한 종목에서 매매 시그널 발생 가능성 대폭 증가.
- **정량적 추정**: 오늘 기준 143종목 중 volume_rank + change_rate만으로 점수 ≥ 0.25인 종목은 상위 30~50% 수준 → 약 40~70종목이 전략 평가를 거쳐 10종목(max_screened)까지 선별될 것으로 예상.

## 롤백

`src/worker/screener.py`의 변경 부분을 원래 코드로 복원한다:

```python
# 변경 후 코드를 아래로 복원:
df = await self._quote.get_daily_prices(
    stock_code=item.stock_code, count=60,
)
if df is None or df.empty:
    continue
```

단, 원래 코드 자체가 버그이므로 롤백 시 스크리닝 전환율이 다시 0%로 돌아간다.
