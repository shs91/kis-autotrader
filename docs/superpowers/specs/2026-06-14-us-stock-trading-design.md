# 미국 주식 매매 확장 설계 (멀티마켓 추상화)

- **작성일**: 2026-06-14
- **브랜치**: `feat/us-stock-trading`
- **상태**: design (승인됨, 구현 계획 대기)
- **목표**: 기존 KIS 국내(KRX) 자동매매 시스템을 **미국 주식 정규장 자동매매**까지 확장한다. 국내와 동일한 풀 파이프라인(스크리닝→전략→자동매매→리스크→알림)을 미국에도 적용하되, 시장 종속 결합을 **실용적 2-시장 추상화**로 분리한다.

---

## 1. 확정된 결정 사항

| # | 항목 | 결정 | 근거 |
|---|------|------|------|
| 1 | 범위 | 국내와 동일한 **풀 파이프라인** | 사용자 결정 |
| 2 | 거래 세션 | 미국 **정규장만** (한국시간 야간 23:30~06:00, DST 22:30~05:00) | 사용자 결정. 주간거래(데이마켓)는 비범위 |
| 3 | 결제/통화 | **원화 통합증거금** (자동환전) | 사용자 결정 + 검증: 별도 환전 API 불필요, 주문만으로 자동환전 |
| 4 | 운영 구조 | **B안** — 공유코드 + 분리프로세스(`MARKET` env) + 공유 PostgreSQL(`market` 컬럼 구분) | 시간대 비중첩 + 과거 공유DB 락 사고(2026-05-20) → 장애 격리 우선 |
| 5 | 종목 유니버스 | **KIS 해외 순위 API** (거래량/등락율/조건검색) | 사용자 결정 + 검증: 해당 API 존재 확인 |
| 6 | 추상화 깊이 | **실용 2-시장** (MarketProfile + Protocol 구현체). 9개 이음새 풀세트는 비채택(YAGNI) | 사용자 결정 |
| 7 | 검증 전략 | **처음부터 실전 소액** (미국은 모의 생략, 실전 appkey). 국내는 `virtual` 유지 | 사용자 결정 + 모의 해외 시세/순위 미지원 가능성 회피 |

### 핵심 함의
- **시간대 비중첩**: 국내(주간)와 미국 정규장(야간)이 겹치지 않음 → 분리 프로세스가 자연스럽고 rate limit 충돌 없음.
- **야간 무인 + 실전 자금**: 안전장치(킬스위치 등 Phase 0 6종)가 미국 매매 진입의 **협상 불가 전제**.
- **분리 프로세스로 시장별 환경 자연 분리**: 주간 `MARKET=KRX, KIS_ENV=virtual` / 야간 `MARKET=US, KIS_ENV=real`.

---

## 2. 검증된 KIS 해외주식 API 사실

> 출처: `koreainvestment/open-trading-api` 공식 예제 + KIS Developers 포털. confidence는 워크플로 검증 기준.

### 2.1 주문 / 잔고 (`/uapi/overseas-stock/v1/trading/...`)

| 기능 | 엔드포인트 | 미국 TR_ID (실전/모의) | confidence |
|------|-----------|----------------------|-----------|
| 매수 | `/trading/order` | `TTTT1002U` / `VTTT1002U` | high |
| 매도 | `/trading/order` | `TTTT1006U` / `VTTT1006U` | high |
| 정정/취소(정규장) | `/trading/order-rvsecncl` | `TTTT1004U` / `VTTT1004U` | **medium — 구현 시 포털 재확인** |
| 잔고(통화별 외화) | `/trading/inquire-balance` | `TTTS3012R` / `VTTS3012R` | high |
| 체결기준 현재잔고(원화/외화) | `/trading/inquire-present-balance` | `CTRP6504R` / `VTRP6504R` | high |
| 매수가능금액 | `/trading/inquire-psamount` | `TTTS3007R` / `VTTS3007R` | high |

