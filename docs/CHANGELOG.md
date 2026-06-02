# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-06-02] 일일 헬스체크 리포트 수정 — API 호출 0 버그 + 예수금 오해(보유평가 추가) (v0.8.7)
- 카테고리: bug_fix
- 변경 파일:
  - src/scheduler/healthcheck.py: ① `api_calls`를 존재하지 않는 `engine._daily_api_calls`(항상 0) 대신 rate limiter `engine._client._limiter.daily_count`에서 읽도록 수정. ② `HealthcheckResult.eval_amount`(보유 평가금액) 추가 + 리포트에 "보유평가" 표기.
  - tests/test_scheduler/test_healthcheck.py: api_calls 출처·보유평가 표기 테스트 갱신/추가.
- 배경: 실전 첫 매매(대한해운 005880) 후 일일 헬스체크 알림에서 "API 호출 0"(실제 8,091)·"예수금 500,000 불변"(매수 49,920원에도)이 데이터 누락처럼 보임. ①은 카운터 미연결 버그, ②는 D예수금(DNCA_TOT_AMT)이 T+2 정산 전 불변인 정상값이나 가용현금 오해 유발.
- 영향: 리포트 표시만 변경(매매 로직·잔고 무관). API 호출수 정확 표기, 보유평가 동반 표시로 자산 흐름 명확. DB 마이그레이션·신규 env 없음.
- 검증 결과: pytest 전체 **1014 passed**(헬스체크 테스트 갱신·추가) | mypy strict ✅ | ruff ✅(변경 파일). 잔존 7건은 공유 DB 기존 실패·무관.
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영(리포트 전용이라 포지션 보유 중 장중 재시작은 불필요, 장 마감 후 권장).

---

## [2026-06-01] 스크리닝 소스 필터 — 거래소 실시간 제외(관리/정리매매/ETF 등) + 보통주 [단계1] (v0.8.6)
- 카테고리: enhancement
- 변경 파일:
  - src/api/quote.py: `get_volume_rank`가 설정 기반 소스 필터 파라미터 전송 — `FID_TRGT_EXLS_CLS_CODE`(6→10자리 교정, 투자위험·관리·정리매매·불성실공시·거래정지·ETF·ETN·SPAC 제외) + `FID_DIV_CLS_CODE`(보통주) + `FID_BLNG_CLS_CODE`(랭킹기준 설정값).
  - src/config.py: `ScreeningConfig`에 `rank_metric`(기본 "0" 거래량), `exclude_targets`(기본 "1111011101"), `common_stock_only`(기본 true) 추가.
  - tests/test_api/test_quote.py: 소스 파라미터 전송 검증 테스트 추가.
- 배경: 실전 첫날 스크리닝 깔때기 진단 — 거래량 top-30의 ~60%가 ETF/ETN + 정리매매·페니로 76런 중 72런(95%)이 0생존. KIS volume-rank 소스단 제외/구분 필터를 미사용(`FID_TRGT_EXLS="000000"` 6자리). 거래소 실시간 지정 기반 제외는 market_actions 일일 sync 사각(230980 all-false)보다 신뢰.
- 영향: 관리종목/정리매매/투자위험/ETF/ETN/SPAC가 후보 풀에서 *소스* 차단 + 우선주 제외 → 230980·0162Z0류 원천 차단, 필터 생존율·품질 개선 기대. 단계1(랭킹은 거래량 유지); 단계2(거래금액순 `SCREENING_RANK_METRIC=3`)·단계3(진짜 시총)은 측정 후. 매매 로직 불변. DB 마이그레이션 없음, 신규 env 3종(기본값 안전).
- 검증 결과: pytest 전체 **1013 passed**(신규 1) | mypy strict ✅ | ruff ✅(변경 파일). 잔존 7건(test_order·pipeline_cli)은 공유 DB 기존 실패·무관.
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영. 하니스(screening_diag)로 적용 전후 후보수·converted 비교 권장. 모의/실전 TR(FHPST01710000) 동일 가정 — 첫 적용 시 파라미터 거부 여부 모니터.

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

