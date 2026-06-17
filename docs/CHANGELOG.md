# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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