- **주문 바디 핵심 필드**: `CANO`, `ACNT_PRDT_CD`, `OVRS_EXCG_CD`(거래소), `PDNO`(심볼 예 `AAPL`), `ORD_QTY`, `OVRS_ORD_UNPR`(외화 단가, 시장가는 0), `ORD_SVR_DVSN_CD`(0), `ORD_DVSN`(주문구분), `SLL_TYPE`(매도 시).
- **주문구분(ORD_DVSN)**: 미국 매수는 `00`(지정가)만 가능. 매도는 `00`/`31`(MOO)/`32`(LOO)/`33`(MOC)/`34`(LOC) 가능. → 기본 전략은 **지정가**로 구현.
- **통합증거금**: 원화로 매수주문 가능, 결제일 자동환전(가환전→실시간환전). **Open API에 별도 FX 엔드포인트 호출 불필요**.
- **잔고 응답(output1)**: `ovrs_pdno`, `ovrs_cblc_qty`, `ord_psbl_qty`, `pchs_avg_pric`, `frcr_pchs_amt1`, `ovrs_stck_evlu_amt`, `now_pric2`, `frcr_evlu_pfls_amt`, `evlu_pfls_rt`, `tr_crcy_cd`.

### 2.2 시세 (`/uapi/overseas-price/v1/quotations/...`)

| 기능 | 엔드포인트 | TR_ID | 파라미터 |
|------|-----------|-------|----------|
| 현재가 | `/quotations/price` | `HHDFS00000300` | `AUTH`, `EXCD`, `SYMB` |
| 현재가 상세 | `/quotations/price-detail` | `HHDFS76200200` | `AUTH`, `EXCD`, `SYMB` |
| 기간별시세(일/주/월) | `/quotations/dailyprice` | `HHDFS76240000` | `EXCD`, `SYMB`, `GUBN`(0일/1주/2월), `BYMD`, `MODP` |
| 분봉 | `/quotations/inquire-time-itemchartprice` | `HHDFS76950200` | `EXCD`, `SYMB`, `NMIN`, `PINC`, `NREC`(≤120) |
| 호가 | `/quotations/inquire-asking-price` | `HHDFS76200100` | `AUTH`, `EXCD`, `SYMB` |

- **현재가 응답 필드**: `rsym`, `zdiv`(소수점 자릿수), `base`(전일종가), `last`(현재가), `sign`, `diff`, `rate`, `tvol`, `tamt`, `ordy`.
- **일봉 응답(output2)**: `xymd`(일자), `clos`(종가), `open`, `high`, `low`, `tvol`, `tamt`, `sign`, `diff`, `rate`.
- **가격은 문자열 + `zdiv`** → **Decimal 파싱** 필수.

### 2.3 순위 / 유니버스 (`/uapi/overseas-stock/v1/ranking/...`)

| 기능 | 엔드포인트 | TR_ID | 핵심 파라미터 |
|------|-----------|-------|--------------|
| 거래량순위 | `/ranking/trade-vol` | `HHDFS76310010` | `EXCD`, `NDAY`, `VOL_RANG`, `PRC1/PRC2` |
| 등락율순위 | `/ranking/updown-rate` | `HHDFS76290000` | `EXCD`, `NDAY`, `GUBN`(0하락/1상승), `VOL_RANG` |
| 가격급등락 | `/ranking/price-fluct` | `HHDFS76260000` | `EXCD`, `GUBN`, `MINX`, `VOL_RANG` |
| 조건검색(멀티팩터) | `/quotations/inquire-search` | `HHDFS76410000` | `EXCD` + 가격/등락율/시총/거래량/EPS/PER 조건 |

- **종목마스터**: `https://new.real.download.dws.co.kr/common/master/{거래소}mst.cod.zip` (`nasmst`/`nysmst`/`amsmst`, CP949, 탭구분).
- **미국 심볼**: 알파벳 1~5자, 클래스주는 점 표기(`BRK.B`) — 정규화 시 점 보존.

### 2.4 거래소코드 이중 체계 (중요)

| 거래소 | 시세 `EXCD` (3자리) | 주문 `OVRS_EXCG_CD` (4자리) |
|--------|---------------------|------------------------------|
| 나스닥 | `NAS` | `NASD` |
| 뉴욕 | `NYS` | `NYSE` |
| 아멕스 | `AMS` | `AMEX` |

→ **시세↔주문 코드 매핑 변환 필수** (MarketProfile이 보유). `US 전체` 일괄 조회 불가 — EXCD별 반복 호출.

