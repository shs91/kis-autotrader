# 일봉 데이터 조회량 부족 수정 — MACD 전략 데이터 요구량 미충족

## 메타데이터
- 작성: Cowork
- 일자: 2026-04-20
- 상태: implemented
- 우선순위: critical
- 카테고리: bug_fix
- 관련파일: src/api/quote.py, src/engine.py

## 현상 분석

### confidence=0 근본 원인 특정 (5일간 지속)

04-16부터 5일간 4개 서브전략(MA, RSI, MACD, Bollinger)이 7종목 × 2,155사이클에서 전부 HOLD confidence=0을 반환하고 있다. 코드 분석을 통해 원인을 특정했다.

**MACD 전략 — 데이터 부족 가드 상시 진입:**

| 전략 | 최소 필요 행 수 | 산식 | 코드 위치 |
|------|-----------------|------|-----------|
| MA(5/20) | 21 | `long_period + 1` | `moving_average.py:83-84` |
| RSI(14) | 15 | `period + 1` | `rsi.py:88-89` |
| **MACD(12,26,9)** | **36** | `slow + signal + 1 = 26+9+1` | `macd.py:55-56` |
| Bollinger(20) | 21 | `period + 1` | `bollinger.py:52` |

`src/api/quote.py`의 `get_daily_price()` 함수는 KIS API `inquire-daily-price` (FHKST01010400) 엔드포인트를 호출하는데, 조회 날짜 범위를 지정하지 않아 API 기본값(약 30건)만 반환된다.

**결과**: MACD는 36행이 필요하지만 ~30행만 수신 → `macd.py:56-70`의 가드 분기에서 `"데이터 부족"` HOLD confidence=0 반환 → 앙상블에서 MACD가 항상 HOLD로 투표.

**MA, RSI, Bollinger는 왜 함께 confidence=0인가:**

- MA(5/20): 21행을 겨우 통과하지만, 일봉 기준 교차 이벤트가 극히 드물어 대부분 "교차 미발생" HOLD confidence=0
- RSI(14): 데이터가 부족하면 변동성이 정확히 계산되지 않으며, 30~70 정상 범위에 있을 확률이 높아 "정상 범위" HOLD confidence=0
- Bollinger(20): 일봉 ~30행에서 20행 윈도우는 통계적으로 불안정하며, 밴드 내부에 있을 확률이 높아 "밴드 내" HOLD confidence=0

**데이터를 충분히 확보하면** MACD가 작동하고, 다른 3개 전략도 더 정확한 지표값을 기반으로 비영 confidence를 반환할 가능성이 높아진다.

### engine.py의 일봉 캐시 메커니즘 확인

`engine.py:156-186`의 `_get_daily_df()`는 당일 1회만 API를 호출하고 캐시하여 종일 재사용한다. 이 캐시 로직 자체는 정상이나, 원천 데이터가 ~30행으로 부족한 것이 문제다.

## 제안 내용

`get_daily_price()`에 조회 시작일(`FID_INPUT_DATE_1`)과 종료일(`FID_INPUT_DATE_2`)을 명시하여 **최근 100 거래일분 데이터**를 요청한다.

### 근거

1. MACD(26,9)의 최소 요구량 36행 대비 충분한 마진(100행)을 확보한다.
2. KIS API `FHKST01010400` 엔드포인트는 `FID_INPUT_DATE_1`, `FID_INPUT_DATE_2` 파라미터를 지원한다.
3. 추가 API 호출 없이 기존 1회 호출에서 파라미터만 추가하므로 Rate Limit 영향 없다.
4. 100행은 약 5개월분 일봉으로, 향후 장기 이동평균(60일) 전략 추가 시에도 여유가 있다.
5. engine.py의 최소 데이터 가드도 21 → 36으로 상향하여 MACD 최소 요구량을 엔진 레벨에서 보장한다.

## 변경 스펙

### 파일별 변경사항

- `src/api/quote.py`: `get_daily_price()` 메서드에 날짜 범위 파라미터 추가

**변경 전** (L160-165):
```python
params = {
    "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD": stock_code,
    "FID_PERIOD_DIV_CODE": period,
    "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
}
```

**변경 후**:
```python
from datetime import date, timedelta

end_date = date.today()
start_date = end_date - timedelta(days=150)  # 약 100 거래일 확보

params = {
    "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD": stock_code,
    "FID_INPUT_DATE_1": start_date.strftime("%Y%m%d"),
    "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
    "FID_PERIOD_DIV_CODE": period,
    "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
}
```

> `timedelta(days=150)`은 캘린더 150일 ≈ 거래일 100일(주말·공휴일 제외)로, MACD(36) + 볼린저(21) + 충분한 마진을 확보한다.

- `src/engine.py`: `_get_daily_df()`의 최소 데이터 가드를 21 → 36으로 상향

**변경 전** (L174):
```python
if len(daily_prices) < 21:
```

**변경 후**:
```python
if len(daily_prices) < 36:
```

### 추가 테스트

- `tests/test_api/test_quote.py`: `get_daily_price` mock 응답에 날짜 파라미터가 포함되는지 확인하는 assertion 추가. 기존 테스트의 mock 응답 행 수가 36 미만이면 36 이상으로 조정.
- `tests/test_engine_db_integration.py`: `_get_daily_df`의 최소 가드가 36인지 확인하는 테스트 추가 (선택).

### 변경 파일 수 (2~3개)
1. `src/api/quote.py` — 날짜 범위 파라미터 추가
2. `src/engine.py` — 최소 데이터 가드 21 → 36
3. `tests/test_api/test_quote.py` — mock 응답 조정 (필요 시)

## 기대 효과

- **MACD 전략 활성화**: 36행 이상 데이터 확보로 MACD 지표가 정상 계산됨. `guard_triggered=True` → `False`
- **전체 앙상블 품질 향상**: 100행 데이터로 MA/RSI/Bollinger도 더 정확한 지표값 계산. confidence > 0인 비율 증가 예상
- **BUY 시그널 복원**: MACD histogram 교차, RSI 과매도, 골든크로스 등이 정상 감지되면 앙상블에 BUY 투표가 유입되어 매매 교착 상태 해소
- **정량적 추정**: MACD 활성화만으로 앙상블 4전략 중 최소 1개가 비영 신호를 출력, HOLD 과반 가드를 통과하는 시그널이 발생할 가능성 증가
- **API 비용 영향 없음**: 동일 엔드포인트에 파라미터만 추가하므로 API 호출 횟수 증가 없음

## 롤백

`src/api/quote.py`에서 `FID_INPUT_DATE_1`, `FID_INPUT_DATE_2` 파라미터를 제거하고, `src/engine.py`의 가드를 36 → 21로 복원하면 원래 동작으로 돌아간다.

```python
# quote.py — 날짜 파라미터 2줄 제거, date import 제거
# engine.py — 36을 21로 변경
```
