# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-06-15] 재매수 쿨다운 — 매도 후 동일종목 재매수 차단 (휩쏘 방지) (v0.15.0)
- 카테고리: enhancement
- 변경 파일:
  - src/config.py: TradingConfig.buy_cooldown_after_sell_min (env BUY_COOLDOWN_AFTER_SELL_MIN, 기본 120분, 0=비활성).
  - src/engine.py: _last_sell_at(종목별 매도확정 KST 시각) 기록(_execute_sell 체결확정 시) + 매수 분기 쿨다운 게이트(REBUY_COOLDOWN 거절) + pre_market 리셋. tz-aware(_KST)로 골든 G01(engine naive datetime 금지) 준수.
  - tests/test_engine_rebuy_cooldown.py: 신규 3건(차단·경과허용·타종목).
- 배경: 06-15 멀티소스 활성 후 휩쏘 관측 — HL만도 69,700 익절(+6.4%) → 1.5h 뒤 73,600 고가 재매수 → 72,100 손절(−2.2%); 대한항공 동가 재매수. 매도해도 후보풀 잔류 + 전략 재BUY로 즉시 재진입(MAX_DAILY_TRADES_PER_STOCK는 매수횟수만 세 못 막음).
- 영향: 매도 후 N분(기본 120) 동일종목 재매수 차단 → 익절 되돌림·동가 churn 방지. 정상 신규매수·매도·청산엔 영향 없음. config_overrides로 튜닝/비활성. DB/스키마 불변.
- 검증 결과: pytest 전체 **1078 passed**(신규 3) | mypy strict ✅(96 files) | ruff ✅(변경분) | 골든 G01 통과.
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영. `BUY_COOLDOWN_AFTER_SELL_MIN`으로 분 단위 조정(롤백=0).

---

## [2026-06-15] 매수 사이징 실주문가능액 캡 — rt_cd=7 폭주 차단 (증분4) (v0.14.1)
- 카테고리: bug_fix
- 변경 파일:
  - src/api/account.py: get_buyable(TTTC8908R/inquire-psbl-order) + Buyable DTO. ord_psbl_cash(주문가능현금)·nrcvb_buy_qty(미수없는=현금만 매수수량)·max_buy_qty 반환.
  - src/engine.py: 매수 직전 _get_buyable_qty로 nrcvb_buy_qty 캡(quantity=min(risk, buyable)). 부족/조회불가 시 INSUFFICIENT_BUYABLE로 매수 보류(주문 미시도).
  - tests/test_api/test_account.py(신규 3)·tests/test_engine_buy_funnel.py(_get_buyable_qty 2).
- 배경: 06-15 멀티소스 활성 후 매수 주문 실패 1,266건(HL만도 862·디앤디 247·대한항공 149). 엔진이 deposit(DNCA_TOT_AMT 예수금총액)으로 사이징 → KIS 실주문가능액(T+2 미결제·타포지션 점유) 초과 → rt_cd=7 거부. 실패는 성공매수로 안 잡혀 MAX_DAILY_TRADES_PER_STOCK에 안 걸리고 매 사이클 무한 재시도(+현재가 호출 인플레로 자가 일일캡 85% 견인).
- 영향: 매수가능조회로 현금 기준 수량 캡 → rt_cd=7 제거, 재시도·현재가 폭주 차단. 부족 시 주문 미시도 보류(보수적). 정상 매수는 영향 없음(현금 충분 시 캡≥risk_qty라 동일). DB/스키마/config 불변.
- 검증 결과: pytest 전체 **1075 passed**(신규 5) | mypy strict ✅(96 files) | ruff ✅(변경분).
- 비고: 멀티소스(v0.13/0.14)와 결합 시 rt_cd=7 없이 후보 확대 효과만 취득. KIS 일일 호출 제한 없음(초당만) — 자가 캡 API_DAILY_CALL_LIMIT 별도 검토. 운영자 액션 — `com.kis.autotrader` 재시작 시 반영.

---

## [2026-06-15] 수급 flow_score 스크리너 배선 — 멀티소스 가산 신호 (증분2, default-off) (v0.14.0)
- 카테고리: enhancement
- 변경 파일:
  - src/config.py: flow_enabled(false)·weight_flow(0.0). weight_flow는 5축 합(=1.0)과 별개의 signed 가산항.
  - src/strategy/screener.py: score_merged/score_merged_candidate에 flow_score 인자(total += weight_flow×flow_score), ScoredCandidate.flow_score 필드.
  - src/worker/screener.py: 멀티소스 분석 풀에 한해 get_investor_trend_daily 1콜(일일 캐시)로 flow_score 산출 → score_merged 전달. flow_score가 공매도 미사용이라 short_sale 미조회(예산 절감). flow_enabled=false면 0.0(무동작).
  - docs/BRIDGE_SPEC.md: SCREENING_WEIGHT_FLOW(0~0.3)·flow 가산항(합 제약 별개)·flow 스위치 명시.
  - tests/test_strategy/test_screener.py: 신규 2건(flow 부호 가산·default-off 미반영).
