# 일봉 조회 엔드포인트 교체 — `inquire-daily-itemchartprice`로 60건 데이터 실제 확보 + MACD 정상 가동

## 메타데이터
- 작성: Cowork (주말 리뷰 2026-W20)
- 일자: 2026-05-16
- 상태: implemented
- 우선순위: high
- 카테고리: bug_fix
- 관련파일: src/api/quote.py, src/engine.py, tests/test_api/test_quote.py
- 선행 제안서: `2026-05-09_daily-quote-pagination-60days.md` (구현됐으나 미달성 — 본 제안서가 후속)

## 현상 분석

### 정량 근거 (W20 데이터)

2026-05-11에 일봉 페이지네이션 60일 제안서가 구현된 이후에도 5/15 SIGNAL_SKIP 메트릭 표본의 `vote_meta.votes` 분석 결과:

- 전 종목·전 사이클에서 `series_len: 30` 그대로 유지
- MACD 투표: `guard_reason: "insufficient_length"`, `guard_triggered: true` 지속
- W19 리포트의 "MACD 영구 비활성화" 문제가 W20에도 완전히 동일하게 재현됨

즉, **페이지네이션 코드는 적용됐으나 실제로 30건 초과 응답을 받지 못한다.**

### 근본 원인

`src/api/quote.py:144`의 `get_daily_price()`는 페이지네이션 루프를 도는 구조다(`max_pages = (lookback_days // 30) + 2`, 페이지마다 `page_start = page_end - 150일`로 윈도우 이동). 그러나 호출하는 엔드포인트는 **`/uapi/domestic-stock/v1/quotations/inquire-daily-price`** (DAILY_PRICE_PATH)이다.

KIS OpenAPI 명세상 `inquire-daily-price`(`FHKST01010400`)는 다음 특성을 갖는다:

1. 응답이 **항상 최근 30거래일 고정** (요청 일자 파라미터를 사실상 무시)
2. `FID_INPUT_DATE_1`(시작일)/`FID_INPUT_DATE_2`(종료일) 파라미터가 명세에 있으나 응답 범위 변경에 사용 불가
3. 결과적으로 페이지 2번째 호출이 첫 페이지와 동일 데이터를 반환 → 코드가 `dt in seen_dates`로 모두 스킵 → `len(output_list) < 30` 조건도 만족하지 않으나 신규 항목이 0이라 `oldest_date_str` 갱신 없이 루프 종료

KIS는 동일 정보 조회용으로 별도 엔드포인트 **`/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`** (`FHKST03010100`)를 제공하며, 이쪽은:

- **응답 최대 100건**까지 가능 (`FID_INPUT_DATE_1`/`FID_INPUT_DATE_2` 기간 지정 작동)
- 일/주/월/년 구분(`FID_PERIOD_DIV_CODE`) 동일 지원
- 수정주가 반영 옵션(`FID_ORG_ADJ_PRC`) 동일 지원
- 응답 필드(`stck_bsop_date`, `stck_oprc/hgpr/lwpr/clpr`, `acml_vol`)도 호환 가능

→ 엔드포인트만 교체하면 페이지네이션이 의도대로 동작하며, 1회 호출로 60건+ 확보 가능 (페이지네이션 루프 자체는 옵션으로 유지).

## 제안 내용

`src/api/quote.py`의 일봉 조회를 `inquire-daily-itemchartprice` 엔드포인트로 전환하여 60건 일봉을 실제로 확보한다. MACD를 포함한 4개 전략 앙상블이 정상 가동되도록 한다.

### 효과 시뮬레이션

| 영향 | 변경 전 (W19~W20) | 변경 후 (목표) |
|------|---------|---------|
| 실제 series_len | 30건 고정 | 60건+ |
| MACD 가동 | 0 사이클 (전 시스템 가동 이래) | 매 사이클 정상 평가 |
| 앙상블 동작 전략 | 3 (MA/RSI/Bollinger) | 4 (MACD 포함) |
| RSI 표본 분포 | 38~64 (5/15 SKIP 표본) | 60일 변동으로 임계 도달 빈도 회복 |
| Bollinger 밴드 폭 | 30일 변동 (표현력 부족) | 60일 변동 (안정) |
| KIS API 호출량 | 종목당 일봉 1회 | 종목당 일봉 1회 (페이지네이션 불필요) |

## 변경 스펙

### 파일별 변경사항

**`src/api/quote.py`**:

1. `DAILY_PRICE_PATH` 상수 변경:
   ```python
   DAILY_PRICE_PATH: str = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
   ```

2. `TR_ID_DAILY_PRICE` (또는 동등 변수) 값 변경:
   - 모의: `FHKST03010100` (실전·모의 공통)
   - 환경별 분기는 기존 패턴(`KIS_ENV`) 그대로 사용