### 2.5 환경 도메인
- 실전: `https://openapi.koreainvestment.com:9443`
- 모의: `https://openapivts.koreainvestment.com:29443` (미국은 실전 사용)

---

## 3. 아키텍처 — 실용 2-시장 추상화

```
                    ┌─────────────────────────────────────┐
   MARKET=KRX  ───▶ │  MarketProfile (frozen dataclass)    │ ◀─── MARKET=US
   KIS_ENV=virtual  │  통화·소수점·거래시간·거래소코드맵     │      KIS_ENV=real
                    │  스크리닝/리스크 파라미터·순위 소스     │
                    │  자격증명 키·base_url·rate_limit      │
                    └──────────────┬──────────────────────┘
                                   │ 주입
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
  QuoteProvider(Protocol)   OrderProvider(Protocol)   AccountProvider(Protocol)
  ├ DomesticQuoteAPI        ├ DomesticOrderAPI         ├ DomesticAccountAPI
  └ OverseasQuoteAPI        └ OverseasOrderAPI         └ OverseasAccountAPI
        └──────────── engine.py / scheduler ── MarketProfile 1개로 구동 ──┘
        (strategy/screener는 지금처럼 데이터를 인자로 받음 — 인터페이스 최소 변경)
```

### 3.1 `MarketProfile` (신규 `src/market/profile.py`)
`@dataclass(frozen=True)` 패턴. 시장별 메타데이터를 한 곳에 집약:
- `market_code: str` (`KRX` / `US`)
- `currency: str`, `currency_symbol: str`, `price_precision: int` (KRX=0, US=2)
- `exchanges: tuple[str, ...]` 및 시세/주문 거래소코드 매핑 dict
- `trading_hours`: pre/open/close/post/cutoff/summary 시각 + 타임존
- `screening_params` / `risk_params` (시장별 값)
- `universe_source`: 순위 데이터소스 식별자
- `credentials_env_prefix`: 자격증명 키 prefix (`KIS_` / `KIS_US_`)

### 3.2 Provider Protocol (신규 `src/api/protocols.py`)
국내/해외는 파라미터·응답 체계가 완전히 다르므로 `if market:` 분기 대신 **인터페이스 + 구현체 2벌**:
- `QuoteProvider`: `get_current_price`, `get_daily_price`, `get_minute_price`, `get_ranking`
- `OrderProvider`: `buy`, `sell`, `modify`, `cancel`
- `AccountProvider`: `get_balance`, `get_executions`, `get_buyable_amount`

기존 `OrderAPI`/`QuoteAPI`/`AccountAPI`는 `Domestic*`로 정리(행동 불변), 해외는 `Overseas*` 신설. 엔진은 Protocol에만 의존.

### 3.3 공통 인프라 재사용
`KISClient`(재시도/CircuitBreaker/RateLimiter), 인증 토큰 발급 로직은 **시장 공용**. 단 시장별 `base_url`/appkey/rate_limit는 `MarketProfile`에서 주입. 토큰 캐시는 자격증명 키별로 분리.

---

## 4. 모듈별 변경 요약 (10개 결합점)

| 모듈 | 변경 |
|------|------|
| `src/config.py` | `MARKET` env 추가, `MarketProfile` 선택 로직, 시장별 자격증명/`base_url`/rate_limit, 시장별 `KIS_ENV` |
| `src/api/order.py` | `DomesticOrderAPI`로 정리 + `OverseasOrderAPI` 신설(`OVRS_EXCG_CD`, `OVRS_ORD_UNPR`, TR_ID 매핑) |
| `src/api/quote.py` | `DomesticQuoteAPI` + `OverseasQuoteAPI`(`EXCD/SYMB`, `last/clos` 파싱, Decimal, 순위 API) |
| `src/api/account.py` | `DomesticAccountAPI` + `OverseasAccountAPI`(통화별 잔고, `inquire-present-balance`, 매수가능금액) |
| `src/api/client.py` | 시장별 `base_url`/헤더 주입(Protocol 외부 변경 최소) |
| `src/engine.py` | `_KST` 하드코딩 제거 → `MarketProfile.trading_hours.tz`, 손절/익절/리스크 파라미터 주입, `Stock` 생성 시 `market` 동적 |
| `src/scheduler/jobs.py` | 시장별 장시간/`_calculate_trading_interval`, 미국 휴장일, `MARKET`에 따라 등록 잡 결정 |
| `src/strategy/screener.py` | `VolumeRankItem`을 시장 무관 구조로, ETF 키워드/필터 파라미터를 `MarketProfile`에서 |
| `src/db/models.py` | `market`/`currency` 컬럼 추가, `price` 계열 Decimal 전환(§5) |
| `src/notify/formatter.py` | 통화기호/소수점 포맷을 `MarketProfile`에서(`₩`/`$`) |