- 배경: v0.12.0 flow_filter shadow(순수 스코어러)의 Phase 3 배선. 구조화 수급(기관·외국인 순매수, FHPTJ04160001)을 스크리너 스코어에 read-only 반영해 smart-money 방향을 후보 랭킹에 보강.
- 영향: 기관·외국인 순매도 종목 demote 가능(가산 음수→min_score 컷). default-off라 운영자 opt-in 전 무동작. per-stock 예산은 분석풀(≤MAX_ANALYSIS_POOL)·일일 캐시·investor_trend 1콜로 한정. 멀티소스 ON 위에서만 동작.
- 검증 결과: pytest 전체 **1070 passed**(신규 2) | mypy strict ✅(96 files) | ruff ✅(변경분).
- 비고: 활성화는 config_overrides로 `SCREENING_FLOW_ENABLED=true` + `SCREENING_WEIGHT_FLOW` 상향(멀티소스도 ON 필요). 운영자 액션 — `com.kis.autotrader` 재시작 시 코드 반영(OFF면 동작 무변경).

---

## [2026-06-15] 스크리너 다중 순위 병합 + 체결강도/호가잔량 스코어 (증분1, default-off) (v0.13.0)
- 카테고리: enhancement
- 변경 파일:
  - src/api/quote.py: RankItem + get_change_rate_rank(FHPST01700000)·get_volume_power_rank(FHPST01680000)·get_quote_balance_rank(FHPST01720000). 모의 미지원/에러→빈 리스트 방어, 엔드포인트별 코드키(stck_shrn_iscd/mksc_shrn_iscd) 흡수.
  - src/strategy/screener.py: MergedCandidate·merge_rankings(union/dedup·market_cap best-effort)·score_merged(5축)·prelim_score(예산 가드 사전컷)·rank-decay. ScoredCandidate에 volume_power_score/quote_balance_score 추가. 필터 market_cap None 통과(breadth).
  - src/config.py: weight_volume_power/quote_balance(0.0)·multisource_enabled(false)·max_analysis_pool(40).
  - src/worker/screener.py: 마스터스위치 분기 — OFF=현행 단일소스(불변)·ON=4소스 fetch→merge→필터→prelim cap→분석→score→DB + SCREENING_MULTISOURCE 관측 메트릭.
  - docs/BRIDGE_SPEC.md: 가중치 제약 3→5축, 신규 파라미터·마스터스위치 명시.
  - tests/: test_quote(순위 3종 파싱·방어 6건)·test_screener(병합·rank-decay·default-off·prelim 8건).
- 배경: 스크리너 거래량 단일소스 → candidate 구조적 빈약(메모리: 약세장 0매매 주원인). KIS 순위 3종(등락률·체결강도·호가잔량)은 env=real에서 동작 → 후보 폭 확대 + 신호 스코어링.
- 영향: 후보 폭 확대로 매매 활성화 기대. **마스터스위치 default false → 출시 시 매매 동작 현행과 완전 동일**, 운영자 2단계 opt-in(스위치 ON→가중치 상향). 예산 가드(MAX_ANALYSIS_POOL=40)로 daily-price 폭증 방지. 다운스트림 게이트(앙상블·리스크) 불변.
- 검증 결과: pytest 전체 **1068 passed**(신규 13) | mypy strict ✅(96 files) | ruff ✅(변경분).
- 비고: 06-15 운영자가 config_overrides로 `SCREENING_MULTISOURCE_ENABLED=true` 활성(스테이지1, 가중치 0). 설계 docs/superpowers/specs/2026-06-15-screener-multisource-design.md.

---

## [2026-06-14] flow_filter 구조화 수급 소스 — 투자자매매동향·공매도 API (shadow) (v0.12.0)
- 카테고리: enhancement
- 변경 파일:
  - src/api/quote.py: QuoteAPI에 get_investor_trend_daily(FHPTJ04160001)·get_short_sale_daily(FHPST04830000) + DTO InvestorTrendDaily/ShortSaleDaily 추가. 둘 다 모의 미지원(실전 전용) → try/except KISAutoTraderError + rt_cd 체크로 None 방어(현 virtual 무동작). 공매도 비중(ssts_vol_rlim) 신규 노출.
  - src/strategy/flow_filter.py: features_from_structured() 순수 매퍼 추가 — 구조화 API 필드→FlowFeatures(텍스트 파싱 대체 경로). flow_score 무변경(비율이라 단위 불변), parse_flow_text 유지(하위호환).
  - tests/test_api/test_quote.py: 신규 5건(파싱·음수·rt_cd≠0/빈 output2/HTTP에러 None 방어).
  - tests/test_strategy/test_flow_filter.py: 신규 2건(매퍼-텍스트 flow_score 동등성·부분입력 안전).
- 배경: flow_filter(v0.11.0 shadow)의 수급 입력이 news_chunks 자유텍스트 정규식 파싱 의존 → 라벨/레이아웃 변경에 취약(생존편향)·수집 종목 한정. KIS 구조화 API(FHPTJ04160001·FHPST04830000)가 동일 피처(기관/외국인/개인 순매수·공매도 체결수량/비중)를 JSON으로 제공.
- 영향: 텍스트→구조화 소스 전환의 첫 단계(shadow, 미배선). 엔진/스크리너 배선은 범위 밖(수동 Phase 3). 매매 동작 무변경 → 실거래 리스크 0. DB/스키마/config_overrides/외부패키지 불변.
- 검증 결과: pytest 전체 **1055 passed**(신규 7) | mypy strict ✅(96 files) | ruff ✅(변경 4파일). 사전존재 ruff 13건은 미변경 파일 베이스라인으로 무관.
- 비고: 두 API는 실전 전용(모의 미지원)이라 현 virtual에선 None(무동작), 실효는 실전 전환 시. 호출부 배선은 수동 Phase 3. 운영자 액션 — `com.kis.autotrader` 재시작 시 코드 반영(shadow라 동작 변화 없음).

---
