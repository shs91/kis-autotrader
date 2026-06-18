# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

---

## [2026-06-18] US 통화 인지 — present-balance(외화예수금·총손익·환율) + 로그 통화 단위 (v0.17.0)
- 카테고리: enhancement
- 변경 파일:
  - src/market/profile.py: format_money(amount, currency) — KRW는 기존 로그와 바이트 동일(정수+"원"), USD는 "$"+2자리(센트 보존)·음수는 "-$".
  - src/api/overseas_account.py: get_present_balance(CTRP6504R) + OverseasPresentBalance — 외화예수금·총평가·총손익·평가수익률·고시환율. 필드명 confidence=medium → _get_any 후보키 폴백 + valid 플래그.
  - src/api/account.py: Balance/StockHolding 금액 필드 int→float(USD 센트 보존) + currency 필드(기본 KRW).
  - src/api/protocols.py: OverseasAccountProvider에 get_present_balance 추가.
  - src/engine.py: _fetch_overseas_balance가 present-balance로 deposit/total_eval/total_pl/환율 보강(실패·무효 시 보유 합산+us_cash_budget 폴백). _money() 통화 인지 포맷으로 잔고확인·결산·체결·매수차단 로그 라우팅. self._fx_rate.
  - src/config.py: fx_usd_krw(폴백 환율)·us_present_balance_enabled(스위치). .env.example 반영.
  - tests: format_money 7·present-balance 5·_fetch_overseas_balance 2(신규 13 등).
- 배경: P3c-2 이후 US 잔고가 deposit=us_cash_budget 하드코딩·total_profit_loss=0 고정이라 실잔고·평가손익 추적 불가, 보유 USD를 int(round)로 절단(센트 손실), 환율 처리 전무, 로그가 USD를 전부 "원"으로 표기해 운영자 통화 혼동(High 1~3).
- 영향: US는 체결기준현재잔고로 실예수금·총손익·고시환율을 반영하고 로그가 "$"로 표기. present-balance 실패 시 보수 폴백으로 라이브 오표기 방지. **KRX는 format_money(KRW)·currency 기본값으로 동작 불변**(바이트 불변, 전체 1212 통과). 통합증거금 자동환전이라 환율은 표시/환산용(주문 사이징 미사용). Telegram 포맷터 통화 인지화는 태스크큐 페이로드 plumbing 필요로 후속.
- 검증 결과: pytest 전체 **1212 passed**(신규 13) | mypy strict ✅(102 files) | ruff ✅(변경분).
- 비고: 운영자 액션 — main 머지 후 pull → `com.kis.autotrader.us` 재시작. DB/스키마/마이그 불변. US_PRESENT_BALANCE_ENABLED=false로 비활성(보유합산 폴백), FX_USD_KRW로 폴백 환율 조정.

---

## [2026-06-18] 읽기측 시장 격리 — US 리스크복구가 KRX 거래로 일일한도 채워 매매 차단되던 P0 (v0.16.3)
- 카테고리: bug_fix
- 변경 파일:
  - src/db/repository.py: TradeRepository.get_trades_by_date(target_date, market=None) — market 필터 추가(None=전 시장 보존). PortfolioRepository.get_peak_prices(market=None) — 시장별 peak 시드.
  - src/engine.py: _restore_risk_state_if_needed가 get_trades_by_date(today, market=self._market.market_code)로 호출(P0). _load_peak_prices가 시장별 시드. _load_today_trades(today, market=None) 추가 + 시장별 캘린더(_create_calendar_event) 격리. 결산 집계(post_market)는 daily_summary/daily_performances에 market 컬럼 부재로 market=None 유지(마이그 후속).
  - tests: test_get_trades_by_date_filters_by_market·test_get_peak_prices_filters_by_market·test_restart_restore_passes_market_filter(신규 3).
- 배경: P3c-4가 쓰기측 market 라우팅만 넣고 읽기측 집계 격리를 누락. US 엔진(MARKET=US)의 장중 재시작 복구가 공유 trades를 시장 무관 조회 → KRX 당일 체결을 US 리스크상태로 재생하고 _today_trade_count=len(trades)로 **US 일일 한도(5건)를 KRX 거래로 채워 US 매매를 차단**(6/18 라이브: US 실거래 0건인데 "당일매도 3건 재생 PnL=10670원" + 한도도달 사이클 스킵). #59(스크리닝)는 같은 부류의 일부였음.
- 영향: US는 자기 시장 체결만 리스크/일일카운트에 반영 → US 매매 정상화. KRX는 market=None/기본값으로 동작 불변. peak·캘린더도 시장 격리. 결산(daily_summary)의 시장 분리는 market 컬럼 마이그가 필요해 후속(현재 KRX/US 합산 유지=무회귀).
- 검증 결과: pytest 전체 **1199 passed**(신규 3) | mypy strict ✅(변경 2 files) | ruff ✅(변경분).
- 비고: 운영자 액션 — main 머지 후 pull → `com.kis.autotrader.us` 재시작. DB/스키마/마이그 불변. KRX(`com.kis.autotrader`)는 무영향.

---

## [2026-06-18] 스크리닝 결과 시장별 격리 — US가 KRX 발굴 종목 읽던 누수 차단 (v0.16.2)
- 카테고리: bug_fix
- 변경 파일:
  - src/db/repository.py: ScreeningResultRepository.get_by_date(target_date, market="KRX", tz="Asia/Seoul") — market 필터 + 날짜 경계를 시장 타임존 기준 산정. 기본값 KRX 불변.
  - src/engine.py: _screen_stocks·_record_screening_match_metric이 self._market의 market_code·timezone 주입.
  - tests/test_db/test_repository.py: test_get_by_date_filters_by_market(KRX↔US 격리 회귀 1건).
- 배경: 멀티마켓 공유 screening_results 테이블에서 get_by_date가 시장 필터 없이 당일 전체 행 반환 → US 엔진(MARKET=US)이 KRX ScreeningWorker 발굴 종목(한국 종목코드)을 읽어 "[거래소 미해결] 003280 — 기본 거래소 NASD 사용" 류 경고 양산 + US API 예산 낭비(6/18 logs/autotrader.us.out.log 관측).
- 영향: US는 US-market 행만 조회(현재 0건 → watchlist_us 폴백). KRX는 market="KRX" 기본값으로 기존 행과 일치 → 동작 불변(byte-invariant). 한국 종목은 US 시세조회/가격하한에서 걸려 오주문은 없었으나(비위험) API 낭비·로그 오염 해소.
- 검증 결과: pytest 전체 **1196 passed**(신규 1) | mypy strict ✅(변경 2 files) | ruff ✅(변경분).
- 비고: 운영자 액션 — main 머지 후 pull → `com.kis.autotrader.us` 재시작 시 반영. DB/스키마/마이그레이션 불변. KRX(`com.kis.autotrader`)는 영향 없음.

---

---

---

---
