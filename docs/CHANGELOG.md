# 변경 이력

> Claude Code가 제안서를 구현할 때마다 이 파일에 기록합니다.
> 제안서 경로: docs/proposals/

---

## [2026-04-14] Telegram 알림 메시지 구조 개선 (매수/매도/결산)
- 카테고리: enhancement
- 배경:
  - 초기 개발 버전의 Telegram 알림이 최소한의 정보만 표시 (종목명, 수량, 가격)
  - 매수 시 전략/시그널 정보, 매도 시 손익/수익률, 결산 시 체결 내역/계좌 현황이 누락
- 변경 파일:
  - src/notify/formatter.py: 전면 개편
    - format_buy(): 총 금액, 전략명, 시그널 근거/신뢰도 표시, BuyDetail 데이터 클래스 추가
    - format_sell(): 매입가, 실현 손익/수익률 표시, SellDetail 데이터 클래스 추가, 익절/손절/전략매도 이모지 분리
    - format_daily_summary(): 매수/매도 건수, 체결 내역(최대 10건), 계좌 현황(예수금/평가금/평가손익/보유종목) 표시
    - format_system(): 시스템 이모지 추가
  - src/notify/telegram.py: 인터페이스 확장
    - notify_buy(): strategy, reason, confidence 키워드 인자 추가
    - notify_sell(): avg_price 키워드 인자 추가 → 자동 손익 계산
    - notify_daily_summary(): buy_count, sell_count, executions, balance 키워드 인자 추가
  - src/engine.py: 알림에 풍부한 데이터 전달
    - _execute_buy(): strategy_name 파라미터 추가, 시그널 정보(reason, confidence) 함께 전달
    - _execute_sell(): avg_price 전달
    - post_market(): executions, balance, buy_count, sell_count 전달
  - tests/test_notify/test_formatter.py: 테스트 8→17건 확대 (BuyDetail, SellDetail, executions, balance 케이스)
  - tests/test_notify/test_telegram.py: 테스트 11→15건 확대 (전략 정보, 매입가/손익, 상세 결산 케이스)
- 검증 결과: pytest ✅ (39 passed in test_notify/) | mypy ✅ (새 에러 없음) | ruff ✅

## [2026-04-14] 서킷 브레이커 점진적 백오프 + 엔진 연동 강화
- 카테고리: bug_fix
- 배경:
  - KIS API 500 에러 연속 발생 시 서킷 브레이커 리셋이 30초로 고정되어 무한 재시도 루프 발생
  - 매매 사이클이 종료되지 않아 후속 스케줄러 작업(post_market, summarize 등) 전부 스킵
  - 오늘(4/14) 11:20~11:23 구간에서 11,310건의 500 에러 발생
- 변경 파일:
  - src/api/client.py: CircuitBreaker에 exponential backoff 적용
    - 반복 트립 시 리셋 대기 시간 점진 증가 (30s → 60s → 120s → 240s → 300s 최대)
    - 성공 시 트립 카운트/백오프 전부 초기화
    - trip_count 추적으로 반복 장애 감지
  - src/engine.py: 서킷 브레이커 상태 확인 추가
    - run_trading_cycle() 시작 시 서킷 브레이커 열림 확인 → 즉시 스킵
    - 종목 처리 루프 중 서킷 브레이커 열림 확인 → 나머지 종목 스킵, 사이클 조기 종료
- 영향: API 장애 시 불필요한 재시도 대폭 감소, 스케줄러 정상 동작 보장

## [2026-04-13] watchdog 주말/공휴일 체크 추가 + stdout 로그 비대화 방지
- 카테고리: bug_fix
- 배경:
  - 4/11(토) watchdog가 주말을 감지하지 못해 장중 미작동으로 오판 → 13회 무한 재시작 루프 발생
  - `autotrader.out.log`가 101MB로 비대화 (Telegram 폴링 로그가 매 30초 stdout에 출력)
