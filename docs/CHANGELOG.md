# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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
- 검증 결과: pytest 신규 5 + 스케줄러/config 회귀 45 passed | mypy ✅ strict(변경 2파일) | ruff ✅(추가 라인; jobs.py 기존 E501 2건은 본 변경과 무관·범위 외). 장중 전체 스위트는 운영 로그(logs/autotrader.log) 오염 방지 위해 장 마감 후 실행 권장.
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

## [2026-05-30] 실전 전환 전 안전장치 6종 — 킬스위치·DB프리체크·고아체결 회수·halt 재시작 복원·긴급알림 폴백 (v0.8.0)
- 카테고리: feature
- 변경 파일:
  - src/engine.py: 수동 킬스위치(`run_trading_cycle` 진입부 — `halt_file` 존재 시 사이클 전체 동결 + 1회 Telegram 알림, 해제 시 재개). 주문 직전 DB 헬스체크(`_execute_buy`/`_execute_sell`가 `db_healthcheck()` 실패 시 주문 보류 + `ORDER_SKIPPED_DB_DOWN`). 고아 체결 회수(`_reconcile_orphan_fill` — `_cancel_pending_order`가 취소 직전 잔고 재확인, 지연 체결이면 트레이드 기록 후 취소 스킵). 장중 재시작 리스크 복원(`_restore_risk_state_if_needed` — pre_market 미실행 시 당일 `trades` 재생으로 halt/연패/누적손익 결정적 재구성 + peak_prices 재적재, 1회 한정). `PendingOrder`에 qty_before/price/avg_price/signal_type 추가.
  - src/strategy/risk.py: `RiskManager.snapshot()`/`restore()` — 포트폴리오 리스크 상태 직렬화·복원(타입·누락 키 방어).
  - src/db/session.py: `db_healthcheck()` — `SELECT 1`로 DB 가용성 점검(예외 swallow→False).
  - src/notify/telegram.py: 긴급(urgent) 전송 실패 시 `logs/urgent_alerts.fallback.log`에 추기(치명 알림 소실 방지).
  - src/config.py: `TradingConfig` 플래그 3종 — `halt_file`(기본 `.trading_halt`), `db_precheck_before_order`(실전=true·모의=false 기본), `reconcile_orphan_fills`(기본 true).
  - scripts/bootstrap_real_db.sh: 신규 — kis_trader_real 스키마 1회 부트스트랩(`KIS_ENV=real alembic upgrade head`, 운영자 실행).
  - tests: test_engine_safety_phase0.py 9종(킬스위치/DB프리체크/고아체결/재시작복원), test_strategy/test_risk_snapshot.py 4종, test_notify/test_telegram_fallback.py 3종 신규.
- 배경: 2026-05-30 모의→실전(시드 50만원) 전환 준비도 검토(7개 차원·다중 에이전트 적대 검증). 실전 전용 안전경로에 확인된 치명 공백 — 손절 사이클당 1회 검사(갭 우회), halt 상태 in-memory(재시작 시 유실→한도 우회), 미체결 취소 시 고아 체결 미정합(추적 불가 포지션), DB장애 중 주문, 텔레그램 알림 미보장, kis_trader_real 미마이그레이션. 6/1 전면 자동매매 전환은 No-Go, 본 PR은 Phase 0 안전장치.
- 영향: 운영자 비상정지(`touch .trading_halt`) 가능. DB 불가 시 'KIS엔 체결·DB엔 미기록'인 추적 불가 실포지션 예방(실전 기본 on). 폴링 윈도를 지난 지연 체결을 취소 대신 회수해 DB 정합 유지. 장중 크래시 재기동 후에도 당일 손실 한도(halt/연패/MDD)가 정본 trades로 복원되어 우회 차단. 긴급 알림 파일 폴백으로 깜깜이 방지. 매수/매도 정상 경로·기존 테스트 전부 불변. DB 마이그레이션 없음(신규 env 3종은 선택, .env.example 문서화).
- 검증 결과: pytest **1005 passed**(신규 16 포함) | mypy ✅ strict | ruff ✅(변경 5파일).
- 비고: 운영자 액션 — ①실전 첫 기동 전 `scripts/bootstrap_real_db.sh` 1회 실행 ②안전장치 반영 위해 `com.kis.autotrader` 재시작. 실시간 손절 모니터링·50만용 설정(DAILY_TRADE_LIMIT 등)은 Phase 1 과제로 미포함.

---

## [2026-05-30] 관측성 메트릭 2종 — acted→체결 퍼널(BUY_OUTCOME) + 단기 신호 반전(SIGNAL_REVERSAL) (v0.7.1)
- 카테고리: performance
- 변경 파일:
  - src/engine.py: `_execute_buy`의 8개 상호배타 종단에 `BUY_OUTCOME` 메트릭 1건씩 적재(`_record_buy_outcome` 헬퍼, outcome=FILLED/UNFILLED/ORDER_FAIL/ORDER_UNTRADABLE/SUPPRESS_PENDING/BLOCK_DISCLOSURE/BLOCK_MARKET_ACTION/SKIP_UNTRADABLE_TODAY). `_observe_signal_reversal` + `_last_signal_by_stock` 인메모리 상태(직전 BUY/SELL 기억, 윈도 내 반대방향 신호 시 `SIGNAL_REVERSAL` 기록, HOLD 제외), `pre_market` 일일 리셋.
  - src/config.py: `TradingConfig.signal_reversal_window_seconds`(기본 600, env `SIGNAL_REVERSAL_WINDOW_SECONDS`).
  - tests: test_engine_buy_funnel.py 신규(종단별 outcome + 상호배타 invariant), test_engine_signal_reversal.py 신규 6종(윈도/방향/종목분리/HOLD제외/pre_market 리셋).
- 배경: 5월 월간·W22 리포트가 두 관측 공백을 지목. ①ENSEMBLE acted 5,332 vs 실체결 29(0.54%) 괴리가 `_execute_buy` 어느 종단(공시/시장조치/미체결/중복억제/실패)에서 새는지 단일 쿼리로 불가시. ②062970이 09:15 STOP_LOSS 매도 42초 뒤 BUY 재진입하는 등 정상 종목의 단기 신호 반전이 미계량(수작업 발굴 의존).
- 영향: `system_metrics(BUY_OUTCOME)` GROUP BY outcome로 acted→체결 깔때기를 일·주 단위 분해(v0.7.0 사전배제 효과 정량 검증, BUY_OUTCOME 총합=acted·FILLED=실체결). `system_metrics(SIGNAL_REVERSAL)`로 반전 빈발 종목/시간대 정량화 → 신호 cooldown 또는 앙상블 confidence 평활화(EMA) 도입의 데이터 근거. 둘 다 매수/매도/게이트 경로 불변(순수 관측), 기록 실패 swallow. DB 마이그레이션·신규 의존성 없음.
- 검증 결과: pytest **17 passed**(신규 테스트 2종) | mypy ✅(src/engine.py·config.py) | ruff ✅ | golden 회귀 PASS(10 invariant, 사전·사후 동일).
- 비고: 운영자 액션 — 메트릭이 사이클에서 적재되려면 `com.kis.autotrader` 재시작 필요(매매 동작 변경은 없음).

---

