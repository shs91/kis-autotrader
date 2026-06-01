# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-06-01] ETF/ETN 필터 보강 — 문자 코드 + RISE·채권혼합 누수 차단 (v0.8.5)
- 카테고리: bug_fix
- 변경 파일:
  - src/strategy/screener.py: `_is_etf_etn` ① `startswith("Q")` → `not stock_code.isdigit()`로 일반화(문자 포함 코드=ETN/ELW/구조화상품 0162Z0 등 제외) ② `_ETF_BRAND_KEYWORDS`에 RISE·PLUS·KOSEF·KINDEX·TIMEFOLIO·히어로즈·마이다스·ETF·채권혼합·혼합형 추가.
  - tests/test_strategy/test_screener.py: ETF 회귀 테스트 5종(문자코드·RISE·채권혼합) + 미사용 import 정리.
- 배경: 실전 첫날(6/1) 스크리닝 깔때기 진단에서, ETF/펀드형 상품 `0162Z0 RISE 삼성전자SK하이닉스채권혼합50`이 매매 후보(converted)로 통과. 원인 — 코드가 Q로 시작 안 함 + 브랜드 키워드에 RISE/채권혼합 미등록.
- 영향: 문자 포함 코드와 RISE/채권혼합/ETF 등 펀드형 상품이 스크리닝 후보·모니터링에서 차단. 매매 로직 불변(ETF 판별만 강화). DB 마이그레이션·신규 env 없음.
- 검증 결과: pytest 전체 **1012 passed**(ETF 회귀 5건 포함) | mypy strict ✅ | ruff ✅(변경 파일). 잔존 7건(test_order·pipeline_cli)은 공유 DB 상태 기존 실패로 무관.
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영. 거래량 랭킹 소스 자체 개선(시총/유동성 결합)은 후속 과제.

---

## [2026-06-01] 스크리닝 필터 실효화 — 엔진이 Worker 선정분만 모니터링 + buy-time 가격 하한 (v0.8.4)
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: ① `_screen_stocks`가 `converted_to_trade=True`(Worker가 가격/등락률/ETF/위험 필터를 통과시켜 선정)인 종목만 모니터링에 편입(기존: 거래량 순위 원본 전체를 필터 무시하고 편입). ② `_execute_buy`에 하드 가격 안전 플로어 추가(`현재가<SCREENING_MIN_PRICE` 또는 ≤0이면 `BLOCK_PRICE_FLOOR`로 매수 차단).
  - tests/test_engine_db_integration.py: `_screen_stocks` 테스트 3종을 새 동작(converted-only)으로 갱신.
  - tests/test_engine_buy_funnel.py: 가격 하한 차단(BLOCK_PRICE_FLOOR) 테스트 추가.
- 배경: 실전 첫날(6/1) 진단 — 5원·-28.57% 정리매매성 종목 230980이 가격(≥1000)·등락률(-3~+15%)·ETF·위험 필터를 전부 우회해 모니터링됨. 근본원인 ① 엔진 `_screen_stocks`가 screening_results(=Worker가 `_record_to_db(ranked,…)`로 기록한 필터 전 거래량 순위 원본)를 순위순으로 편입하며 Worker 필터를 의도적으로 무시 ② market_actions에 230980 있으나 위험플래그 전부 FALSE(KIS 종목마스터 사각).
- 영향: Worker의 `SCREENING_*` 필터가 모니터링/매매 유니버스에 실제 반영(파라미터 튜닝이 비로소 유효). buy-time 가격 하한이 종목마스터 사각을 보완해 페니/정리매매 매수를 실시간 차단. 모니터링 종목은 필터 통과분으로 좁아짐(품질↑). DB 마이그레이션·신규 env 없음(기존 SCREENING_MIN_PRICE 재사용).
- 검증 결과: pytest 전체 **1008 passed**(신규/수정 4건 포함) | mypy strict ✅ | ruff ✅. 잔존 7건(test_order 1·pipeline_cli 6)은 공유 DB 상태 기존 실패로 본 변경과 무관(신규 실패 0).
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영. 모니터링 종목 수가 줄 수 있으므로(필터 생존분만) 스크리닝 소스/파라미터 튜닝과 함께 운용 권장.