- 변경 파일:
  - scripts/watchdog.sh: 주말(토/일) 및 공휴일(holidays.json) 체크 추가, 해당 시 즉시 종료
  - src/utils/logger.py: 콘솔 핸들러 레벨 INFO → WARNING 변경 (파일 핸들러는 INFO 유지)
- 영향: 주말/공휴일 불필요한 재시작 방지, out.log 크기 대폭 축소

## [2026-04-10] 기본 전략을 앙상블로 변경하여 다중 전략 활성화
- 제안서: docs/proposals/2026-04-10_default-strategy-to-ensemble.md
- 카테고리: bug_fix
- 변경 파일:
  - src/strategy/selector.py: 기본 전략 `"moving_average"` → `"ensemble"` 변경, fallback도 동일 적용
  - src/config.py: `StrategyConfig.default` 기본값 `"moving_average"` → `"ensemble"` 변경
  - src/engine.py: signal_type 매핑에 MACD_SIGNAL, BOLLINGER_SIGNAL, ENSEMBLE 추가 + RSI 과매도/과매수 키워드 보완
- 검증 결과: pytest ✅ (349 passed, 기존 실패 4건 `test_risk.py`는 본 건 무관) | mypy ✅ (새 에러 없음) | ruff ✅ (새 에러 없음)

## [2026-04-09] 캘린더 일일 결산 수익률·체결건수 오류 수정
- 카테고리: bug_fix
- 배경:
  - 장 마감 후 Google Calendar 이벤트의 수익률이 항상 `+0.0%`, 체결 건수가 항상 `0건`으로 등록되는 버그
  - 실제 DB에는 매매 3건(매수 2 / 매도 1, 손절 -45,000원) 존재했으나 캘린더에는 반영 안 됨
- 근본 원인:
  1. `src/api/account.py`: KIS `/inquire-balance` 응답에 존재하지 않는 필드 `TOT_EVLU_PFLS_RT`를 조회 → 기본값 `"0"` 반환 → 수익률 항상 0.0%
  2. `src/engine.py`: 체결 내역을 KIS `/inquire-daily-ccld` API로 조회했으나 모의투자 환경에서 `output1: []` 반환 → 체결 건수 항상 0
- 변경 파일:
  - src/api/account.py: `TOT_EVLU_PFLS_RT` → `ASST_ICDC_ERNG_RT` (자산증감수익률) 로 교체
  - src/engine.py:
    - `_create_calendar_event()`가 KIS API 대신 DB Trade 테이블에서 당일 체결을 집계하도록 변경
    - `_load_today_trades()` 헬퍼 추가 (DB 조회 + 실패 시 빈 리스트 폴백)
    - `_group_trades_for_calendar()` 헬퍼 추가 (종목별 매수/매도 합산, 손익 합산, 수익률 금액-가중평균)
    - `from typing import Any` import 추가
- 검증 결과:
  - ruff ✅ | mypy ✅ (새 에러 0, baseline 50 → 48)
  - pytest ✅ (329 passed, 기존 실패 4건 `test_risk.py`는 본 건 무관)
  - 라이브 KIS API 검증: `ASST_ICDC_ERNG_RT = -0.68%` 정상 반환 (이전: 0.0)
  - 오늘 데이터 시뮬레이션: 체결 3건, 종목 2그룹, 손익 -30,000원, 수익률 -0.68% 정상 집계
- 후속 조치:
  - 잘못 등록된 캘린더 이벤트 `p9j8c5uo946e31un11228do6bc` 삭제
  - 수정된 로직으로 재등록: `vi0mqsjkal3lbjqqis3g81kgks`
- 프로세스 재시작: `launchctl stop/start com.kis.autotrader` 완료 (PID 61510 → 87736)

## [2026-04-09] 저신뢰도 시그널 DB 저장 스킵 (로깅 볼륨 축소)
- 제안서: docs/proposals/2026-04-09_signal-low-confidence-skip-logging.md
- 카테고리: performance
- 변경 파일:
  - src/engine.py: `_record_signal_to_db()`에 저신뢰도+비매매전환 시그널 필터 추가 (confidence < min_confidence && !action_taken → DB 저장 스킵)
