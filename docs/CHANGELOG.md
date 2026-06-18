# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-06-18] present-balance output3 파싱 + 통합증거금 과대주문 방지 (v0.19.3)
- 카테고리: bug_fix
- 변경 파일:
  - src/api/overseas_account.py: get_present_balance가 output3(실측 필드: frcr_use_psbl_amt 매수여력·tot_dncl_amt 예수금·frcr_evlu_tota 평가·tot_evlu_pfls_amt 손익·evlu_erng_rt1 수익률)에서 파싱. 기존엔 output2(부재)에서 찾아 valid=False였음.
  - src/engine.py: _fetch_overseas_balance가 deposit(사이징 기준)을 us_cash_budget 캡으로 유지 — pb.deposit(통합증거금 매수여력, 클 수 있음)으로 덮지 않음(과대주문 방지). 평가/손익/환율만 present-balance 실값 반영 + 매수여력 로깅.
  - tests: present-balance output3 파싱·환율 output2 폴백·deposit 캡 유지 회귀.
- 배경: US 라이브 진단 결과 present-balance(CTRP6504R) 데이터가 output2 아닌 output3에 있어 #61 파싱이 항상 valid=False→us_cash_budget 폴백. 우연히 안전(보수 사이징)했으나 표시 부정확. 또한 통합증거금 활성 시 매수여력(원화담보 환산, 클 수 있음)을 deposit으로 쓰면 사이징 과대 → us_cash_budget($1000) 캡 명시.
- 영향: 계좌 충전(통합증거금) 후 평가/손익을 실값으로 표시하되 사이징은 us_cash_budget 캡 유지(실주문은 _get_buyable_qty가 별도 캡). KRX 무관. US 매수 블로커는 계좌 매수여력 $0(통합증거금 미활성)이라 본 수정과 별개(코드는 준비됨).
- 검증 결과: pytest 전체 **1229 passed**(신규 회귀) | mypy strict ✅ | ruff ✅ | 라이브 진단 실측 필드 확인.
- 비고: 운영자 액션 — main 머지 후 pull → US 재시작 시 반영. DB/마이그 불변. 통합증거금 활성 후 평가/손익 정확표시.

---

## [2026-06-18] 마감 임박 매수가드 타임존 — US가 개장 직후에도 매수 전면차단되던 라이브 블로커 (v0.19.2)
- 카테고리: bug_fix
- 변경 파일:
  - src/strategy/risk.py: RiskManager(tz=) + is_near_market_close가 now 미지정 시 datetime.now(시장 타임존)로 판정. 기존엔 datetime.now()(시스템 KST)로 컷오프(14:30)와 비교.
  - src/engine.py: RiskManager 생성 시 tz=self._market.timezone(KRX=Asia/Seoul, US=America/New_York).
  - tests: 마감가드 시장 타임존 회귀 3건(tz저장·ET컷오프·default now가 시장tz 사용).
- 배경: US 동적 스크리너가 발굴+BUY 신호 생성했으나(6/18 라이브, PBR/A 0.78 등 BUY 10) 전부 BUY_REJECT(MARKET_CLOSE_GUARD). 원인: is_near_market_close가 시스템 KST 시각(22:54)을 US 마감 컷오프(14:30 KRX용)와 비교 → 22>14로 항상 "마감 임박" → US 세션(KST 22:30~05:00) 내내 신규 매수 차단. US 배포 후 잠복(BUY 신호가 처음 나서 노출). settlement date.today() KST 이슈와 동류.
- 영향: US는 ET 기준으로 마감 컷오프 판정 → 개장~14:30 ET 매수 허용, 14:30 ET 이후 차단(1.5h 전). **KRX는 tz=Asia/Seoul(시스템 KST 동일)·.hour 동일로 동작 불변**(전체 1228 통과). 마감 청산 게이트·익절 하향(같은 메서드)도 US에서 정합화.
- 검증 결과: pytest 전체 **1228 passed**(신규 3) | mypy strict ✅ | ruff ✅ | 라이브 발현 확인(BUY_REJECT=MARKET_CLOSE_GUARD).
- 비고: 운영자 액션 — main 머지 후 pull → US 재시작 시 매수 정상화. DB/마이그 불변. US 라이브 활성 중이라 조기 배포 권장. 컷오프 14:30은 KRX/US 공유(US=close 1.5h 전) — 필요 시 US 전용 컷오프 별도.

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