---

## [2026-06-01] 장중 매매 사이클 1초 폭주 수정 — 간격 하한 설정화 + 0종목 폴백 (v0.8.3)
- 카테고리: bug_fix
- 변경 파일:
  - src/config.py: `TradingConfig.min_trading_interval_seconds`(기본 10.0, env `TRADING_MIN_INTERVAL_SECONDS`).
  - src/scheduler/jobs.py: `_calculate_trading_interval`의 0종목 폴백 `return 1.0`→설정 하한, `max(interval, 10.0)`→`max(interval, min_interval)`(하드코딩 하한 2곳을 설정값으로 통일).
  - tests/test_scheduler/test_jobs.py: 신규 5종(0/음수→하한, 소수종목 바닥, 대량 종목 산출값>하한, env 오버라이드).
  - .env.example: `TRADING_MIN_INTERVAL_SECONDS` 문서화.
- 배경: 실전 첫날(2026-06-01) 장중 모니터링에서 매매잡이 `interval[0:00:01]`(1초)로 폭주. 원인 — WATCHLIST 비움(스크리닝 의존)으로 셋업 시 `_stock_count`=0 → `_calculate_trading_interval(0)`이 `if stock_count<=0: return 1.0` 경로로 빠져 기존 "최소 10초" 하한을 우회. ~175 calls/분으로 일일 API 한도(5만)를 ~14시 소진 전망 + KIS `EGW00201`(초당한도) 간헐 거부(screener.get_volume_rank 3회 재시도 소진 traceback) + `max instances` WARNING 폭주.
- 영향: 0종목/소수종목 모두 설정 하한(기본 10초)을 따름 → 일일 API ~57k→~5.7k(종일 커버), EGW00201 버스트·max-instances WARNING 해소. 매매 로직·신호·게이트 경로 불변(사이클 간격만 변경, 손절/익절 반응 1초→10초·본 전략엔 충분). DB 마이그레이션 없음, 신규 env 1종(선택, .env.example 문서화).
- 검증 결과: pytest 스케줄러 간격 6건(기존 `test_zero_stocks`/`test_negative_stocks`를 새 하한 동작으로 갱신 + 설정가능성 테스트 1건 추가; 중복 신설 파일 제거) 통과, 전체 스위트 **1009 passed** | mypy ✅ strict | ruff ✅. 잔존 7건(test_order 1·pipeline_cli 6)은 공유 `kis_trader` DB 상태 의존 기존 실패로 본 변경과 무관. (jobs.py 기존 E501 2건도 범위 외)
- 비고: 운영자 액션 — 반영하려면 `com.kis.autotrader` 재시작(코드는 순수 변경, 재시작은 별도 액션). 더 빠른 반응 원하면 `TRADING_MIN_INTERVAL_SECONDS=5`(여전히 안전, ~11.5k/일). 근본적으로는 장중 스크리닝 종목 수로 간격을 재계산하는 것이 정석이나 본 패치는 하한 보장으로 한정(MAX_SCREENED_STOCKS=5 기준 어차피 10초).

---

## [2026-05-30] bootstrap_real_db.sh 수정 — venv 파이썬 해석 + settings.kis.env (v0.8.2)
- 카테고리: bug_fix
- 변경 파일:
  - scripts/bootstrap_real_db.sh: ① 시스템에 `python` 심볼릭이 없는 환경(macOS, python3만 존재) 대응 — `.venv/bin/python` > `python3` > `python` 순으로 `PYTHON` 해석 후 모든 호출에 사용(line26 `command not found` 해소). ② 인라인 검증의 `settings.env`(미존재 속성) → `settings.kis.env`로 수정.