- 검증 결과: pytest ✅ (329 passed, 4 기존 실패) | mypy ✅ (새 에러 없음) | ruff ✅

## [2026-04-09] Phase 3 — 전략 추가 + 성과 피드백 + 대시보드 리스크 + 매매 제어
- 카테고리: enhancement
- 신규 파일:
  - src/strategy/macd.py: MACD 전략 (EMA 교차 기반 골든/데드크로스)
  - src/strategy/bollinger.py: 볼린저밴드 전략 (%B 지표 기반 과매수/과매도)
  - dashboard/pages/risk.py: 리스크 분석 페이지 (MDD, Sharpe/Sortino, Profit Factor, 연패)
  - tests/test_strategy/test_macd.py, test_bollinger.py: 전략 테스트 10건
- 변경 파일:
  - src/strategy/ensemble.py: "performance" 투표 모드 추가 (과거 승률 기반 가중치)
  - src/strategy/registry.py: macd, bollinger 전략 자동 등록
  - src/db/analytics.py: get_strategy_win_rates() 추가 (전략별 승률 조회)
  - dashboard/app.py: 30초 자동 갱신 옵션 추가
  - main.py: Telegram /stop, /resume, /setlimit 매매 제어 명령 3개 추가
- 검증 결과: pytest ✅ (333 passed)

## [2026-04-09] Phase 2 — 분석 지표 고도화 + 포트폴리오 리스크 + 시간대 조정
- 카테고리: enhancement
- 변경 파일:
  - src/db/analytics.py: MDD, Sharpe/Sortino Ratio, Profit Factor, 연속 손실/수익 추적 함수 추가
  - src/strategy/risk.py: record_trade_result() + 당일 MDD/연패 감시 → 자동 매매 중단, 장 마감 임박(14:30 이후) 신규 매수 차단 + 익절 비율 50% 하향
  - src/engine.py: 매도 결과 리스크 추적 연동, 포트폴리오 halt 체크, 장 시작 시 리스크 초기화
  - src/config.py: TradingConfig에 MAX_DAILY_DRAWDOWN, MAX_CONSECUTIVE_LOSSES, MARKET_CLOSE_CUTOFF 추가
- 검증 결과: pytest ✅ (323 passed)

## [2026-04-09] Phase 1 — 전략 파라미터 외부화 + watchdog 수정 + 로그 로테이션
- 카테고리: enhancement, bug_fix
- 변경 파일:
  - src/config.py: StrategyConfig에 MA/RSI/앙상블/익절/신뢰도 파라미터 11개 추가
  - src/strategy/moving_average.py, rsi.py, risk.py: 하드코딩 → settings 주입
  - scripts/watchdog.sh: date +%H → +%-H (08/09시 8진수 파싱 버그 수정)
  - src/utils/logger.py: WARNING 이상 크기 기반 로테이션 추가 (50MB × 5)
- 검증 결과: pytest ✅ (323 passed)

## [2026-04-09] 스크리닝 고도화 — 사전필터 + 복수소스 스코어링 파이프라인
- 카테고리: enhancement
- 신규 파일:
  - src/strategy/screener.py: ScreeningFilter(사전 필터) + ScreeningScorer(가중 스코어링) + StockScreener(통합 클래스)
  - tests/test_strategy/test_screener.py: 필터/스코어링/통합 테스트 18건
- 변경 파일:
  - src/config.py: ScreeningConfig 추가 (15개 설정값 .env 외부화)
  - src/engine.py: _screen_stocks를 4단계 파이프라인으로 교체 (필터→분석→스코어링→정렬)
- 스코어링: 거래량순위(0.2) + 등락률(0.3) + 전략신뢰도(0.5) 가중합산
- 검증 결과: pytest ✅ (323 passed) | mypy ✅ | ruff ✅
- 프로세스 재시작: 완료

## [2026-04-09] 대시보드 에러 수정 + 매수사유 추적 + 안정화
- 카테고리: bug_fix, enhancement
- 신규 파일:
  - alembic/versions/499487c40196_add_buy_reason_to_trades.py: DB 마이그레이션
