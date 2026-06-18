# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-06-18] 해외 거래량순위 필수 파라미터 누락 수정 — US 스크리너 발굴 0 라이브 블로커 (v0.19.1)
- 카테고리: bug_fix
- 변경 파일:
  - src/api/overseas_quote.py: get_ranking params에 PRC1/PRC2(가격범위)·KEYB(연속조회키) 추가 — 빈값이어도 필수. OverseasRankItem.name(ename 영문명) 추가.
  - src/worker/screener.py: _run_screening_us가 r.name(영문명)으로 stock_name 보강.
  - tests: get_ranking 필수 파라미터 회귀 가드 + name(ename) 파싱.
- 배경: US 동적 스크리너(#65) 라이브 활성화(6/18 22:25 KST) 후 발굴 0 관측. 진단 결과 trade-vol 순위 API(HHDFS76310010)가 PRC1 누락으로 OPSQ2001 "ERROR INPUT FIELD NOT FOUND [PRC1]" 반환 → output2 부재 → 빈 결과 → _run_screening_us가 all_items 비어 로그 없이 early return. P2 get_ranking의 잠복 버그(스크리너가 첫 실호출자라 노출). 파라미터 보강 시 output2 100종목 정상(msg_cd MCA00000).
- 영향: US 스크리너가 거래소별 100종목 순위를 정상 발굴. 응답의 ename(영문명) 활용으로 종목명도 심볼 대신 정식명(예: ADITXT INC). KRX 무관(해외 전용 API). opt-in이라 SCREENING_US_ENABLED=true에서만 경로 활성.
- 검증 결과: pytest 전체 **1225 passed**(신규 회귀 가드) | mypy strict ✅ | ruff ✅ | 라이브 진단으로 output2 100종목 실측 확인.
- 비고: 운영자 액션 — main 머지 후 pull → US 재시작 시 스크리너 발굴 정상화. DB/스키마/마이그 불변. 라이브 활성 중이라 조기 배포 권장.

---

## [2026-06-18] US 동적 스크리너 (P3c-5 2/2) — 거래소별 순위 발굴, opt-in 기본 off (v0.19.0)
- 카테고리: enhancement
- 변경 파일:
  - src/strategy/screener.py: ScreeningFilter/StockScreener is_overseas(540dd6e cherry-pick) — US 알파벳 심볼 ETF 오분류 해소 + min_price_us.
  - src/worker/screener.py: ScreeningWorker(market_profile=) — US는 OverseasQuoteAPI + StockScreener(is_overseas). _run_screening_us(거래소별 get_ranking[EXCD]→VolumeRankItem 변환+exch_of[symbol]=OVRS_EXCG_CD→필터→해외일봉 분석→스코어→적재). _is_trading_window 시장별(US ET 09:30~16:00+holidays_us). _record_to_db(market, exch_of): record_screening(market) + US는 stocks.market=거래소 upsert. _load_existing_screened_codes 시장필터.
  - src/engine.py: _screen_stocks가 발굴 US 종목의 stocks.market(거래소)을 읽어 _exchanges 시드(_seed_overseas_exchanges) → 주문 라우팅. _board_label(code, krx_default): US는 _exchange_of(code)(거래소) 우선.
  - src/scheduler/jobs.py: us_enabled면 US 쿼터 KRX 동형 분할(장전 스크리너100%→장중 80/20→마감후 메인100%), 아니면 메인 100%(현 P5).
  - main.py: US 스크리너 워커 게이트(is_overseas and screening.us_enabled). src/config.py: ScreeningConfig.us_enabled(SCREENING_US_ENABLED, 기본 false).
  - tests: 워커 US 거래소 라우팅/변환·board_label 거래소 회귀.
- 배경: US가 watchlist_us 고정 유니버스만 매매하던 한계 해소. 거래소별 거래량순위 API로 동적 발굴. **거래소 코드 이중체계**(순위/시세 EXCD NAS/NYS/AMS ≠ 주문 OVRS_EXCG_CD NASD/NYSE/AMEX)를 quote_exchange_map으로 변환, stocks.market=거래소로 엔진 주문 라우팅 시드(마이그 회피).
- 영향: **opt-in 기본 off** — SCREENING_US_ENABLED=false면 US는 watchlist_us 고정+메인 100%(현 P5 무변경). true면 워커 가동+쿼터 분할. **KRX 완전 불변**(is_overseas/us_enabled 기본 false 뒤 분기, 전체 1225 통과). 어댑버설 리뷰(거래소 라우팅 실금 민감) 수행.
- 검증 결과: pytest 전체 **1225 passed**(신규 3) | mypy strict ✅(103 files) | ruff ✅(변경분).
- 비고: 운영자 액션 — main 머지 후 pull → 재시작(기본 off라 무변경). 활성화는 config_overrides/env `SCREENING_US_ENABLED=true` + US 재시작. DB/스키마/마이그 불변(stocks.market 재사용). 첫 활성 시 거래소 라우팅·발굴 로그 모니터링 권장.

---

## [2026-06-18] Telegram 알림 통화 인지화 — US 알림 "원"→"$" (통화 일관성 마무리) (v0.18.1)
- 카테고리: enhancement
- 변경 파일:
  - src/notify/formatter.py: format_buy/sell/daily_summary/diagnostics에 currency 파라미터(기본 KRW) + format_money 라우팅. BuyDetail/SellDetail 금액 필드 float화(USD 센트). 잔고 라인은 balance.currency 사용.
  - src/notify/telegram.py: notify_buy/sell/daily_summary/diagnostics에 currency 전달. notify_sell 손익은 KRW만 int(USD 센트 보존).
  - src/engine.py: 텔레그램 enqueue 6종(buy×2·sell×2·daily_summary·diagnostics) message_data에 currency=self._market.currency 배선.
  - tests: US 통화("$") 회귀 4건 + _FakeBalance.currency.
- 배경: #61이 엔진 로그를 통화 인지화했으나 Telegram 포맷터는 엔진→태스크큐→워커→노티파이어 경유라 currency plumbing이 필요해 후속으로 미뤘던 항목. US 매수/매도/결산/진단 알림이 USD를 전부 "원"으로 표기해 운영자 통화 혼동.
- 영향: US 알림이 "$"+센트로 표기. **KRX는 currency=KRW 기본값·format_money(KRW) 정수+"원"으로 바이트 동일**(전체 1219 통과, notify 기존 테스트 무회귀). 멀티마켓 통화 인지화 3층(로그 #61·결산테이블 #63·알림 #이번) 완결.
- 검증 결과: pytest 전체 **1219 passed**(신규 4) | mypy strict ✅(102 files) | ruff ✅(변경분).
- 비고: 운영자 액션 — main 머지 후 pull → `com.kis.autotrader`·`com.kis.autotrader.us` 재시작. DB/스키마/마이그 불변.

---

## [2026-06-18] 결산 테이블 시장 격리 — daily_summary/daily_performances market 컬럼 + alembic 중복 head 복구 (v0.18.0)
- 카테고리: enhancement
- 변경 파일:
  - src/db/models.py: DailySummary/DailyPerformance에 market 컬럼(server_default KRX) + 복합 unique(date, market). 기존 단일 date unique 해제.
  - alembic: c3d4e5f6a7b8 중복 revision 해소 — sell_reason 마이그를 고유 ID d4e5f6a7b8c9로 rename + Numeric(c3d4e5f6a7b8) 뒤로 재연결(선형화). 신규 e5f6a7b8c9d0: market 컬럼 추가 + unique 인덱스→복합 제약, 기존 행 KRX 백필.
  - src/db/repository.py: upsert_daily_summary(date, market)·get_by_date(date, market) — trades·screening_results 시장 필터 + (date,market) upsert. DailyPerformanceRepository.create/get_by_date에 market.
  - src/worker/handlers.py: DailySummary/DailyPerformance 핸들러가 payload market 전달. src/engine.py: 결산 enqueue payload + 레거시 경로 market 배선. src/scheduler/jobs.py·src/db/analytics.py: market 전달. dashboard: daily_summary/perf 쿼리 market='KRX' 필터(복합키 후 더블카운트 방지).
  - tests: 결산 시장 격리 회귀 2건(summary·performance).
- 배경: #62가 결산 enqueue 멱등키를 시장 분리했으나, daily_summary/daily_performances 테이블 자체는 date 단일 unique라 KRX/US가 같은 날짜 행을 덮어쓰던 잔여(#4). 또한 sell_reason 마이그(v0.16.1)가 Numeric 마이그와 동일 revision ID(c3d4e5f6a7b8)를 잘못 써 alembic head가 갈라진 사전존재 결함을 발견 — 새 마이그 생성을 막아 동반 복구.
- 영향: KRX/US 결산이 (date, market) 복합키로 분리 저장. trades·screening 집계 시장 격리(error/cycle는 system_metrics market 컬럼 부재로 합산 유지=기존과 동일). **KRX는 market=KRX 기본값·dashboard 필터로 동작 불변**(전체 1215 통과). sell_reason는 ADD VALUE IF NOT EXISTS라 재실행 no-op(stamp 불필요).
- 검증 결과: pytest 전체 **1215 passed**(신규 2) | mypy strict ✅(102 files) | ruff ✅(변경분) | 마이그 오프라인 SQL 검증.
- 비고: **운영자 액션 — alembic upgrade head**(sell_reason 재실행 no-op + daily 테이블 market 컬럼 추가) → main 머지 후 pull → `com.kis.autotrader`·`com.kis.autotrader.us` 재시작. 과거 US 오염 결산 행(6/18 daily_perf 등)은 KRX 라벨 백필 — 필요 시 별도 데이터 정정.

---

## [2026-06-18] 결산 멱등키 시장 네임스페이스 — US가 KRX 캘린더/결산을 선점·디듑하던 버그 (v0.17.1)
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: _today()=datetime.now(self._tz).date()(시장 타임존 날짜, US=ET). post_market·결산 enqueue 5종(calendar/telegram_summary/telegram_diag/daily_summary/daily_perf)의 idempotency_key를 `{type}_{market_code}_{date}`로 시장 네임스페이스(sync_portfolio는 P3c-4에서 이미 적용). 결산/스크리닝/일일성과 날짜를 _today()로 통일.
  - tests: test_settlement_idempotency_keys_market_namespaced(KRX/US 키 분리·충돌 검증), diagnostics 테스트에 _market/_tz 주입.
- 배경: 결산 enqueue 멱등키가 시장 네임스페이스 없이 `calendar_{date}`라, US 프로세스가 ET 16:10 결산(=KST 새벽)에 date.today()=KST 다음날로 0건 태스크를 먼저 등록 → 같은 날짜 KRX 결산(15:40)의 실제 enqueue가 멱등 디듑됨. 6/18 KRX 10건(+17,332원)인데 캘린더가 "0건 +0원"(US가 calendar_2026-06-18을 KST 05:10에 선점, 태스크 id 397124 exec_cnt=0). 캘린더 외 telegram_summary·telegram_diag·daily_perf도 동일 선점.
- 영향: KRX/US가 각자 결산 이벤트/알림을 등록(키 분리). US date.today()의 KST 오인을 _today()로 교정(US=ET 세션 날짜). **KRX는 self._tz=Asia/Seoul·market_code=KRX라 날짜·키 모두 기존과 동일**(동작 불변). daily_summary 테이블 자체 격리(market 컬럼)는 후속(#4). 과거 잘못 등록된 6/18 이벤트는 운영자 수동 정리.
- 검증 결과: pytest 전체 **1213 passed**(신규 1) | mypy strict ✅(102 files) | ruff ✅(변경분).
- 비고: 운영자 액션 — main 머지 후 pull → `com.kis.autotrader`·`com.kis.autotrader.us` 재시작. DB/스키마 불변. 오늘(6/18) KRX 캘린더 이벤트는 별도 재생성/정리 필요.