> 전략 코어(`moving_average`/`rsi`/`macd`/`bollinger`/`ensemble`)는 **가격 시계열만 받으므로 변경 없음**. 단 Decimal/float 일관성만 확인.

---

## 5. 데이터 모델 & 마이그레이션

DB는 공유, `market` 컬럼으로 구분. `alembic-migration-flow` 스킬 패턴 준수.

- **`Stock.market`**: 기존 `KOSPI/KOSDAQ` + `NASD/NYSE/AMEX` 허용. 문자열 유지(ENUM 강제 회피로 마이그레이션 위험↓).
- **`Trade`/`Portfolio`/`Signal`/`ScreeningResult`**: `market: str`, `currency: str` 컬럼 추가. 기존 행은 `KRX`/`KRW` 백필. 기본값으로 다운타임 없는 add column.
- **가격 Decimal 전환**: `Trade.price`, `Trade.total_amount`, `Trade.profit_loss_amount` → `Numeric(18,4)`. 국내 정수값은 무손실 저장. `Portfolio.avg_price`/`current_price`/`peak_price`는 이미 Float이나 정밀도 영향 검토.
- **신규 `exchange_rates`**: `(from_currency, to_currency, rate, recorded_at)` — 매매엔 불필요(통합증거금), **원화 환산 리포팅/대시보드용**.
- **하위호환**: 기존 대시보드/주간리포트/캘린더 쿼리는 `market` 필터만 추가하면 동작. 기본 동작은 전체(KRX+US) 합산 또는 시장별 분리 뷰.

---

## 6. 시장별 환경 / 자격증명 분리

`.env` 확장 (역할 분리 원칙 유지):
```
# 국내(모의) — 기존
KIS_APP_KEY=...           KIS_APP_SECRET=...        KIS_ACCOUNT_NO=...     # KIS_ENV=virtual
# 미국(실전) — 신규
KIS_US_APP_KEY=...        KIS_US_APP_SECRET=...     KIS_US_ACCOUNT_NO=...  # 실전 계좌
MARKET=KRX                # 프로세스별로 KRX | US
```
- `config.py`가 `MARKET`을 읽어 `MarketProfile` + 해당 자격증명/`base_url`/rate_limit(미국 real=20/s) 로드.
- 시장별 `KIS_ENV`는 `MarketProfile`에 **내장**(KRX→`virtual`, US→`real`)을 기본으로 하고, 비상시 프로세스 `KIS_ENV` env로 override 가능.

---

## 7. 야간 무인 실전 운영 안전장치 (최우선)

메모리 `feat/live-readiness-phase0`의 **Phase 0 6종**을 미국 매매 진입 전 필수로 통합:
1. 킬스위치 (텔레그램/파일 기반 즉시 정지)
2. DB 프리체크 (사이클 시작 전 연결/스키마 검증)
3. 고아 체결 정리 (미체결/부분체결 복원)
4. halt 복원 (재시작 시 중단 상태 복원)
5. 알림 폴백 (텔레그램 실패 시 대체 경로)
6. real DB 부트스트랩

**미국 특화 추가 안전장치**:
- 보수적 한도: `MAX_POSITION_RATIO`↓, `DAILY_TRADE_LIMIT`↓, 종목당 진입 1회
- 야간 텔레그램: 체결/에러/킬스위치 트립 알림(운영자 취침 중 가시성)
- 환율 급변 게이트: USD/KRW 비정상 변동 시 신규 진입 보류
- 야간 사이클 예산 가드: 일일 API 한도 소진 곡선 모니터링

---