- 변경 파일:
  - src/db/models.py: BuyReason enum 추가, Trade 모델에 buy_reason 컬럼
  - src/db/repository.py: record_trade()에 buy_reason 파라미터 추가
  - src/engine.py: 매수 시 시그널→BuyReason 자동 매핑, signal 정보 기록
  - dashboard/pages/trades.py: sell_reason enum 에러 수정, 매수 사유 분석 섹션 추가
  - dashboard/app.py: 당일 체결 매수 탭에 매수사유 표시
  - src/notify/bot.py: 시작 시 기존 업데이트 flush (재시작 루프 방지)
  - src/calendar/google_auth.py: 토큰 갱신 실패 시 재인증 플로우 자동 fallback
- 검증 결과: pytest ✅ (305 passed) | mypy ✅ | ruff ✅
- 프로세스 재시작: 완료

## [2026-04-08] 스크리닝 등락률(price_change_pct) 필드명 불일치 수정
- 제안서: docs/proposals/2026-04-08_screening-price-change-field-mismatch.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `getattr(item, "price_change_pct", 0.0)` → `item.change_rate` 직접 접근으로 수정 (VolumeRankItem 필드명 불일치 해소)
- 검증 결과: pytest ✅ (305 passed) | mypy ✅ (기존 에러만, 새 에러 없음) | ruff ✅ (기존 에러만, 새 에러 없음)
- 프로세스 재시작: 예정

## [2026-04-07] 사이클 조기종료 시 CYCLE_END 메트릭 누락 수정
- 제안서: docs/proposals/2026-04-07_cycle-end-metric-missing.md
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: run_trading_cycle()에 try/finally 패턴 적용, 조기종료 시에도 CYCLE_END 기록, exit_reason 필드 추가
- 검증 결과: pytest ✅ (305 passed) | mypy ✅ (기존 에러만, 새 에러 없음) | ruff ✅
- 프로세스 재시작: 예정

## [2026-04-06] DAILY_TRADE_LIMIT 50~500으로 수정
- 카테고리: config
- 변경 파일: .env
- 내용: 일일 매매 한도를 10 → 200으로 상향 (모의투자 데이터 축적 목적)

## [2026-04-06 18:04] 이동평균 전략 NaN 방어 로직 추가
- 제안서: docs/proposals/2026-04-06_moving-average-nan-guard.md
- 카테고리: bug_fix
- 변경 파일:
  - src/strategy/moving_average.py: MA 값 NaN 체크 가드 추가 (math.isnan), NaN 시 HOLD 반환
  - tests/test_strategy/test_moving_average.py: NaN 데이터 케이스 테스트 추가
- 검증 결과: pytest ✅ (256 passed) | mypy ✅ (기존 에러만, 새 에러 없음) | ruff ✅ (기존 에러만, 새 에러 없음)
- 프로세스 재시작: 예정

## [2026-04-05] 사이클 완료 로그에 API 호출/모니터링 상세 통합
- 카테고리: refactor
- 변경 파일: src/engine.py
- 내용: 사이클 완료 시 API 호출수, 모니터링 종목수(보유/발굴), exit_reason 등 상세 로그 통합

## [2026-04-05] 사이클 메트릭 상세 추가 + /status 명령 개선
- 카테고리: enhancement
- 변경 파일: src/engine.py, src/notify/bot.py
- 내용: CYCLE_END 메트릭에 API 호출/모니터링 상세 추가, /status 텔레그램 명령에서 표시

## [2026-04-05] /status, /today 명령을 DB 데이터 기반으로 개선
- 카테고리: enhancement
- 변경 파일: src/notify/bot.py
- 내용: 헬스체크 API 대신 DB 직접 조회로 정확도 향상, daily_summary 테이블 활용

## [2026-04-04] numpy float → Python float 변환 수정
- 카테고리: bug_fix
- 변경 파일: src/engine.py, src/db/repository.py
- 내용: numpy float64를 PostgreSQL JSONB/파라미터에 전달 시 직렬화 실패 수정

