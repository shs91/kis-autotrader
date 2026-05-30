# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

## [2026-05-30] 매매 0건 근본 대응 — 스크리닝 위험종목 사전 배제 + 헬스체크 거절사유 가시성 복구 (v0.7.0)
- 카테고리: enhancement
- 변경 파일:
  - src/strategy/disclosure_risk.py: 신규 — 치명 공시 키워드(`CRITICAL_DISCLOSURE_KEYWORDS`) + 순수 매처(`match_critical_disclosure`)를 단일 진실원천으로 분리. engine buy-time 게이트와 스크리닝 Worker가 공유(키워드 드리프트 방지).
  - src/worker/screener.py: `_run_screening`이 `filter_candidates` 직전 `_load_risk_blocked_codes`로 위험종목(market_actions 차단 OR 치명 공시)을 후보 풀에서 사전 배제 + `SCREENING_RISK_EXCLUDED` 메트릭 기록.
  - src/engine.py: `_CRITICAL_DISCLOSURE_KEYWORDS`/`_match_critical_disclosure`를 disclosure_risk로 이관. `_match_critical_disclosure`는 위임 래퍼로 유지(기존 테스트 보존).
  - src/scheduler/healthcheck.py: `func.case`→`case`(PostgreSQL에 없는 `case()` 함수 호출로 매 실행 예외→기본값 전송하던 크래시 수정) + 매수 거절 사유 조회를 `event_logs`→`system_metrics`(BUY_REJECT/BUY_DISCLOSURE_BLOCK/BUY_UNTRADABLE)로 교정. `_extract_reject_reason`→`_reject_label`.
  - tests: test_disclosure_risk.py 신규 7종, test_screener.py 위험배제 4종, test_healthcheck.py 실제 SQL 실행 회귀 가드 1종.
- 배경: 5/26 이후 매매 0건 조사. 시스템은 정상(750사이클/0에러)이었고, 앙상블이 상장폐지 정리매매 종목(230980 비유테크놀러지)에 conf 1.000 BUY를 고착 생성 → v0.6.0 공시 게이트가 679건 전량 정당 차단. 정리매매 급등락이 기술지표를 강한 BUY로 속인 것(앙상블 버그 아님). 헬스체크 0건 경고는 `func.case` 예외로 매 실행 기본값(0) 전송, 거절사유는 system_metrics에만 기록되는데 event_logs를 조회해 항상 공란이었음.
- 영향: 위험종목이 후보 풀·신호 평가에 진입조차 못 해 단일종목 고착 차단(게이트 호출 644→0, SIGNAL_SKIP noise 감소). 헬스체크 0건 경고가 신호 BUY/SELL 수·상위 거절사유(DISCLOSURE/MARKET_CLOSE_GUARD 등)를 정확히 표기 → 운영자 즉시 진단 가능. DB 마이그레이션·신규 env 없음(기존 NEWS_RISK_GATE_ENABLED/LOOKBACK 재사용).
- 검증 결과: pytest **972 passed**(신규 12 포함) | mypy ✅(변경 4파일) | ruff ✅(변경 7파일).
- 비고: 운영자 액션 — 스크리닝/헬스체크 로직 반영을 위해 `com.kis.autotrader` 재시작 필요.

---

## [2026-05-28] 일일 헬스체크 (12:30·15:35) — 매매 0건 감지 시 즉시 Telegram 경고 (v0.6.0)
- 카테고리: feature
- 변경 파일:
  - src/scheduler/healthcheck.py: 신규 — `HealthcheckSlot(MORNING/CLOSING)`, `HealthcheckResult`(frozen dataclass), `build_healthcheck_message`(0건 분기 `⚠️` + 상위 매수 거절 사유 동봉), `_query_today_counts`(오늘자 signals BUY/SELL + orders BUY/SELL + event_logs 거절사유 집계), `collect_healthcheck`(KIS 잔고 holdings/deposit + engine cycle/api_calls), `run_healthcheck`(휴장일·엔진없음·DB실패 모두 swallow).
  - src/scheduler/jobs.py: `healthcheck_morning_job`(12:30 KST)·`healthcheck_closing_job`(15:35 KST) 메서드 + `_register_jobs`에 평일 cron 등록.
  - tests/test_scheduler/test_healthcheck.py: 신규 11종 — 0건 경고/정상 분기/슬롯 라벨(오전·마감)/거절사유 표기/휴장일 스킵/엔진없음 스킵/Telegram 전송/에러 swallow/_query_today_counts 시그니처/KST today 위임.
  - README.md: 스케줄러 표에 헬스체크 2행 추가.
