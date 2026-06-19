# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-06-20] 앙상블 추세역행 BUY 가드(C1) + 재시작 쿨다운 복원(C2) — churn 손실 교정 (v0.22.0)
- 카테고리: enhancement
- 변경 파일:
  - src/strategy/base.py: BaseStrategy.is_trend_following 클래스 속성(기본 False). moving_average.py·macd.py에 =True(RSI·볼린저는 평균회귀형 False).
  - src/strategy/ensemble.py + config.py + registry.py: **(C1)** `_weighted_vote`에 추세역행 BUY 가드 — BUY 승자인데 추세형(MA·MACD) BUY 표가 없으면(평균회귀 RSI/볼린저만 BUY) HOLD로 억제(단독·합의 둘 다). `STRATEGY_TREND_FILTER_ENABLED`(기본 false, opt-in) 게이트.
  - src/engine.py: **(C2)** `_restore_risk_state_if_needed`가 당일 trades에서 `_today_buys_per_stock`·`_last_sell_at`를 재구성(매도 없어도 BUY 카운트 복원). 장중 재시작 시 두 dict가 비어 손절 직후 재매수(쿨다운 우회)·종목당 한도 초과가 발생하던 M8 버그 수정. 쿨다운=실제 매도시각 기준.
  - tests: 추세역행 억제/허용/기본off·재시작 카운터 복원(매도없는 케이스 포함) 회귀 6건.
- 배경: 이번주 KRX 분석 → churn 손실 범인이 RSI(9) 역추세 dip-buy(아주IB −9,909, MA·MACD·볼린저 HOLD인데 RSI만 과매도 BUY). 코칩은 재시작이 쿨다운 초기화해 손절 4분 후 재매수(실측). 제안서 docs/proposals/2026-06-19_rsi-downtrend-churn-fix.md(3축 적대검증).
- 영향: **C1은 opt-in 기본 off라 켜기 전 KRX/US 불변**. **C2는 KRX/US 공통**(재시작 안전장치 복원, 운영자 승인) — 정상일(pre_market 실행) 불변, 장중 재시작 시에만 복원. 별도로 config_overrides SOLO_BUY_MIN_CONFIDENCE 0.45→0.60 적용(제안서 1단계).
- 검증 결과: pytest 전체 **1268 passed**(신규 6) | mypy strict ✅ | ruff ✅(변경분).
- 비고: 운영자 액션 — main 머지 후 pull → KRX·US 재시작(C2). **C1 활성화는 config_overrides에 `STRATEGY_TREND_FILTER_ENABLED: "true"` + 재시작**(회귀 관측하며 opt-in 권장). DB/마이그 불변.

---

## [2026-06-19] 보유종목 실시간 가격 vs 매수가 비교 차트 (v0.21.0)
- 카테고리: enhancement
- 변경 파일:
  - src/db/models.py + alembic: 신규 `price_snapshots` 테이블(stock_code·market·currency·price Numeric·captured_at, 복합 인덱스 (stock_code,captured_at)·captured_at). 보유종목 폴링 현재가 시계열.
  - src/db/repository.py: `PriceSnapshotRepository`(add/get_recent/delete_older_than).
  - src/worker/handlers.py + main.py: `PriceSnapshotHandler`("price_snapshot" task_type) — 워커가 INSERT.
  - src/engine.py: `_enqueue_price_snapshot` — _process_stock 보유 분기에서만 현재가를 워커 큐로 적재(추가 API 0, 매매 무영향, priority=0). KRX/US 시장 인지(_norm_price·market_code·currency).
  - src/scheduler/jobs.py: 일 1회(04:30) 7일 초과 스냅샷 정리 잡(시장 무관 멱등).
  - dashboard/positions_data.py + pages/positions.py: Altair 차트 — 가격 line + 평단가/손절선/익절선/peak 수평선 + 매수▲/매도▼ 체결마커 + 손익률, 통화 인지(KRX ₩/US $). 데이터 구성은 순수 함수 분리(테스트 가능).
  - tests: 모델·repository·핸들러·엔진 enqueue·정리잡·차트 데이터 회귀 17건.