3. `get_daily_price()` 본문 수정:
   - 응답 구조가 `output1`(헤더)·`output2`(시세 리스트)로 변경되므로 `response.get("output2", [])`로 파싱
   - `FID_INPUT_DATE_1`/`FID_INPUT_DATE_2`를 실제 기간 지정에 사용(예: 오늘 - `lookback_days*2` ~ 오늘)
   - 페이지네이션 루프는 **단순 1회 호출로 단순화** (`output2`가 최대 100건 반환). 60건 미달 시 추가 호출 1회만 수행하는 fallback 유지.
   - `FID_INPUT_HOUR_1` 등 추가 필수 파라미터가 있다면 docstring과 함께 명시

4. 응답 필드 매핑은 inquire-daily-price와 동일하므로 `_get(item, "STCK_BSOP_DATE")` 등 그대로 유지(소문자 키도 동시 지원하도록 `_get` 헬퍼 점검 필요).

**`src/engine.py`**:

- `_get_daily_df`의 `min_daily_count = settings.strategy.ma_long_period + 2` 유지
- **선택**: MACD 활성화를 강제 검증하려면 본 제안 적용 후 W21 데이터에서 SIGNAL_SKIP의 `series_len`이 ≥ 36으로 변경됨을 확인. 강제 임계 상향은 본 제안서 범위 외(별도 후속 제안서로 분리).

**`tests/test_api/test_quote.py`**:

- 기존 페이지네이션 테스트(60건 확보 케이스)를 `inquire-daily-itemchartprice` 엔드포인트 + `output2` 응답 형태로 재작성
- 신규: `output2`에 60건 응답이 1회 호출로 도착 시 정상 반환 케이스
- 신규: `output2`에 100건 응답이 도착해도 `DailyPriceItem` 파싱이 무결한지 확인

### 추가 검증 (구현 후)

- mypy/ruff 통과
- `pytest tests/test_api/test_quote.py -v`
- 통합 테스트(`test_engine_db_integration.py`)에서 `_get_daily_df` 모킹이 60건 반환 시 정상 동작 확인
- **운영 검증 (W21 첫 영업일 5/18 월요일)**:
  - `system_metrics`에서 `metric_type='SIGNAL_SKIP'` detail의 `vote_meta.votes[*].series_len`이 ≥ 60으로 변경됨을 확인
  - MACD 투표의 `guard_triggered`가 false로 전환됨을 확인
  - SIGNAL_SUMMARY의 buy_count/sell_count 분포 변화 모니터링 (시그널 다양성)

## 기대 효과

1. **MACD 정상 가동** — 시스템 가동 이래 첫 정상 평가. 앙상블이 설계대로 4전략 가중투표로 작동.
2. **RSI/Bollinger 표현력 회복** — 60일 변동 범위에서 임계 도달 빈도 상승, HOLD 우세 구조 완화.
3. **시그널 다양성 증가** — 단일 전략 동시 오판 위험 감소. W19 리포트 "중기 아키텍처 논의 §1"의 핵심 병목 해소.
4. **act_rate / avg_confidence 안정화 기여** — MACD가 합류하면 신뢰도 가중 평균이 변동. W21 데이터로 추가 튜닝 여부 결정.

## 리스크 및 롤백

### 리스크

- **응답 구조 차이**: `inquire-daily-itemchartprice`는 `output1`(헤더)·`output2`(시세) 이중 구조. 파싱 오류 시 일봉 조회 전체가 실패할 수 있음 → **응답 검증 + fallback 가드 필수** (응답이 비거나 키가 없으면 기존 엔드포인트로 1회 재시도 또는 빈 리스트 반환).
- **TR_ID 차이**: 모의/실전 환경별 TR_ID 값을 정확히 매핑해야 함. 잘못 매핑 시 401 또는 EGW00001류 에러.
- **API 호출량**: 단일 호출 1회로 60건 확보되므로 페이지네이션 대비 호출량이 줄어듦 — 위험 아님.

### 롤백

- `DAILY_PRICE_PATH` 상수와 응답 파싱을 W20 상태로 되돌리는 단일 커밋 revert 가능
- 회귀 발생 시 `git restore src/api/quote.py` + 테스트 재실행으로 즉시 복원

## 검증 후 W21 액션

- 본 제안서 효과를 W21 일일 리포트의 "이전 제안서 효과 검증"에서 다음 SQL로 추적:
  ```sql
  SELECT
    detail->'vote_meta'->'votes' AS votes_sample
  FROM system_metrics
  WHERE metric_type = 'SIGNAL_SKIP'
    AND (recorded_at AT TIME ZONE 'Asia/Seoul')::date >= '2026-05-18'
  LIMIT 5;
  ```
  표본의 `series_len`이 60 이상이고 MACD `guard_triggered=false`이면 검증 완료.
- W21 weekly 리포트의 "중기 아키텍처 논의 §1" 항목 close 처리.
