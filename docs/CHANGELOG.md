# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

## [2026-06-17] 본전스톱·정체청산 sell_reason enum 매핑 — NULL 기록 정합화 (v0.16.1)
- 카테고리: bug_fix
- 변경 파일:
  - src/db/models.py: SellReason enum에 BREAKEVEN·STAGNATION 추가.
  - src/engine.py: _SELL_REASON_MAP에 "본전스톱"→BREAKEVEN·"정체청산"→STAGNATION 매핑 2건.
  - alembic/versions/c3d4e5f6a7b8_add_sell_reason_breakeven_stagnation.py: ALTER TYPE sell_reason_enum ADD VALUE (BREAKEVEN, STAGNATION). autocommit_block 사용(PG ADD VALUE 트랜잭션 제약).
  - tests/test_engine_sell_reason.py: 본전스톱→BREAKEVEN·정체청산→STAGNATION 기록 + _SELL_REASON_MAP 완전성 회귀 4건.
- 배경: v0.16.0 청산 로직(본전스톱/정체청산)이 _SELL_REASON_MAP에 매핑이 없어 sell_reason=NULL로 기록(6/17 아주IB투자 정체청산 +1.9%·보유180분 사례로 발견). 청산은 정상 작동하나 매도사유 집계·대시보드·룰엔진에서 누락. pytest가 risk.should_*만 검증해 엔진 DB 기록 경로 미테스트로 미발견.
- 영향: 정체청산→STAGNATION·본전스톱→BREAKEVEN 정확 기록. 청산 동작·손익 불변(기록만 정합화). 매핑 완전성 테스트로 향후 청산사유 추가 시 NULL 회귀 차단. 기존 NULL 1건(6/17 아주IB) 백필은 운영자 승인 후 별도(6/15 흥아해운 NULL은 원인 미상).
- 검증 결과: pytest 전체 **1126 passed**(신규 4) | mypy strict ✅(102 files) | ruff ✅(변경분) | 골든 11 통과.
- 비고: 운영자 액션 — alembic upgrade head 적용 완료(→c3d4e5f6a7b8). `com.kis.autotrader` 재시작 시 매핑 반영. DB enum 값 추가는 비가역(downgrade no-op)·기존 데이터 영향 0.

---

## [2026-06-16] 본전 스톱 + 정체 청산 — 이익 보호 & 횡보 슬롯 회수 (v0.16.0)
- 카테고리: enhancement
- 변경 파일:
  - src/config.py: StrategyConfig.breakeven_activation_ratio(env BREAKEVEN_ACTIVATION_RATIO, 기본 0.02, 0=비활성)·stagnation_hours(env STAGNATION_HOURS, 기본 3.0, 0=비활성).
  - src/strategy/risk.py: should_breakeven_stop(고점이 +X%(기본 2%) 도달한 뒤 현재가가 평단 이하로 회귀 시 본전 청산) + should_stagnation_exit(보유 N시간(기본 3h) 초과 + 트레일링 미무장(고점<+5%) 시 정체 청산). __init__에 두 파라미터 추가(None→settings 폴백).
  - src/engine.py: _held_since(종목별 최초 보유 KST 시각, tz-aware _KST) 추적 + _held_minutes 헬퍼. _process_held_stock 청산 사다리에 4순위 본전스톱·5순위 정체청산 삽입(손절>마감청산>트레일링/익절>본전스톱>정체청산>전략매도). pre_market·_execute_sell에서 리셋/pop. 골든 G01(engine naive datetime 금지) 준수.
  - tests/test_strategy/test_risk.py: 신규 8건(본전스톱 4·정체청산 4).
- 배경: 06-16 손절 2%→3% 완화 후에도 횡보 종목이 슬롯(MAX_POSITION_RATIO 0.3 → ~3개)을 장시간 점유해 회전율 병목. 트레일링은 +5% 무장 전엔 무방비라 +2~4% 갔다 본전 회귀하는 이익 되돌림을 못 막음(쿨다운·손절 모두 사각).
- 영향: (1) 본전스톱 — 고점 +2% 찍은 종목이 평단까지 밀리면 손실 전환 전 청산해 이익 되돌림 방지. (2) 정체청산 — 3시간 보유에도 트레일링 못 켠 죽은 종목 정리 → 슬롯 회수로 회전 가속. 손절·마감·트레일링·익절이 모두 우선이라 정상 추세·이익 포지션엔 영향 없음. default-ON.
- 검증 결과: pytest 전체 **1086 passed**(신규 8) | mypy strict ✅(96 files) | ruff ✅(변경분) | 골든 G01 통과.
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영. `BREAKEVEN_ACTIVATION_RATIO=0`·`STAGNATION_HOURS=0`으로 개별 비활성, config_overrides로 튜닝. DB/스키마 불변.

---

---

---
