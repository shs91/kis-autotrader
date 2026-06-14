# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

## [2026-06-13] 테스트 환경 격리 — real .env 누수로 깨지던 pytest 8건 수정 (v0.11.1)
- 카테고리: bug_fix
- 변경 파일:
  - tests/conftest.py: pytest 전역 격리 신규. `KIS_ENV=virtual` 강제(실전 TR ID·DATABASE_URL_REAL 차단) + `STRATEGY_RSI_PERIOD`를 코드 기본값 "14"로 SET. 제안서 초안의 무차별 pop 방식은 config.py `load_dotenv(override=False)`가 .env 부재 키를 재주입 + `settings`가 import-시점 1회 빌드 싱글톤이라 9가 박혀 무효 → SET-to-default로 보정.
  - tests/test_harness/test_pipeline_cli.py: db_session fixture에 subprocess 이중 방어 2줄(`KIS_ENV=virtual` setenv + `DATABASE_URL_REAL` delenv)로 real DB 누수 차단.
- 배경: KIS_ENV=real 운영 환경에서 `pytest tests/`가 제안서·코드 무관 8건 실패(test_pipeline_cli 6·test_order 1·test_rsi 1). tests/conftest.py 부재로 운영 .env(KIS_ENV/DATABASE_URL_REAL/STRATEGY_*)가 테스트 프로세스에 누수. baseline stash로 사전존재 확정.
- 영향: real env `pytest tests/` **8 failed → 0 failed (1048 passed)**. BRIDGE_SPEC "pytest 전체 그린" 게이트 복구(real 환경 자동 구현 검증 정상화). pipeline_cli subprocess의 kis_trader_real 연결·오염 위험 제거. 테스트 결정론화(운영 튜닝 변동 비의존). 운영 코드(src/)·매매 동작 불변(테스트 전용).
- 검증 결과: pytest real env **1048 passed / 0 failed**(8건 fix, 신규 회귀 0) | verifier diff-scope 15 passed | mypy strict ✅(96 files) | ruff ✅(변경 파일).
- 비고: 운영자 액션 불필요(테스트 전용, 매매 서비스 무관). 미해결 후속: config_overrides.json 파일 누수(STRATEGY_MIN_CONFIDENCE 등)는 개별 명시 주입 표준화 별도 과제.

---

## [2026-06-13] 수급 섀도우 필터 — flow_filter 순수 스코어러 추가 (v0.11.0)
- 카테고리: enhancement
- 변경 파일:
  - src/strategy/flow_filter.py: 신규. 수급 텍스트(투자자별 매매·공매도 잔고) 파서 `FlowFeatures`+`parse_flow_text()` + `[-1.0, 1.0]` 범위 `flow_score()` 순수 함수. 점수=(기관합계+외국인 순매수)/(|기관|+|외국인|+|개인|), 양수=기관·외국인 매수우위(강세). 공매도는 피처만 노출(점수 미반영).
  - tests/test_strategy/test_flow_filter.py: 신규 5건(파싱 정확성·부호·외국인vs기타외국인 구분·flow_score 경계·빈/무관 텍스트 0.0 안전반환).
- 배경: 실전 news_chunks의 수급 데이터가 chunk_text에 자유 텍스트로만 존재 → 매매 보조신호로 쓰려면 숫자 파싱·점수화 선행 필요. 전체 활용(수집·배선)은 worker/db/rag 인프라라 안전게이트 밖(수동 계획 docs/plans/2026-06-12_news-flow-data-utilization.md). 본 건은 순수(무 I/O) 파서+스코어러만 안전 도입.
- 영향: 수급 점수화 로직+회귀 테스트가 검증된 상태로 확보 → 수동 계획 Phase 3에서 엔진 read-only 배선 즉시 가능. 매매 동작 **무변경**(순수 함수, 미배선)이라 실거래 리스크 0. DB/스키마/config_overrides 불변.
- 검증 결과: pytest test_flow_filter **5 passed** | mypy strict ✅(flow_filter.py) | ruff ✅. 전략 모듈 경계(데이터 인자 수신, api/ 직접호출 없음) 준수.
- 비고: 운영자 액션 불필요(미배선). 호출부 배선은 수동 계획 Phase 3 별도 과제.

---

## [2026-06-12] 공격적 진입 전환 — 단독 BUY 임계↓ + 스크리너 정합 + 회전 가속 (v0.10.1)
- 카테고리: param_tuning
- 변경 파일:
  - config_overrides.json: 진입 16개 파라미터 전체교체 — SOLO_BUY_MIN_CONFIDENCE 0.70→0.45, MIN_CONFIDENCE 0.20→0.05, MAX_POSITION_RATIO 0.1→0.3, 스크리너 전략중심(WEIGHT_STRATEGY 0.3→0.5·CHANGE_RATE 0.4→0.2), CHANGE_RATE_MIN/MAX -8~8, MAX_PRICE 20k→150k, TOP_N 30→50, MAX_SCREENED 5→20, INTERVAL_CYCLES 30→15, PER_STOCK 1→3, RSI_OVERSOLD 35→38. 청산 게이트(손절·MDD·트레일링) 불변.
  - src/strategy/risk.py: `RiskManager.__init__`에 `min_confidence` 주입 파라미터 추가(기본 None=settings, 운영 동작 불변) — 다른 7개 리스크 파라미터와 동일 패턴, 테스트 격리용.
  - tests/test_strategy/test_risk.py: `TestValidateOrder`가 `RiskManager(min_confidence=0.1)` 명시 주입하도록 격리(운영 MIN_CONFIDENCE=0.05 의존 제거).