## [2026-04-04] Telegram 봇 명령 5개 추가
- 카테고리: enhancement
- 변경 파일: src/notify/bot.py, main.py
- 명령: /trades (체결 내역), /pnl (손익), /signals (시그널), /risk (리스크), /screen (스크리닝)

## [2026-04-04] 대시보드 고도화 — trades/signals/daily_summary 기반 분석 페이지
- 카테고리: enhancement
- 신규 파일: dashboard/pages/trades.py, dashboard/pages/signals.py
- 변경 파일: dashboard/app.py, dashboard/pages/performance.py
- 내용: 매매 분석, 시그널 분석 페이지 추가, daily_summary 기반 성과 분석 고도화

## [2026-04-04] 매매 데이터 PostgreSQL 적재 인프라 + 분석 쿼리 + 엔진 연동
- 카테고리: enhancement
- 신규 파일: src/db/analytics.py, alembic migrations (trades, signals, screening_results, daily_summary, system_metrics)
- 변경 파일: src/db/models.py, src/db/repository.py, src/engine.py
- 내용: Trade/Signal/ScreeningResult/DailySummary/SystemMetric 모델 + 엔진에서 자동 기록

## [2026-04-04] 워치독 헬스체크 기반 감시 개선
- 카테고리: enhancement
- 변경 파일: scripts/watchdog.sh
- 내용: 로그 파일 기반 → 헬스체크 API + cycle_count 기반 hang 감지로 개선

## [2026-04-03] 모의/실전 DB 분리
- 카테고리: enhancement
- 변경 파일: src/config.py, .env
- 내용: KIS_ENV에 따라 DATABASE_URL / DATABASE_URL_REAL 자동 선택

## [2026-04-03] 대시보드 SQL/타입 수정
- 카테고리: bug_fix
- 변경 파일: dashboard/app.py, dashboard/pages/performance.py
- 내용: text()로 SQL 감싸기, isocalendar float→int 변환, connection 사용

## [2026-04-03] T3-4 로그 구조화 저장
- 신규: src/db/event_logger.py, alembic migration (event_logs 테이블)
- 변경: src/db/models.py (EventLog, EventLevel), src/db/repository.py, src/engine.py, main.py, dashboard/app.py
- 기능: 매매/시스템/에러/경고 이벤트를 DB에 구조화 저장, 대시보드에서 조회
- 테스트: 195 passed

## [2026-04-03] T3-1 공휴일 자동 감지
- 신규 파일: src/scheduler/holidays.py, holidays.json, tests/test_scheduler/test_holidays.py
- 변경 파일: src/scheduler/jobs.py
- 기능: holidays.json 기반 휴장일 판단, pre_market/trading/post_market 모두 적용
- 2026년 한국 증시 휴장일 15일 등록 (설날, 추석, 공휴일 등)
- 테스트: 195 passed (신규 7건)

## [2026-04-03] T2-2 성과 시각화
- 신규 파일: dashboard/pages/performance.py
- 기능: 일별 수익률 추이, 주간별 집계 차트, 종목별 매매 통계, 기간 통계 요약
- Streamlit 멀티페이지로 대시보드에 자동 통합

## [2026-04-03] T2-1 웹 대시보드 (Streamlit)
- 신규 파일: dashboard/app.py, scripts/run_dashboard.sh
- 기능: 시스템 상태, 보유 포트폴리오, 일일 성과 차트, 최근 주문 내역
- 헬스체크 API + PostgreSQL 직접 조회
- 실행: .venv/bin/streamlit run dashboard/app.py (포트 8501)
- 테스트: 188 passed (기존 테스트 영향 없음)

## [2026-04-03] T2-4 Telegram 원격 명령
- 신규 파일: src/notify/bot.py, tests/test_notify/test_bot.py
- 변경 파일: main.py
- 명령: /status (시스템 상태), /balance (잔고), /today (당일 현황), /help
- getUpdates 롱 폴링, chat_id 검증, 명령 핸들러 패턴
- 테스트: 188 passed (신규 5건)