- 배경: 운영 중 "내가 산 가격 대비 지금 어디쯤이고 어디서 팔릴지"를 한눈에 보는 화면 요구. 웹소켓(dead code·US 미지원·차단 위험) 대신 엔진이 이미 폴링하는 현재가를 시계열 적재(폴링 재사용).
- 영향: **KRX 매매/결산 완전 불변**(신규 테이블·경로, 전체 1262 passed). 보유종목만 스냅샷(범위 한정), 7일 롤링으로 저장량 유계. 대시보드 신규 positions 페이지.
- 검증 결과: pytest 전체 **1262 passed**(신규 17) | mypy strict ✅(102 files) | ruff ✅(변경분) | 11 TDD 커밋 + 태스크별 스펙·품질 적대검토 + opus 최종 리뷰 GO.
- 비고: 운영자 액션 — main 머지 후 pull → `alembic upgrade head`(price_snapshots 생성, **DB 변경**) → KRX·US 재시작(스냅샷 수집·정리잡 시작). 대시보드 호스트에 altair 필요(streamlit 번들로 보통 설치됨). 장중 ~10초 단위 누적.

---

## [2026-06-19] US 실거래 경로 하드닝 5종 — 사이징/손절차단/결산통화/연패정밀도/중복주문 (v0.20.0)
- 카테고리: bug_fix
- 변경 파일:
  - src/strategy/risk.py: **(B1)** calculate_position_size에 min_quantity 플로어(기본 0). US가 1을 넘겨 예산×비율($100)<주가인 고가주(AAPL/NVDA 등)가 0주로 영구 차단되던 false-block 해소. **(H4)** record_trade_result 입력·누적PnL을 float화 — US 센트 손익 보존(int 절단 시 1달러 미만 손익이 연패 카운터에서 소실돼 MAX_CONSECUTIVE_LOSSES 서킷 약화). KRX 프로세스는 정수값만 흘러 누적기·로그 바이트 불변.
  - src/engine.py: **(B2)** 일일 매매 한도(BUY+SELL 합산) 도달 시 사이클을 통째 return하던 게이트를 신규 매수만 차단하도록 변경 — 보유 종목 손절/트레일링/마감청산 등 보호매도는 계속 평가(야간 무인 세션 포지션 무방비 방지). **(H3)** 일일결산 _load_today_trades에 market 필터 — US 결산이 KRX 매도손익을 FX 없이 정수 합산해 손익/수익률을 오표기하던 누수 격리. **(B1·H4)** 사이징 호출부 US 1주 플로어·손익 절단 제거.
  - src/api/client.py + order.py + overseas_order.py: **(중복주문)** post에 idempotent 플래그 추가. 주문 체결(매수/매도)은 idempotent=False로 호출 — 5xx/네트워크 타임아웃 시 주문이 접수·체결됐는데 응답만 유실된 경우 재시도가 실자금 중복주문을 내던 위험 차단(재시도 없이 즉시 실패). 429(거부)는 재시도 유지. 주문 실패경로에 잔고캐시 무효화 추가 → 다음 사이클이 fresh 잔고로 팬텀 체결 재조정(60s TTL 안전망 누수 차단). 정정/취소는 미변경.
  - tests: B1 플로어·H4 센트연패·idempotency(5xx·네트워크 무재시도+429/기본 재시도)·주문 비멱등 전달·B2 한도 도달 보호매도 회귀 15건 추가.
