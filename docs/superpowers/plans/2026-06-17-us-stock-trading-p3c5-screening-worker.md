# P3c-5: ScreeningWorker US 동적 스크리닝 경로 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 큰 변경 + 실금 주문 라우팅 민감 → 구현 전 어댑버설 리뷰(P3c-2 패턴) 권장.

**Goal:** 미국 종목을 거래소별 순위 API로 발굴해 동적 스크리닝한다. **opt-in**(`SCREENING_US_ENABLED` 기본 false)으로 켜기 전엔 US가 watchlist_us 고정 유니버스(P5 동작)로 **무변경**. KRX 행동 불변.

**선행 완료(P3c-5 필터 청크, 커밋 540dd6e):** `ScreeningFilter`/`StockScreener`에 `is_overseas` — US 알파벳 심볼 ETF 오분류 해소 + min_price_us. 이 plan은 그 위에서 **Worker/엔진/repo/main** 을 잇는다.

## 핵심 설계 결정 (확정)

1. **거래소 라우팅 = stocks.market 재사용(마이그 회피)**: Worker가 US 스크리닝 종목의 `stocks.market`에 **거래소코드(NASD/NYSE/AMEX)** 를 upsert. 엔진 `_screen_stocks`가 각 screened code의 `Stock.market`을 읽어 `self._exchanges[code]=거래소` 시드 → `_exchange_of`가 올바른 거래소 반환. **screening_results.exchange 컬럼/마이그 불필요**(순수 코드).
   - stocks.market 의미: KRX="KOSPI/KOSDAQ"(보드), US=거래소. `market_stats.py`의 `in ("KOSPI","KOSDAQ")` 필터는 US 거래소를 제외(정합).
   - 정합성: P3c-4 `_board_label`(US→market_code "US")을 `_board_label(code, krx_default)`로 확장해 US는 `_exchange_of(code) or market_code` 반환(거래소 우선). watchlist_us 종목도 거래소 라벨로 일관.
2. **쿼터 상호의존(중요)**: P3c-6이 US 스케줄러를 "메인 100%, 스크리너 0"으로 둠. US 스크리너를 켜면 **스크리너 쿼터 0 → 시세조회 불가**. `SCREENING_US_ENABLED`가 true일 때만 US 스케줄러가 **메인/스크리너 분할**(KRX와 동형 80/20)로 전환. false면 메인 100% 유지(불변).
3. **opt-in 안전**: `SCREENING_US_ENABLED`(env, 기본 false). false면 main.py가 US 스크리너 워커 미가동 + 스케줄러 메인 100%(현 P5). true면 워커 가동 + 쿼터 분할.

## 파일 구조
| 파일 | 변경 |
|------|------|
| `src/config.py` | `ScreeningConfig.us_enabled`(SCREENING_US_ENABLED, 기본 false) |
| `src/worker/screener.py` | `__init__(market_profile=)` + OverseasQuoteAPI + StockScreener(is_overseas) · `_is_trading_window` 시장별(ET/holidays_us) · `_run_screening` US 분기 → `_run_screening_us` · `_convert_overseas_rank`(OverseasRankItem→VolumeRankItem) · `_record_to_db(market=, exch_of=)` + Stock.market=거래소 upsert |
| `src/engine.py` | `_screen_stocks`: `get_by_date(market=self._market.market_code)` + screened code의 Stock.market에서 `_exchanges` 시드. `_board_label(code, krx_default)` 거래소 우선(US) |
| `src/db/repository.py` | `ScreeningResultRepository.get_by_date(market="KRX")` 필터 |
| `src/scheduler/jobs.py` | US 쿼터: `SCREENING_US_ENABLED` true면 분할(KRX 동형), false면 메인 100%(현 P5) |
| `main.py` | US 스크리너 워커 게이트: `is_overseas and settings.screening.us_enabled`. ScreeningWorker(market_profile=) 주입 |
| tests | worker US 랭킹/변환/적재, 엔진 거래소 시드, repo market 필터 |

## Task 분해 (각 TDD)
1. **config us_enabled** + worker `__init__` 시장 주입 + StockScreener(is_overseas).
2. **`_run_screening_us`**: 거래소 루프 get_ranking → `_convert_overseas_rank`(symbol→stock_code, last:Decimal→int(round), market_cap=0, exch_of[symbol]=exchange) → dedup → filter → 해외 일봉 분석(`overseas_quote.get_daily_price(symbol,exchange)`, close Decimal→float) → score → `_record_to_db(market="US", exch_of=)`.
3. **`_record_to_db` market/exchange**: `record_screening(market=)` + US는 `StockRepository.create/update` 로 `stocks.market=exch_of[code]` upsert.
4. **`_is_trading_window` 시장별**: US는 ET(self._market.timezone) 시간 + `is_market_closed(date, "US")`. KRX 불변.
5. **엔진 `_screen_stocks`**: `get_by_date(today, market=self._market.market_code)` + 각 screened code의 Stock.market이 거래소면 `_exchanges` 시드.
6. **`_board_label(code, krx_default)`**: US는 `_exchange_of(code) or market_code`. 호출부 2곳 갱신.
7. **repo `get_by_date(market=)`** 필터.
8. **jobs.py US 쿼터 분할**(us_enabled 시) + **main.py US 워커 게이트**.

## KRX 행동 불변
- 모든 신규 분기는 `is_overseas`/`us_enabled`(기본 false) 뒤 → KRX·US-watchlist(현 P5) 무변경.
- `_run_screening`/`_record_to_db` KRX 경로, `get_by_date` 기본 market="KRX"(server_default와 동일), `_board_label` KRX 리터럴, 쿼터 KRX 분할 모두 불변.
- 회귀 검출: 기존 worker/screener/engine 테스트 green.

## 리스크 (어댑버설 리뷰 집중 항목)
- **거래소 라우팅 오류**: stocks.market=거래소 → 엔진 시드 → 주문 거래소. 한 단계라도 틀리면 US 종목이 잘못된 거래소로 주문(실금). 시드 타이밍(_screen_stocks가 stocks 조회) + watchlist vs screened 일관성.
- **쿼터 0 함정**: us_enabled true인데 스케줄러 쿼터 분할 미반영 시 스크리너 시세조회 0 → 발굴 0(조용한 실패).
- **해외 일봉 분석량**: 거래소 3개 × 종목 × 일봉 = 야간 API 버스트(§9.2). top_n 거래소별 상한 + min_trading_interval.
- **US 종목명 부재**: 순위 API가 이름 미제공 → stock_name=symbol. 표시/포맷 영향.

## Execution Handoff
필터 청크(540dd6e, branch us-stock-p3c5-screener) 위에서 이 plan을 실행. opt-in 기본 off라 단계별 안전.
