# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-06-08] 자동 구현 git_clean — docs 산출물 untracked 제외(교착 해소) (v0.9.1)
- 카테고리: bug_fix
- 변경 파일:
  - src/harness/initializer.py: `_check_git_clean`이 docs/proposals·docs/reports의 untracked 파일을 위반에서 제외(`_is_ignorable_untracked`). `git status --porcelain`에 `--untracked-files=all` 추가로 디렉토리 축약(`?? docs/`) 비의존. src/ 코드 변경·tracked 수정은 그대로 FAIL.
  - tests/test_harness/test_initializer.py: docs 예외 2종(proposals·reports PASS) + 안전 가드 4종(clean PASS / src untracked·modified tracked·mixed FAIL) TDD.
- 배경: 2026-06-06 제안서(event-logs-error-integrity)가 자동 구현되지 않은 원인 분석. Initializer가 untracked 제안서/리포트까지 git_clean FAIL로 잡아, 코디네이터가 사이클을 비결정적으로 보류(6/3 통과·6/8 no-op). DB엔 06-06이 READY로 적재됐으나 `list_ready` 조회조차 없이 completed=0 종료(progress.json history 빈 채, diff 0).
- 영향: 분석 파이프라인 산출물(제안서·리포트)이 커밋 전 untracked로 남아도 git_clean PASS → 다음 사이클이 정상 처리. src/ 코드 변경·tracked 수정 차단은 유지(안전). 매매 로직·DB 마이그레이션·신규 env 없음.
- 검증 결과: pytest test_initializer **11 passed**(신규 6) | mypy harness 26 files ✅ | ruff 변경파일 ✅. 잔존 pipeline_cli 6건은 공유 DB 기존 실패로 무관(baseline stash 재현 확인).
- 비고: 운영자 액션 불필요(자동 구현 파이프라인 Initializer만 영향, `com.kis.autotrader` 매매 서비스 무관). 다음 auto-implement 사이클(6/9 17:15)이 06-06 제안서를 자동 처리할 전망.

---

## [2026-06-08] 장 마감 매매 진단 알림 — 결산 직후 "왜 매매했나/안했나" 가시화 (v0.9.0)
- 카테고리: enhancement
- 변경 파일:
  - src/db/analytics.py: `build_daily_diagnostics` 추가 — 당일 system_metrics(EVAL_TARGETS·SIGNAL_SUMMARY·SIGNAL_SKIP·SCREENING_CANDIDATE·SCREENING_RISK_EXCLUDED·BUY_REJECT)+trades 집계. `signals` 테이블 미사용(적재 공백 이슈와 독립). 보조 헬퍼 `_resolve_stock_names`(stocks.code→name), `_diagnostics_headline`.
  - src/notify/formatter.py: `format_diagnostics` + `_REJECT_LABELS`(BUY_REJECT reason 코드→한글 라벨).
  - src/notify/telegram.py: `notify_diagnostics` 메서드(worker 동적 디스패치 `notify_{type}`로 자동 연결).
  - src/engine.py: `post_market` 결산 enqueue 직후 `_enqueue_telegram_diagnostics` 적재. 집계 실패는 try/except로 격리(결산·매매 무영향).
  - tests/: test_analytics_diagnostics·test_engine_diagnostics 신규 + formatter·telegram·worker handlers 라우팅 테스트(신규 8건).
- 배경: 매매 0건이 지속되나 텔레그램은 *체결*만 알려 "왜 안 사는지" 불가시(누적 체결 2건, 6/2 이후 신규 매수 0). 근본은 발굴 빈약(스크리닝 candidate≈0)+모니터링 종목 전원 HOLD+stale 잔류. 이를 매일 가시화해 "정상 보수화 vs 버그" 판별 + 향후 A(임계완화)·B(stale 만료) 튜닝 효과 측정 기준선 확보(옵션 C).
- 영향: 결산 직후 `[매매 진단]` 무음 알림 1건 추가(모니터링/후보/max_conf/매수게이트 차단/잔고). 매매 로직 불변. DB 마이그레이션·신규 env 없음.
- 검증 결과: pytest 전체 **1022 passed**(신규 8) | mypy strict ✅ | ruff ✅(변경 파일). 잔존 7건(test_order·pipeline_cli)은 공유 DB 기존 실패로 무관(분기 이전 커밋 85e8fe7에서 동일 7건 재현 확인).
- 비고: 운영자 액션 — `com.kis.autotrader` 재시작 시 반영(장 마감 후 권장). 머지 후 `scripts/record_implementation.py` 실행으로 버전 bump(0.8.8→0.9.0, enhancement=minor)+DB 이력 기록.

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