- 배경: 첫 US 실거래(6/18) 직후 6차원 38에이전트 적대감사에서 확정된 16건 중 첫 실주문 신뢰성 직결 5종. B1=고가주 유니버스 사장, B2=한도 후 손절차단(야간 실자금 무방비), H3=결산 통화혼합 오표기, H4=소액손실 서킷 약화, 중복주문=5xx 재시도 실자금 중복(라이브 로그에 실제 500 발생 확인). 7에이전트 적대 검증 후 운영자 결정으로 B2·중복주문을 KRX에도 적용(아래).
- 영향: **B1·H3·H4는 KRX 바이트 불변**(B1 min_quantity 기본0·H4 KRX 정수값 유지[reset int 0 시드]·H3 KRX trades만 필터). **B2·중복주문은 운영자 승인하 KRX에도 의도 적용** — 두 변경 다 KRX 실자금에 **더 안전**: B2는 KRX도 한도(10) 후 보호매도 작동(손절차단 해제), 중복주문은 KRX 주문도 5xx/타임아웃 시 fail-fast(중복 방지). KRX 정상 성공경로는 바이트 동일, exit_reason은 'completed' 유지(buy_limit_reached를 CYCLE_END 메트릭에 별도 기록)해 기존 대시보드 무영향. US는 추가로 고가주 매수·결산 통화정확·센트 손익 추적.
- 검증 결과: pytest 전체 **1245 passed**(신규 15) | mypy strict ✅ | ruff ✅(변경분). 7에이전트 적대 검증(KRX 불변·결함해소·신규회귀) 통과.
- 비고: 운영자 액션 — main 머지 후 pull → **`com.kis.autotrader`(KRX)·`com.kis.autotrader.us`(US) 둘 다 재시작**(B2·중복주문이 KRX에도 적용되므로). DB/마이그 불변. 남은 감사 medium 4·low 6(결산진단 시장필터·마감컷오프 US전용·재시작 카운터복원 등)은 후속.

---

## [2026-06-18] 매수가능 통합증거금 필드 우선 파싱 — US 동적매수 buyable=0 라이브 블로커 (v0.19.4)
- 카테고리: bug_fix
- 변경 파일:
  - src/api/overseas_account.py: get_buyable_amount이 psamount 응답에서 통합증거금 반영 필드(ovrs_max_ord_psbl_qty 해외최대주문가능수량·frcr_ord_psbl_amt1 외화주문가능금액)를 **우선** 파싱. 기존엔 ord_psbl_qty/ord_psbl_frcr_amt(외화 **현금 한정**)만 읽어 통합증거금(원화담보 환산) 매수여력을 0으로 보고 → 전 종목 buyable=0. 각 후보 중 첫 양수값 채택(_first_pos_int/_first_pos_dec, 0은 건너뜀 — _get 부재 시 "0" 반환이라 단순 or 부적합).
  - tests: 통합증거금 필드 우선(ord_psbl_qty=0이어도 ovrs_max_ord_psbl_qty=124 채택)·현금 폴백 회귀.
- 배경: US 라이브 매수가 마감가드(#67)·발굴(#66) 해소 후에도 전부 미체결. 진단 결과 psamount(TTTS3007R)의 ord_psbl_qty는 외화 현금만 반영 → 통합증거금 활성 계좌도 0. 실측 통합증거금 매수여력 $620.11(=itgr_ord_psbl_amt=frcr_ord_psbl_amt1, ovrs_max_ord_psbl_qty=124=620/5). KIS 앱 매수가 정상인 것과 모순돼 필드 추적 → 통합증거금은 ovrs_max_ord_psbl_qty/frcr_ord_psbl_amt1에 반영됨 확인(docs Excel "해외증거금 통화별조회" TTTC2101R itgr_ord_psbl_amt와 일치).
- 영향: 통합증거금 활성 US 계좌가 실제 매수여력(현금+원화담보 환산)으로 주문 수량 산정 → 동적 매수 실행 가능. 실주문은 여전히 min(risk_qty, buyable)·us_cash_budget 사이징 캡 적용(과대주문 없음). KRX 무관(해외 전용 psamount). 현금 필드 폴백 유지로 통합증거금 미활성 계좌도 동작.
- 검증 결과: pytest 전체 통과(통합증거금 우선 신규 회귀) | mypy strict ✅ | ruff ✅.
- 비고: 운영자 액션 — main 머지 후 pull → US 재시작 시 매수여력 정상 인식. DB/마이그 불변. #68(present-balance)에 누락됐던 분리 수정(force-push 차단으로 amend 미반영) — 이 PR로 본 블로커 해소.

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