## 8. 배포 (launchd 야간 + watchdog)

- **`com.kis.autotrader.us`** launchd 서비스 신설: 미국 정규장 시간(서머타임 전환 인식)에 기동/종료.
- **watchdog 확장**: 미국 거래일/시간 인식, 야간 재시작 로직, 주말/미국 휴장일 게이팅.
- **공유 Postgres 보호**: 미국 프로세스의 DB 풀 크기/타임아웃을 독립 튜닝(2026-05-20 락 고갈 사고 재발 방지).
- 기존 6종 launchd 서비스와 공존(`com.kis.weeklyanalysis`는 의도적 제거 상태 유지).

---

## 9. API 호출 예산 (EGW00201 재발 방지)

미국은 EXCD 3개 반복 + 종목당 시세 호출로 예산 압박이 큼:
- `_calculate_trading_interval`을 `MarketProfile`별 분리, **사이클 간격 하한**을 미국용 보수 설정.
- **유니버스 상한**: EXCD별 Top-N으로 제한(예: 거래소당 N → 총 3N).
- spec/구현 시 **일일 한도 대비 소진 곡선 산정표** 작성(종목수 × 사이클빈도 × 거래소수).

---

## 10. 구현 Phase 순서

```
P1  시장 추상화 골격(MarketProfile / Provider Protocol) + KRX 리팩터
    → 행동 불변. 기존 테스트가 회귀 검출기. 전부 green 유지.
P2  해외 API 구현체: quote → account → order
    → respx mock 테스트 + 실전키 5분 실측(시세/순위/잔고 동작 확인)
P3  DB 마이그레이션(market/currency/Decimal) + 엔진 멀티마켓 구동
P4  야간 안전장치(Phase 0 통합) + 보수적 한도 + 텔레그램
P5  launchd/watchdog 야간 배포 + 소액 카나리(canary)
```

각 Phase는 독립 검증(pytest + mypy + ruff) 통과 후 다음으로.

---

## 11. 테스트 전략

- `tests/test_api/`: 해외 API respx mock(실제 응답 샘플 픽스처), 거래소코드 매핑, Decimal 파싱.
- `tests/test_market/`(신규): `MarketProfile` 단위 테스트(KRX/US 인스턴스).
- **P1 KRX 리팩터**: 기존 테스트가 행동 불변 회귀 검출기. green 유지가 P1 완료 기준.
- 메모리 `project_real_env_pytest_preexisting_failures`: real 환경 conftest 처리 주의(v0.11.1 격리 유지).

---

## 12. 비범위 (Out of Scope)

- 미국 **주간거래(데이마켓)** — `daytime-order`, BAA/BAY 거래소코드 계열.
- 미국 외 해외시장(홍콩/중국/일본/베트남) — 추상화는 확장 가능하나 이번엔 미구현.
- 프리/애프터마켓(확장시간) 매매.
- 실시간 웹소켓 미국 시세(무료 15분 지연/유료 실시간 신청) — 1차는 REST 폴링.
- USD 외화 직접 결제 모드 — 통합증거금만.

---

## 13. 구현 시 1차 재확인 항목 (검증 openQuestions)

> 다음은 confidence가 medium/low이거나 미확정인 항목. 구현 착수 시 KIS 포털/실호출로 확정.

1. 정규장 정정취소 미국 TR_ID(`TTTT1004U`/`VTTT1004U`) — 포털 원문 재확인.
2. 잔고/매수가능금액 응답 컬럼 전체 목록(`ord_psbl_frcr_amt` 등) — 포털 응답 명세서.
3. 순위 API `output2` 응답 필드명(`symb/last/rate/tvol/valx`)과 페이징(`KEYB`), 1회 반환 행 수.
4. 미국 가격 문자열/`zdiv` 스케일링 규칙 실응답 샘플 확인.
5. 마스터파일 클래스주 표기(`BRK.B` vs `BRKB`)와 주문 `SYMB` 입력 규칙 일치.
6. 해외 순위/시세 API의 초당/TR당 호출 제한이 국내와 다른지(외부 벤더 throttle).
7. **(실전 소액 채택으로 우선순위↓)** 모의 해외 시세/순위 지원 여부 — 미국은 실전 사용이므로 영향 없음.