- 배경: 2026-05-28 사용자가 "오늘 매매기록이 아예 없네"로 인지. 진단 결과 시스템은 정상이었으나(KIS 모의계좌 보유 0개 + 강한 BUY 후보 1종목=230980 비유테크놀러지가 정리매매로 v0.6.0 공시 게이트 차단, SELL 후보 1종목=001740 SK네트웍스가 미보유로 `sell_without_position` skip) 가시성이 부족해 운영자가 즉시 알기 어려운 상태였음.
- 영향: 장중 12:30·마감 직후 15:35에 사이클/시그널/주문/잔고를 Telegram으로 보고. 매매 0건이면 `⚠️` 마커 + 상위 매수 거절 사유(DISCLOSURE_FATAL/POSITION_RATIO/DAILY_TRADE_LIMIT_PER_STOCK 등) 동봉. 운영 영향 0(전송 실패 swallow). 함께 stale `portfolios` 12종목(5/25 이후 sync 안 됨) 단발 DELETE — 엔진은 KIS 잔고 API를 신뢰하므로 영향 없음.
- 검증 결과: pytest tests/test_scheduler/ ✅ **18 passed**(신규 11 포함) | tests/test_notify+scheduler+db ✅ **194 passed** | mypy ✅(src/scheduler/healthcheck.py + jobs.py) | ruff ✅(신규 파일).
- 비고: 운영자 액션 — 신규 cron 등록을 위해 `com.kis.autotrader` 재시작 필요.

---

## [2026-05-27] 공시 기반 매수 리스크 게이트 — 종목마스터 sync 사각지대 보완 (v0.6.0)
- 카테고리: enhancement
- 변경 파일:
  - src/config.py: `TradingConfig.news_risk_gate_enabled`(기본 on, env `NEWS_RISK_GATE_ENABLED`), `news_risk_lookback_days`(기본 30, env `NEWS_RISK_LOOKBACK_DAYS`) 추가.
  - src/db/repository.py: `NewsChunkRepository.get_recent_disclosure_titles(ticker, since)` — 최근 DISCLOSURE 공시 제목 조회.
  - src/engine.py: `_CRITICAL_DISCLOSURE_KEYWORDS`(상장폐지/정리매매/관리종목/회생절차/감사의견거절/횡령/배임/부도/영업정지) 신설. `_match_critical_disclosure`(순수 키워드 매처) + `_check_disclosure_risk_block`(설정 gate + DB 조회, 실패 swallow). `_execute_buy`에서 market_action 차단 직후 호출 — 매칭 시 `BUY_DISCLOSURE_BLOCK` 메트릭 기록 후 매수 차단.
  - tests/test_engine_disclosure_risk_gate.py: 키워드 매처(해제=호재 오탐 회피 포함)/게이트 on·off/DB 실패 swallow/_execute_buy 차단·통과 10종 신규.
- 배경: 2026-05-27 230980(비유테크놀러지) 매매불가 사고에서, KIS 종목마스터 sync(`market_actions`)는 230980을 정상(모든 플래그 false)으로 표시했으나 DART 공시는 5/21자 "상장폐지에 따른 정리매매 개시"(sentiment -0.85)를 이미 포착. 종목마스터 sync에 사각지대가 존재함이 확인됨.
- 영향: 최근 30일 내 치명 공시가 있는 종목의 매수를 사전 차단(모델 미사용, 순수 룰베이스). `_check_market_action_block`(종목마스터 기반)을 DART 공시로 보완 — 라이브 DB 검증서 230980·464680(상폐) 차단, 005930(삼성전자, 공시 5건) 통과. '거래정지해제'(거래 재개=호재) 오탐 방지로 바레 '거래정지'는 키워드 제외. 매도(청산)는 영향 없음.
- 검증 결과: pytest **949 passed**(신규 10 포함) | mypy ✅(변경 3파일) | ruff ✅.
- 비고: 운영자 액션 — 매수 게이트 로직 변경 반영을 위해 `com.kis.autotrader` 재시작 필요.

---

