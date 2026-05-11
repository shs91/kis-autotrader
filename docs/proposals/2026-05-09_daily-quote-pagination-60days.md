# 일봉 조회 페이지네이션 — 60일 데이터 확보로 MACD 활성화 및 지표 안정성 향상

## 메타데이터
- 작성: Cowork
- 일자: 2026-05-09
- 상태: implemented
- 우선순위: high
- 카테고리: performance
- 관련파일: src/api/quote.py, src/engine.py

## 현상 분석

### 정량 근거 (W19 데이터)

- KIS 일봉 조회(FHKST01010400)가 매 호출 30건만 반환
- W19 SIGNAL_SKIP 메트릭의 vote_meta 분석 결과, **모든 사이클에서 MACD 투표가 `guard_reason=insufficient_length`로 차단**
  - MACD 필요 데이터: `slow(26) + signal(9) + 1 = 36건`
  - 실제 series_len: 30건 (전 종목 동일)
  - 시스템 가동 이래 MACD가 정상 평가된 사이클 0건
- 앙상블이 사실상 3개 전략(MA/RSI/Bollinger)에만 의존 → 시그널 다양성 부족, 단일 시장 환경 가정에서의 동시 오판 위험
- RSI(14)·Bollinger(20,2.0)도 30일 윈도우에서 임계 도달이 드묾:
  - RSI 표본 38~64 (중립)
  - Bollinger %B 0.07~0.76 (중립)
  - HOLD 우세 구조 → 매매 기회 자체가 희소

### 근본 원인

`src/api/quote.py`의 일봉 조회가 단일 호출만 수행하여 KIS API의 1회 응답 한도(30건)에 묶임. 페이지네이션을 적용하면 다음 영역(start_date/end_date 조정)을 추가 호출로 확보 가능.

## 제안 내용

`src/api/quote.py`의 일봉 조회 함수에 **페이지네이션 루프**를 추가하여 60건(약 3개월 거래일) 이상의 일봉을 확보한다. 옵션으로 `lookback_days` 파라미터를 받아 호출자가 필요량을 지정한다(엔진은 60, 백테스트 등은 더 큼).

### 효과 시뮬레이션

| 영향 | 변경 전 | 변경 후 |
|------|---------|---------|
| MACD 가동 | 0 사이클 | 정상 평가 가능 |
| 앙상블 동작 전략 | 3 (MA/RSI/Bollinger) | 4 (전 전략) |
| RSI 임계 도달 빈도 | 매우 낮음 | 정상 (60일 변동 범위) |
| Bollinger 밴드 폭 | 단기 변동 과잉 반영 | 안정 |
| API 호출량 증가 | — | 일봉 조회당 +1회 (1.x배 수준, 종목별 페이지네이션 캐시 시 무시 가능) |

## 변경 스펙

### 파일별 변경사항

- `src/api/quote.py`:
  - `get_daily_prices(stock_code, period_div, lookback_days=60)` 시그니처 확장 (기본값 60).
  - 내부에서 KIS API의 `FID_INPUT_DATE_1`(시작일)·`FID_INPUT_DATE_2`(종료일) 파라미터를 활용해 30건 단위로 페이지를 끌어오는 루프 구현.
  - 응답을 시간순(과거→현재)으로 병합하고, `lookback_days` 도달 또는 빈 응답 시 종료.
  - 모든 호출은 기존 RateLimiter 경유. 페이지 간 `await asyncio.sleep(0.05)` 등으로 버스트 회피.
  - 메서드 docstring 한글로 갱신.

- `src/engine.py`:
  - L185 부근 `min_daily_count = settings.strategy.ma_long_period + 2` 를 유지하되, MACD 활성화 효과를 측정하기 위해 `min_daily_count = max(min_daily_count, settings.strategy.macd_slow + settings.strategy.macd_signal + 1)`(설정 존재 시) 형태로 상향 검토. 단, 이 변경은 본 제안서 내에서는 **선택 사항**으로 명시하고, 페이지네이션 효과 검증(W20 데이터)을 본 적용 후로 보류.

- `tests/test_api/test_quote.py`:
  - respx로 페이지네이션 응답을 모킹하는 테스트 1건 추가 (60건 확보, 두 번째 페이지 호출, 시간순 병합 확인).
  - 기존 테스트는 시그니처 호환을 위해 `lookback_days=30`로 호출 시 단일 페이지 결과를 반환하도록 패스 유지.

### 추가 검증

- mypy/ruff 통과
- 기존 통합 테스트(`test_engine_db_integration.py`)에서 `_get_daily_df` 모킹이 60건을 반환해도 동작하는지 확인

## 기대 효과

1. MACD가 데이터 부족 가드를 통과하여 매 사이클 정상 평가 → **앙상블 4전략 모두 가동**
2. RSI/Bollinger의 60일 변동 범위가 회복되면서 임계 도달 빈도 상승 → HOLD 비중 완화
3. 시그널 품질 개선으로 W20 이후 평균 신뢰도(현재 0.256) 상승 기대 — 0.30 이상 목표
4. 스크리닝 전환율 0% 장기화의 한 축(전략 평가 표현력 한계) 해소

## 리스크 및 롤백

### 리스크

- API 호출량 증가 — 종목당 일봉 조회가 1회 → 2회. 일일 한도(50,000) 대비 안전 마진 충분 (모의투자 기준 현 수준 ~12,000회/일).
- MACD가 활성화되면 앙상블 가중치 재조정이 필요할 수 있음 — 본 제안서 적용 후 W20 데이터로 별도 평가.

### 롤백

- `get_daily_prices` 시그니처에서 `lookback_days` 기본값을 30으로 되돌리거나 페이지네이션 루프를 단일 호출로 환원.
- 엔진 변경(선택 사항)은 본 제안서에서 적용하지 않음 → 롤백 대상 아님.