## [2026-04-03] T2-3 알림 레벨 분류
- 변경 파일: src/notify/telegram.py, tests/test_notify/test_telegram.py
- 긴급(손절, 에러) → 소리/진동 알림, 일반(체결, 결산) → 무음 전송
- Telegram disable_notification 파라미터 활용
- 테스트: 183 passed (신규 2건)

## [2026-04-03] T1-4 프로세스 행 감지 + 자동 재시작
- 로드맵: docs/plans/feature-roadmap.md (T1-4)
- 신규 파일: scripts/watchdog.sh
- 기능: 로그 미갱신 5분 초과 시 hang 판단, launchctl 재시작, Telegram 알림
- 장중 시간(09:00~15:25)에만 동작, 평일 5분마다 crontab 실행

## [2026-04-03] T1-3 DB 자동 백업 구현
- 로드맵: docs/plans/feature-roadmap.md (T1-3)
- 신규 파일: scripts/backup_db.sh
- 기능: Docker exec pg_dump → gzip 압축, 7일 롤링 보관, crontab 매일 04:00 실행
- crontab 등록 완료

## [2026-04-03] T1-2 헬스체크 API 구현
- 로드맵: docs/plans/feature-roadmap.md (T1-2)
- 신규 파일: src/api/health.py
- 변경 파일: src/config.py, main.py
- 기능: asyncio 기반 경량 HTTP 서버, GET /health 엔드포인트 (DB, 스케줄러, API 호출량 상태)
- 외부 패키지 추가 없음 (표준 라이브러리만 사용)
- 테스트: 181 passed (신규 4건)

## [2026-04-03] T1-1 Telegram 알림 기능 구현
- 로드맵: docs/plans/feature-roadmap.md (T1-1)
- 신규 파일: src/notify/__init__.py, src/notify/telegram.py, src/notify/formatter.py
- 변경 파일: src/config.py, src/engine.py, main.py
- 기능: 매수/매도 체결, 손절, 일일 결산, 에러, 시스템 시작/종료 Telegram 알림
- 테스트: 177 passed (신규 20건)

## [2026-04-03] KIS API 호출 제한 정책 최신화 (2026년 기준)
- 변경 파일: .env, src/config.py, src/api/rate_limiter.py, src/api/websocket.py
- 수정 내용:
  - 초당 호출 제한을 KIS 최신 정책에 맞게 수정 (모의=5건/초, 실전=20건/초)
  - MIN_CALL_INTERVAL을 하드코딩에서 초당 호출 수 기반 동적 계산으로 변경
  - 웹소켓 구독 종목 수 상한 41개 추가 (KIS 세션당 제한)
  - 일일 호출 한도 10,000 → 50,000으로 상향 (KIS 공식 일일 한도 없음, 안전장치)
- 테스트: 157 passed

## [2026-04-03] API 일일 한도 초과 대응 수정
- 변경 파일: src/engine.py, src/strategy/moving_average.py
- 원인: 스크리닝 발굴 종목이 무제한 증가하여 API 호출량 폭증 + 한도 초과 후에도 스케줄러가 계속 실행
- 수정 내용:
  - `_daily_limit_reached` 플래그 도입: 한도 초과 시 이후 사이클 즉시 중단 (다음 장 시작 시 초기화)
  - 스크리닝 발굴 종목 상한(`MAX_SCREENED_STOCKS=15`) 추가하여 API 호출량 제어
  - 이동평균 전략 괴리율 계산 시 0 나누기 방어 코드 추가
- 테스트: 157 passed

## [2026-04-03] 스크리닝 간격 최적화
- 제안서: docs/proposals/2026-04-03_스크리닝_간격_최적화.md
- 테스트: PASS
- 자동 구현 완료

## [2026-04-03 03:21] 잔고 캐시 TTL 조정
- 제안서: docs/proposals/2026-04-03_잔고캐시_TTL_조정.md
- 변경 파일: src/engine.py
- 테스트: PASS
- 재시작: 예정
