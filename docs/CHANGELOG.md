# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

## [2026-06-09] event_logs 적재 정합 — 종목 처리 ERROR를 event_logs에도 기록 (v0.9.2)
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `log_error` import 보강 + `_record_error(stock_code, error)` 헬퍼 신설(`system_metrics(ERROR)` enqueue + `event_logs(ERROR)` 양쪽 일관 적재, `log_error` 호출은 try/except로 방어해 매매 흐름 보호). 종목 처리 예외 블록을 인라인 `_record_metric("ERROR", {...})`에서 `self._record_error(stock_code)` 호출로 치환(기존 metric payload cycle/stock_code/error 보존).
  - tests/test_engine_error_event.py: 신규 — `_record_error`가 metric+event_logs 양쪽 적재하는지(detail 필드 검증) + `log_error` 예외가 swallow되는지 TDD 2건.
- 배경: W23 주말 리뷰에서 실전 DB(kis_trader_real) 직접 조회 결과, 종목 처리 ERROR가 `system_metrics`에만 적재되고 `event_logs` ERROR 행은 전 기간 0건인 관측성 결함 확인(06-05 ERROR 2건도 event_logs 누락). engine.py가 `log_error`를 import/호출하지 않아 일간 리포트 "에러/경고" 섹션과 공통규칙 룰C(에러 반복)가 event_logs 기준으로 항상 0건으로 보임.
- 영향: 종목 처리 에러가 `event_logs`(ERROR)에도 적재되어 일간·주간 분석이 event_logs 기준으로도 에러 추적 가능. system_metrics ERROR와 event_logs ERROR 불일치 해소. 매매 동작/시그니처/수익률 불변(순수 관측성 보강). DB 마이그레이션·신규 env 없음.
- 검증 결과: pytest test_engine_error_event **2 passed**(신규) | test_engine_db_integration 30 passed | test_engine_buy_gate_metric 10 passed | mypy src/engine.py ✅ | ruff ✅(변경 파일).
- 비고: 06-01·06-02 event_logs의 팬텀 '테스트' 매매(고아체결 회수 경로 의심)는 매매/회수 경로를 건드려야 하므로 본 제안 범위 밖(별도 조사). 운영자 액션 — `com.kis.autotrader` 재시작 시 반영.

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
