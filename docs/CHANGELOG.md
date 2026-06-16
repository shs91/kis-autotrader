# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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
