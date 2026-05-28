# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (96건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

## [2026-05-27] 매매불가 종목 당일 블랙리스트 — rt_cd=1 매매불가 반복 거부 차단 (v0.5.2)
- 카테고리: bug_fix
- 변경 파일:
  - src/utils/exceptions.py: `OrderError`가 KIS 응답의 `rt_cd`/`msg1`을 보존하도록 `__init__` 추가 — 호출부가 거부 사유(매매불가 등)를 식별 가능.
  - src/api/order.py: `_parse_order_response`가 거부 시 `rt_cd`/`msg1`을 `OrderError`에 실어 전파.
  - src/engine.py: `_untradable_today` 당일 블랙리스트 신설. `_execute_buy`가 ①블랙리스트 종목은 주문 시도 자체를 스킵, ②`매매불가` 거부(`_is_untradable_order_error`) 수신 시 블랙리스트 등록 + `BUY_UNTRADABLE` 메트릭 기록. `pre_market`에서 일자 단위 리셋.
  - tests/test_engine_untradable_blacklist.py: 매매불가 거부→블랙리스트 / 블랙리스트 종목 주문 스킵 / 일반 거부는 비차단 / pre_market 리셋 / OrderError 필드 보존 5종 신규.
- 배경: 2026-05-27 장중, 스크리너가 모의투자 매매불가 종목(230980 비유테크놀러지)을 후보로 올려 신뢰도 0.99 BUY 신호가 매 사이클 발생. 매수 주문이 `rt_cd=1 모의투자 주문처리가 안되었습니다(매매불가 종목)`로 거부되는데도 09:07부터 191회 무한 재시도(+ 주문 엔드포인트 500 782회). 재시도가 10초 매매 사이클을 넘겨 `max_instances=1` 작업 스킵 폭주 → 105분간 사이클 219회로 throughput 급감.
- 영향: 매매불가 거부를 1회 받으면 같은 거래일 동안 해당 종목 매수 재시도를 차단. 무한 주문/500 폭주·사이클 블로킹 해소, API 호출 낭비 제거. 매도(보유분 청산)는 차단 대상 아님. 인메모리 셋(`_today_buys_per_stock`와 동일 패턴) — 일중 재시작 시 리셋되는 한계는 기존 일일 카운터와 동일.
- 검증 결과: pytest **939 passed**(신규 5 포함) | mypy ✅(변경 3파일) | ruff ✅(변경 파일).
- 비고: 운영자 액션 — 주문 실행 로직 변경 반영을 위해 `com.kis.autotrader` 재시작 필요.

---

## [2026-05-23] 사이클 카운터 관측성 수정 — progress.transition이 상태 리스트 유지 (v0.5.1)
- 카테고리: bug_fix
- 변경 파일:
  - src/harness/progress.py: `CycleProgress.transition`이 history append뿐 아니라 상태 리스트(pending/in_flight/completed/failed/skipped)도 from→to로 이동. `_STATE_LIST_FIELD` 매핑(implemented→completed, ready→pending) 신설.
  - .claude/agents/proposal-validator.md: 안전 게이트 거절 시 `pipeline_mark_skipped`에 더해 `pipeline_append_progress`(ready→skipped)도 호출(implementer 패턴과 일치).
- 배경: `transition()`이 history에만 append하고 상태 리스트는 비워둬 orchestrator의 `len(completed/failed/skipped)`가 항상 0. 신format 사이클 9건 전부 `completed=0 failed=0 skipped=0`으로 보고(75건 implemented된 날 포함). 추가로 validator는 progress 기록을 아예 안 해 skip이 history에도 안 남았다(2026-05-23 W21 제안서 2건 SKIP이 결산엔 0으로 표시된 사례).
- 영향: 사이클 결산(`[cycle] ... completed/failed/skipped`)과 텔레그램 상태가 실제 처리 결과를 정확히 카운트. 안전 게이트 SKIP도 결산·history에 반영돼 "왜 0건인가" 진단이 즉시 가능.
- 검증 결과: pytest **934 passed**(신규 7: transition 리스트 유지) | mypy ✅ | ruff(변경 파일) ✅.
- 비고: 하네스 내부 변경(progress.py + 에이전트 프롬프트) — 서비스 재시작 불요, 다음 자동구현 cron(평일 17:15)부터 적용.

---

## [2026-05-23] 종목별 당일 진입 횟수 제한 — 동일 종목 다중 진입 차단 (v0.5.0)
- 제안서: docs/proposals/2026-05-23_daily-trade-limit-per-stock.md
- 카테고리: enhancement
- 변경 파일:
  - src/config.py: `TradingConfig.max_daily_trades_per_stock` 추가(기본 2, env `MAX_DAILY_TRADES_PER_STOCK`).
  - src/engine.py: `_process_stock` 매수 경로에 종목별 당일 진입 게이트 신설(전체 일일한도 체크 직후, check_buy_gates 직전). 한도 도달 시 `BUY_REJECT(reason=DAILY_TRADE_LIMIT_PER_STOCK)` 기록 후 매수 차단. 체결 확정 시 `_today_buys_per_stock[code]` 누적, `pre_market`에서 일자 단위 리셋.
  - .env.example / README.md / CLAUDE.md: `MAX_DAILY_TRADES_PER_STOCK` 문서화.
  - tests/test_engine_daily_trade_limit_per_stock.py: 한도 도달 차단 / 미만 허용 / 종목별 독립 / pre_market 리셋 4종 신규.
- 배경: 2주 연속 동일 종목 3회전 진입 패턴(W21 §7) — 동일 종목 반복 진입이 손실을 누적. 매수 게이트는 종목별 진입 횟수를 보지 않았다.
- 영향: 동일 종목 당일 매수 2회로 제한(3회차부터 차단). 매도(보유분 청산)는 항상 허용. 인메모리 카운터(`_today_trade_count`와 동일 패턴) — 일중 재시작 시 리셋되는 한계는 기존 일일 카운터와 동일.
- 검증 결과: pytest **927 passed**(신규 4 포함) | mypy ✅ | ruff(변경 파일) ✅ | golden 11 ✅.
- 비고: 주간분석 제안서가 안전 게이트(리스크 게이트 코드 변경)에 막혀 SKIPPED 처리된 것을 수동 검토 후 구현. 운영자 액션 — 전략 로직 변경 반영을 위해 `com.kis.autotrader` 재시작 필요.

---