- 배경: 실전 2주(05-29~06-11) 부진 원인이 리스크 게이트 차단이 아니라 "살 종목 부재"로 정량 확정 — 스크리너 등락률 편중(급등주)→평균회귀 전략 SELL 판정→후보 60% 미보유 SELL 폐기, 2주 BUY 종목 대한해운 1개뿐. 청산 게이트 거의 미발동(손절 1회).
- 영향: 진입 3축(단독 BUY 임계↓·스크리너 전략정합·후보/회전/사이즈↑) 완화로 BUY 전환·회전율 상승 기대, SELL-only 낭비 감소. 청산 안전장치(손절 2%·MDD 4%·트레일링 +5%/-5%) 전부 불변. 거래비용·승률↓·변동성↑ 가능 → 소액 forward 관측 권장. config_overrides로 즉시 롤백(SOLO_BUY 1.01).
- 검증 결과: pytest **1035 passed / 8 failed** | mypy strict ✅(95 files) | ruff ✅(변경 파일). 잔존 8건(test_order·pipeline_cli 6·test_rsi)은 real 환경 사전존재로 제안서 무관(baseline stash 재현) — test_rsi는 수반 .env RSI_PERIOD 14→9 반영, 제안서 유발 신규 회귀 0.
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영. .env 진입 민감도 변수(MA_LONG 15·RSI_PERIOD 9·MA_MAX_DIVERGENCE 0.10·RSI_OVERBOUGHT 78·DAILY_TRADE_LIMIT 50·MAX_CONSECUTIVE_LOSSES 7)는 운영자 수동 선적용. MAX_POSITION_RATIO 0.3은 고위험 항목으로 운영자 승인.

---

## [2026-06-12] 앙상블 단독 BUY 조건부 허용 + 보유중 BUY 관측 수정 (v0.10.0)
- 카테고리: enhancement
- 변경 파일:
  - src/strategy/ensemble.py: `_weighted_vote`의 단독표 억제(`n_win<2`→HOLD)를 **BUY 한정 완화** — 종합 신뢰도가 `solo_buy_min_confidence` 이상이면 단독(n_win=1) BUY 진입 허용. SELL/HOLD는 기존 억제 유지. `__init__`에 임계 인자 추가.
  - src/config.py: `StrategyConfig.solo_buy_min_confidence`(기본 0.7, env `STRATEGY_SOLO_BUY_MIN_CONFIDENCE`, 1.01=비활성).
  - src/strategy/registry.py: EnsembleStrategy 생성 시 임계 주입.
  - src/engine.py: 보유 종목 BUY 차단을 `skip_reason="held_skip_buy"`로 기록(매매 무변경, 877행).
  - tests/: test_ensemble 단독 BUY 4종 + test_engine_held_observability 2종(신규 6).
- 배경: 이번주(6/8~) 0매매 병목을 `signals`+`system_metrics.SIGNAL_SKIP.vote_meta` **두 채널**로 정량 확정 — 개별 BUY표는 많으나(MACD 4,504·RSI 4,686·MA 2,250) 같은 종목·봉서 2개 겹친 사이클 0건(`n_buy=2`=0) → 앙상블 `n_win≥2` 단독표 억제로 BUY 0 → 매매 0. 강한 단독 BUY 084650(0.86)·093370(1.0)이 묵살됨. (한 채널만 보면 양쪽 오진 — 다회 정정 끝에 확정)
- 영향: 강한 단독 BUY(conf≥0.7) 진입 허용 → 매수 재개 기대. 약한 단독(003280 0.23·027360 0.04)은 거름. 위험게이트·min_confidence·예수금·한도 모두 유지. config_overrides로 즉시 롤백(1.01). 보유중 BUY 차단 관측 투명화(skip_reason).
- 검증 결과: pytest 전체 **1036 passed**(신규 6) | mypy strict ✅ | ruff ✅(변경 파일). 잔존 7건(test_order·pipeline_cli)은 공유 DB 기존 실패로 무관.
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영. 효과 제한적 가능(일봉 +1.25%/+7.25%, 6/2 실거래 -3.67%) + forward 검증 일중가 부재 → **소액 관측**. `STRATEGY_SOLO_BUY_MIN_CONFIDENCE` 조정/롤백은 config_overrides.

---