- 배경: PR #47에 추가된 `bootstrap_real_db.sh`가 실전 전환 직전 운영자 실행 시 (1) `python: command not found`, (2) `'Settings' object has no attribute 'env'` 2중 실패. 실전 DB(`kis_trader_real`) 스키마 부트스트랩이 막혀 있었음.
- 영향: 스크립트 정상 동작 확인 — `kis_trader_real` 19개 테이블 + `alembic_version=a1b2c3d4e5f6`(head) 생성. 런타임 매매 코드 영향 없음(ops 스크립트 한정). DB 마이그레이션·신규 의존성 없음.
- 검증 결과: 수동 실행 — kis_trader_real 19 테이블 + alembic head 확인. 기존 테스트 불변(스크립트 변경).
- 비고: 운영자 액션 — 실전 첫 기동 전 1회 실행하는 스크립트. 이미 부트스트랩 완료된 경우 멱등(재실행 무해).

---

## [2026-05-30] 실체결 슬리피지 계측(FILL_SLIPPAGE) + 분석·졸업판정 도구 — 소액 실전 캘리브레이션 (v0.8.1)
- 카테고리: performance
- 변경 파일:
  - src/engine.py: `_record_fill_slippage`(기대가=주문 시점 현재가 대비 실체결가를 `FILL_SLIPPAGE` 메트릭으로 적재, `adverse_bps`=비용 방향[매수 더 비싸게/매도 더 싸게 체결 시 양수]). `_holding_avg_price`(체결 확인 후 캐시 잔고의 매입평균가 — 신규 진입은 이 값이 곧 실체결가, 추가 API 호출 없음). `_realized_price_via_executions`(매도측 실체결가를 당일체결조회로 best-effort, 실전 한정·order_no 매칭). `_execute_buy`는 신규 진입(qty_before==0) 체결 후, `_execute_sell`은 실전(real) 체결 후 계측 호출.
  - src/config.py: `TradingConfig.measure_fill_slippage`(기본 true, env `MEASURE_FILL_SLIPPAGE`, 관측 전용).
  - scripts/analyze_slippage.py: 신규 — `FILL_SLIPPAGE` 집계(매수/매도 평균·중앙·p90 adverse_bps) → 왕복비용(슬리피지×2 + 세금·수수료 21bps) 추정 → 모의 엣지(157bps, +1.57% gross) 대비 순엣지 및 50만원 확대 졸업 판정(표본≥20·순엣지>40% 기준).
  - docs/CALIBRATION_RUNBOOK.md: 신규 — 운영자 런북(사전준비→실전DB 부트스트랩→캘리브 설정표[DAILY_TRADE_LIMIT 5·MAX_LOSS_RATE 0.02·SCREENING_MAX_PRICE 20000 등]→기동→일일점검→졸업판정→롤백).
  - tests/test_engine_slippage.py: 신규 8종(bps 계산·비용방향·플래그 off·무효가격·잔고평균가·체결조회 매칭·매수흐름 통합).
- 배경: PR #47(v0.8.0 안전장치) 머지 후 Phase 1 캘리브레이션. 모의는 슬리피지 0·즉시체결이라 실전 체결 비용이 미측정 — 모의 엣지(+1.57%/거래)가 실전 비용 차감 후 생존하는지 알 수 없음. 소액(20~30만) 실전으로 슬리피지를 계측해 데이터 기반으로 50만 확대 여부를 판정한다.
- 영향: 매 체결 시 기대가 대비 실체결가 차이를 `system_metrics(FILL_SLIPPAGE)`에 적재. `analyze_slippage.py`로 왕복 비용·순엣지·졸업 판정을 1회 쿼리로 산출. 관측 전용 — 매수/매도/게이트 경로 불변, 기록 실패 swallow. DB 마이그레이션·신규 의존성 없음. 매수측은 체결 후 캐시 잔고 사용(추가 API 無), 매도측은 실전에서만 체결조회 1회 추가.
- 검증 결과: pytest **1013 passed**(신규 8) | mypy ✅ strict | ruff ✅.
- 비고: 운영자 액션 — `docs/CALIBRATION_RUNBOOK.md`대로 `.env` 캘리브 설정 + `scripts/bootstrap_real_db.sh` + `com.kis.autotrader` 재시작. 매도측 슬리피지는 실전 체결조회 신뢰도에 의존(모의는 미수집).

---

