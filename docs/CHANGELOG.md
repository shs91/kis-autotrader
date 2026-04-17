# 변경 이력

> Claude Code가 제안서를 구현할 때마다 이 파일에 기록합니다.
> 제안서 경로: docs/proposals/

---

## [2026-04-17 22:00] 앙상블 가중투표 SELL 편향 수정 — HOLD 과반 가드
- 제안서: docs/proposals/2026-04-17_ensemble-sell-bias-fix.md
- 카테고리: refactor
- 배경:
  - W16 앙상블 시그널 8,054건 중 BUY 0건, SELL 8,054건(100% SELL).
    횡보장에서 교차 전략(MA, MACD)이 HOLD를 출력하면 해당 투표가 "기권"으로
    처리되어 소수의 SELL 투표만으로 전체 결과가 SELL로 확정되는 구조적 문제.
  - HOLD 투표가 과반(전체 전략의 50% 초과)이면 앙상블도 HOLD를 반환하도록
    `_weighted_vote`에 가드 추가.
- 변경 파일:
  - src/strategy/ensemble.py: `_weighted_vote` 메서드에 HOLD 과반 가드 6줄 추가
  - tests/test_strategy/test_ensemble.py: HOLD 과반 테스트 3개 추가
- 검증 결과:
  - pytest ✅ (403 passed, 4 pre-existing failures in test_risk.py — 제 변경과 무관)
  - mypy: pre-existing 에러만 (신규 에러 없음)
  - ruff ✅ All checks passed
- 기대 효과: HOLD 과반 시 불필요한 SELL 시그널(주간 ~5,000~7,000건) 제거,
  signals 테이블 적재량 감소.

---

## [2026-04-17 21:00] RSI 과매도 임계값 상향 조정 — 약세장 BUY 시그널 활성화
- 제안서: docs/proposals/2026-04-17_rsi-oversold-threshold-tuning.md
- 카테고리: param_tuning
- 배경:
  - 최근 4일간(04-14~04-17) 전 전략에서 BUY 시그널 0건 발생. RSI 시그널도
    7일간 0건. 현재 RSI 과매도 임계값 30.0은 약세장에서 도달하기 어려운
    극단적 수준이라 시그널 발생이 차단되는 구조.
  - 스크리닝 전환율도 04-16부터 0%로 급락 (이전 12.7~19.4%).
- 변경 파일:
  - config_overrides.json (신규 생성): `STRATEGY_RSI_OVERSOLD` 30.0 → 35.0
- 검증 결과:
  - pytest ✅ (400 passed, 4 pre-existing failures in test_risk.py — 제 변경과 무관)
  - mypy: pre-existing 74 (신규 에러 없음)
  - ruff: pre-existing 16 (신규 에러 없음)
- 기대 효과: RSI 과매도 시그널 활성화로 앙상블 BUY 투표 발생, 매매 교착 해소.
  MAX_LOSS_RATE(3%) 및 기존 리스크 관리 체계가 역추세 매수 리스크를 제어.

---

## [2026-04-16 17:30] 스크리닝→시그널 파이프라인 가시화 — EVAL_TARGETS 메트릭 추가
- 제안서: docs/proposals/2026-04-16_screening-to-signal-pipeline-gap.md
- 카테고리: bug_fix (observability)
- 배경:
  - 오늘 스크리닝 145 distinct 종목 발굴했으나 시그널 평가 대상은 블루칩
    5종 + 두산에너빌리티 1종뿐 (전환율 0%). 어제는 67종 발굴 중 13종
    전환(19.4%)이었으나 오늘 0%로 급락. 스크리닝 결과가 엔진의
    평가 대상 리스트로 주입되는 경로가 단절되었거나 회복되지 않은 것으로
    추정되나, 현재 로그로는 "엔진이 이번 사이클에서 실제로 어떤
    종목 N개를 평가했는지"를 확인할 수 없었다.
- 변경 파일:
  - src/engine.py: `run_trading_cycle` 내 평가 대상 구성 직후
    `_record_eval_targets()` 호출. 이 메서드는 `metric_type=EVAL_TARGETS`
    레코드를 `system_metrics` 큐에 enqueue. detail에
    `{cycle, counts: {screening, watchlist, positions}, total_targets,
    targets(최대 50개), truncated}` 필드 기록. 재사용 중이던
    `_get_watchlist_codes()` 결과를 로컬 변수로 뽑아 카운트 로그와
    메트릭에서 공유.
  - src/worker/screener.py: ScreeningWorker와 메인 엔진 간
    `screening_results` 조회 규약(date=today + converted_to_trade=True 키)을
    모듈 docstring에 명문화. 코드 변경 없음.
  - src/strategy/selector.py: `get_strategy()`에 전략 배정 DEBUG trace
    추가 — 어떤 종목이 어떤 전략으로 배정되는지 로그로 추적.
  - tests/test_engine_db_integration.py: `TestRecordEvalTargets` 추가
    (3 테스트). 메트릭 payload shape, truncate, run_trading_cycle에서의
    실제 enqueue 발생 검증.
- 검증 결과:
  - pytest ✅ (400 passed, 4 pre-existing failures in test_risk.py 관련
    장 마감 임박 차단 로직 — 제 변경과 무관)
  - mypy: pre-existing 79 → 74 (신규 에러 없음)
  - ruff: pre-existing 16 → 16 (신규 에러 없음)
- 기대 효과: 내일(2026-04-17) 리포트에서 스크리닝 발굴 N종 → 엔진
  평가 반영 M종 비율이 보이므로, 단절된 구간이 "엔진 DB 조회"인지
  "selector 필터링"인지 구체적 수정 제안을 작성할 수 있다.

---

## [2026-04-16 17:30] 앙상블 서브전략 confidence=0 수렴 원인 진단 — 지표 관측 메타 추가
- 제안서: docs/proposals/2026-04-16_ensemble-all-hold-zero-confidence.md
- 카테고리: bug_fix (observability)
- 배경:
  - 어제 구현된 `vote_meta`(SIGNAL_SKIP 관측) 덕분에 오늘 처음으로
    앙상블 내부 투표가 데이터로 확인됨. 5종목 × 289 사이클 = 1,445건
    전부 4개 서브전략(MA·RSI·MACD·BB)이 `confidence=0` HOLD로 수렴.
  - 서로 다른 지표가 동시에 0 confidence를 낼 통계적 가능성이 낮아,
    데이터 길이 부족/NaN 방어 분기 진입이 의심됨. 다만 현재 meta에는
    각 지표의 `series_len/nan_ratio/last_value/guard_triggered`가 없어
    원인 단계를 특정할 수 없다. 어제 4,400건 정상 계산과 대비.
- 변경 파일 (5개 한도 정확히 충족):
  - src/strategy/moving_average.py: `analyze()` 내 Signal.meta에
    `series_len, nan_ratio, last_short, last_long, guard_triggered
    (+guard_reason)` 기록. 길이 부족·NaN 분기에서도 메타 채움.
  - src/strategy/rsi.py: `series_len, nan_ratio, last_rsi,
    guard_triggered (+guard_reason)` 기록. NaN RSI 방어 분기 추가.
  - src/strategy/macd.py: `series_len, nan_ratio, last_macd,
    last_signal, last_hist, guard_triggered (+guard_reason)` 기록.
    NaN 방어 분기 추가.
  - src/strategy/bollinger.py: `series_len, nan_ratio, last_price,
    last_upper, last_lower, last_percent_b, guard_triggered
    (+guard_reason)` 기록. NaN 밴드 방어 분기 추가.
  - src/strategy/ensemble.py: `_build_vote_meta()`에서 각 서브전략의
    `Signal.meta`를 vote 항목에 병합. 기존 shape `{strategy, action,
    confidence}` 유지하고 sub-meta 키만 append (기존 3개 키는 보호).
- 테스트 추가:
  - tests/test_strategy/test_ensemble.py: sub-meta 병합 테스트 1건.
  - tests/test_strategy/test_moving_average.py, test_rsi.py, test_macd.py,
    test_bollinger.py: 정상 케이스의 meta 키 존재 + 길이 부족 guard
    테스트 각 1~2건씩 (기존 로직 영향 없음).
- 검증 결과:
  - pytest ✅ (400 passed, 4 pre-existing failures in test_risk.py —
    장 마감 임박 차단 로직, 제 변경과 무관)
  - mypy: pre-existing 79 → 74 (신규 에러 없음)
  - ruff: pre-existing 16 → 16 (신규 에러 없음)
- 기대 효과: 내일부터 `SIGNAL_SKIP.detail.vote_meta.votes[i]`에 각 지표
  단계별 상태(길이/NaN/최종값)가 쌓여, confidence=0 수렴의 구체 원인을
  `guard_triggered=true`(길이/NaN 분기) vs 정상 계산 후 BUY/SELL 분기
  조건 미충족으로 구분 가능.

---

## [2026-04-16] Worker 큐 적체 이슈 해결 — batch_size/poll_interval 튜닝
- 카테고리: bug_fix (ops)
- 배경:
  - 2026-04-16 16:20 시점에 구글 캘린더 오늘 결산 이벤트가 미등록 상태.
    조사 결과 15:40에 post_market으로 enqueue된 5건 중 `daily_performance`
    (priority=5)만 즉시 처리되고 `sync_portfolio`·`daily_summary`·
    `calendar_event` (priority=1)와 `telegram_notify` (priority=3)는 PENDING
    상태로 장시간 대기.
  - 원인: Worker 처리 용량 < enqueue 속도.
    - 기본값 `WORKER_BATCH_SIZE=10`, `WORKER_POLL_INTERVAL=30` → 20건/분
    - 매매 사이클(10초)마다 `CYCLE_START`·`CYCLE_END`·N개의 `SIGNAL_SKIP`
      메트릭 enqueue → 분당 ~60건 이상 누적
    - 하루 매매 시간 끝에 record_metric(priority=3) 수백건이 큐에 남아
      priority=1 태스크를 막음 (`priority DESC, scheduled_at` 정렬).
  - 당일 조치: PENDING 4건(id 11270~11273) priority를 10으로 격상 →
    16:23:22~16:23:37 사이 모두 처리 완료. 캘린더 이벤트
    `[매매결과] 2026-04-16 +0.0% (0건 체결)` 정상 등록 확인.
- 변경 파일:
  - .env: `WORKER_BATCH_SIZE=50`, `WORKER_POLL_INTERVAL=15` 추가
    (처리 용량 200건/분 = enqueue 속도의 약 3배 이상 확보).
  - .env.example: 기본값 주석에 튜닝 가이드 추가.
- 검증: 오늘 남은 record_metric PENDING 359건은 장 마감 후라 enqueue가
  멈춘 상태이므로 현재 속도로 ~18분 내 자연 소진. 재시작 시 신규 설정
  적용되어 ~1.8분에 소진 가능.

---

## [2026-04-16] Google Calendar 일일 결산 상단 요약 오보 수정 — 평가손익 → 실현손익 통일
- 카테고리: bug_fix
- 배경:
  - 2026-04-15 구글 캘린더 `[매매결과] 2026-04-15 +0.6% (3건 체결)` 이벤트의
    상단 요약이 `총 손익: +0원`으로 표시되었지만 종목별 상세 합은
    `+60,600원`으로 불일치.
  - 원인: `_enqueue_calendar_event`의 payload가 `balance.total_profit_loss`
    (평가손익·미실현 포함)와 `balance.total_profit_rate`(평가수익률)를
    전달. 2026-04-15에는 보유 중인 삼성전자가 매수가=현재가라 평가손익이
    0원이 되었고, 종목별 상세(DB trades 기반)의 실현손익 +60,600원과
    달랐음.
  - 제목 `+0.6%`도 평가수익률(자산증감수익률). 실현수익률 `+5.03%`와 상이.
- 변경 파일:
  - src/engine.py:
    - `_enqueue_calendar_event()` 시그니처 변경(keyword-only):
      `balance` 파라미터 제거, `trades`·`realized_profit_loss`·
      `realized_rate` 추가. payload `total_profit_loss`/`profit_rate`에
      실현값을 전달하여 종목별 상세 합과 상단 요약/제목이 일치하도록 수정.
    - `post_market()`에서 Telegram과 동일한 실현손익/수익률 값을 Calendar
      enqueue에도 전달.
- 검증 결과: pytest ✅ (391 passed) | ruff ✅ | mypy: 기존 dead code
  (`_create_calendar_event`, `_save_daily_performance`, `_sync_portfolio`)의
  `object` 타입 힌트 관련 pre-existing 에러만 잔존.

---

## [2026-04-16] Telegram 일일 결산 "0건 +0원" 오보 수정 — KIS executions → DB trades 전환
- 카테고리: bug_fix
- 배경:
  - 2026-04-15 Telegram 알림이 실제 체결(매수 2 + 매도 1, 실현손익 +60,600원)과
    다르게 `체결: 0건, 실현손익: +0원 (+0.64%)`로 잘못 전송됨.
  - 원인: `post_market`에서 `self._account.get_executions()`(KIS
    `inquire-daily-ccld` API) 호출 시 해당 API가 500 에러 후 빈 결과 반환.
    `_enqueue_telegram_daily_summary`는 이 빈 `executions`를 그대로 사용하여
    `count=0, buy_count=0, sell_count=0`로 메시지 생성.
  - 의미 오류: formatter는 "실현손익" 라벨을 표시하는데 실제 전달되는 값은
    `balance.total_profit_loss`(KIS 평가손익, 미실현 포함). 라벨과 의미가
    달랐음.
  - Calendar 이벤트는 이미 `_load_today_trades()`(DB 조회)를 사용해 올바르게
    "+0.6% (3건 체결)"로 기록되었으나, Telegram은 같은 fallback을 쓰지
    않았음.
- 변경 파일:
  - src/engine.py:
    - `post_market()`: 장 마감 집계 전반을 DB `trades` 테이블 기반으로 전환.
      buy_count / sell_count / realized_pl / realized_rate를 DB에서 계산.
      KIS executions는 부가 로깅에만 사용.
    - `_enqueue_telegram_daily_summary()` 시그니처 변경(keyword-only):
      `executions` 제거, `realized_profit_loss` / `realized_rate` 추가.
      "실현손익" 라벨에 실제 실현손익(매도 trades.profit_loss_amount 합)을
      전달하도록 수정.
    - `_enqueue_daily_performance()`: executions(KIS 결과) 대신 trades(DB)
      수신. details JSON도 Trade 객체 속성에 맞게 변환(trade_type→side,
      profit_loss_amount 추가). KIS API가 빈 결과를 반환해도 체결 상세가
      DB에 정확히 저장됨.
    - `[일일결산]` 로그 메시지도 DB 기반 값으로 변경.
- 검증 결과: pytest ✅ (391 passed) | ruff ✅ | mypy: 기존 `object` 타입 힌트
  관련 pre-existing 에러만 잔존 (이번 변경과 무관)

---

## [2026-04-16] DailyPerformance 저장 버그 2건 수정 — Worker 경로 파라미터명·단위 불일치
- 카테고리: bug_fix
- 배경:
  - **버그 1 (이름 불일치)**: 2026-04-15 15:40~15:55 장 마감 후 일일 성과 저장이
    5회 재시도 후 DEAD 처리. 에러: `DailyPerformanceRepository.create() got an
    unexpected keyword argument 'total_profit_loss'`. Worker 분리(Phase 1)에서
    handler가 payload 키를 그대로 Repository.create() 호출에 사용했으나
    Repository 시그니처는 `total_pl`, `rate`, `count`를 요구.
  - **버그 2 (단위 불일치)**: 이름 불일치를 해결하면 이번에는 `profit_rate`가
    100배 크게 저장되는 문제 발생. `balance.total_profit_rate`는 KIS API의
    `ASST_ICDC_ERNG_RT`로 **퍼센트 단위**(예: 2.5)인데, DB `profit_rate`
    컬럼은 **비율 단위**(예: 0.025)로 저장하는 것이 기존 histori/legacy
    `_save_daily_performance` 경로와 일치. Worker enqueue 경로에는 `/100.0`
    변환이 누락되어 있었음.
  - 결과: 2026-04-15 일일 성과가 DB에 누락됨. 수정 이후 생성되는 레코드는
    기존 daily_performances 이력과 동일한 비율 스케일로 저장됨.
- 변경 파일:
  - src/worker/handlers.py:
    - `DailyPerformanceHandler.execute()` 내 `repo.create()` 호출 파라미터명 수정
      (`total_profit_loss=` → `total_pl=`, `profit_rate=` → `rate=`,
      `execution_count=` → `count=`).
    - docstring에 `profit_rate` 단위를 "비율, 예: 2.5% → 0.025"로 명시.
  - src/engine.py:
    - `_enqueue_daily_performance()`의 payload `profit_rate`를
      `float(balance.total_profit_rate) / 100.0`로 변환하여
      legacy `_save_daily_performance` 및 기존 DB 이력과 단위 통일.
    - 단위 변환 의도를 설명하는 주석 추가.
- 검증 결과: pytest ✅ (391 passed) | ruff ✅ | mypy: 기존 dead code
  (`_save_daily_performance`, `_sync_portfolio`)의 `balance: object` 타입
  관련 pre-existing 에러만 잔존 (이번 변경과 무관)

---

## [2026-04-15] ENSEMBLE 시그널 매매 전환율 0% 원인 조사 — observability 강화
- 제안서: docs/proposals/2026-04-15_ensemble-zero-conversion-investigation.md
- 카테고리: bug_fix (observability)
- 변경 파일:
  - src/strategy/base.py: Signal dataclass에 `meta: dict[str, Any]` 필드 추가
  - src/strategy/ensemble.py: HOLD 수렴 시 투표 집계 상세(method, votes)를 meta에 기록
  - src/engine.py: 시그널 skip 사유(hold_action, sell_without_position, risk_rejected, zero_quantity, low_confidence_sell)를 SIGNAL_SKIP 메트릭 + signal_value.skip_reason으로 기록. `_record_signal_skip()` 메서드 추가
  - tests/test_strategy/test_ensemble.py: HOLD meta 기록 검증 테스트 3개 추가
- 검증 결과: pytest ✅ (387 passed, 기존 실패 4건 동일) | mypy ✅ (신규 에러 없음) | ruff ✅

---

## [2026-04-15] Worker 분리 — 매매 엔진 I/O 비동기화 (Phase 1~3)
- 카테고리: feature (architecture)
- 배경:
  - 2026-04-14 네트워크 단절로 Google Calendar 등록 실패
  - post_market에서 Calendar/Telegram/DB 집계가 순차 실행되어 장 마감 후 작업 지연
  - 스크리닝 API 호출이 매매 사이클과 rate limiter를 공유하여 경합 발생
- 변경 내용:
  - **Phase 1**: PostgreSQL Outbox 패턴 task_queue 테이블 + Worker 프로세스
    - Calendar, Telegram, 일일집계, 포트폴리오, 일일성과를 Queue 경유로 전환
    - 실패 시 exponential backoff 재시도 (최대 5회), DEAD 시 Telegram 알림
  - **Phase 2**: 매매/시그널/메트릭 DB 기록 Queue화
    - record_trade(priority=10), record_signal(5), record_metric(3)
    - 매매 체결 후 즉시 다음 종목으로 이동 (DB 대기 제거)
  - **Phase 3**: Redis Rate Limiter + ScreeningWorker 분리
    - RedisRateLimiter(INCR 기반) + HybridRateLimiter(Redis 폴백)
    - 시간대별 할당량 동적 전환 (08:25 스크리닝100%, 08:55 장중80/20, 15:25 메인100%)
    - ScreeningWorker가 300초 주기로 독립 실행, 메인 엔진은 DB 결과만 읽기
- 신규 파일:
  - src/worker/__init__.py, queue.py, runner.py, handlers.py, screener.py
  - alembic/versions/702dbb24bf59_add_task_queue_table.py
  - tests/test_worker/ (test_queue, test_handlers, test_runner, test_rate_limiter, test_screener)
- 수정 파일:
  - src/db/models.py, src/db/repository.py, src/config.py, src/engine.py
  - src/api/rate_limiter.py, src/scheduler/jobs.py, src/utils/exceptions.py
  - main.py, docker-compose.yml, .env.example, tests/test_engine_db_integration.py
- 인프라 추가:
  - Redis 7-alpine (Docker, port 6380, --restart unless-stopped)
  - 대시보드 launchd 등록 (com.kis.dashboard)
- 검증 결과: pytest ✅ (388 passed) | Match Rate 97% | 프로세스 재시작 후 정상 동작 확인

## [2026-04-14] 앙상블 전략 미등록 + .env 기본전략 불일치 수정
- 카테고리: bug_fix
- 배경:
  - 앙상블 전략이 기본 전략으로 설정(2026-04-10)되었으나, 실제로는 이동평균만 실행됨
  - 원인 1: `StrategyRegistry.create_default()`에서 ensemble 전략을 등록하지 않음 (4종만 등록)
  - 원인 2: `.env`에 `STRATEGY_DEFAULT=moving_average`가 하드코딩되어 config.py 기본값 무시
- 변경 파일:
  - src/strategy/registry.py: `create_default()`에 EnsembleStrategy 등록 추가 (하위전략 4종 포함)
  - .env: `STRATEGY_DEFAULT=moving_average` → `ensemble` 변경
- 검증 결과: pytest ✅ (114 passed in test_strategy/) | 프로세스 재시작 후 앙상블 전략 정상 동작 확인

## [2026-04-14] CLAUDE.md 전면 현행화 — 실제 소스 구조·설정 기준 재작성
- 카테고리: docs
- 배경:
  - CLAUDE.md가 초기 설계 시점 기준으로 작성되어 실제 코드베이스와 다수 불일치
  - 누락: src/engine.py, src/backtest/, scripts/, Docker 파일, test_notify/ 등
  - 부정확: Rate Limit 기본값(3→virtual=5/real=20), 일일 한도(10,000→50,000)
  - 미비: 예외 클래스, 로깅 규약, 테스트 규칙, 실행 방법, Circuit Breaker 상세 등
- 변경 파일:
  - CLAUDE.md: 전면 재작성 (두 브랜치 fix/claude-md-overhaul + chore/update-claude-md 최선 컴바인)
- 주요 변경:
  - 기술 스택: httpx, websockets, pandas, pydantic, respx, Streamlit 추가
  - 디렉토리 구조: engine.py, backtest/, scripts/, docs/ 등 누락 항목 전부 추가
  - 코딩 컨벤션: future annotations, frozen dataclass, ruff/mypy 설정 구체화
  - 신규 섹션: 커스텀 예외 테이블, 로깅 규약, 테스트 조직 규칙, Alembic 워크플로우, 실행 방법
  - 설정 시스템: config_overrides.json 오버라이드, 환경별 기본값 테이블
  - Circuit Breaker: 별도 섹션으로 분리, 백오프 수치 명시
  - 모듈 경계: 의존성 방향 다이어그램 추가, 제약 완화 (단독 작업 시 참고용)
  - 환경변수: Strategy, Screening, Telegram, Docker, Health Check 전체 반영

## [2026-04-14] signals/trades/stocks 테이블 종목명 누락 수정
- 카테고리: bug_fix
- 배경:
  - signals, trades 테이블에 stock_name이 빈 문자열로 저장되는 문제 (signals 2,323건, trades 4건)
  - stocks 테이블에 name이 종목코드 그대로 저장된 경우 존재 (034220 → "034220")
- 근본 원인:
  - 현재가 API(`HTS_KOR_ISNM`)가 간헐적으로 빈 문자열 반환 → 그대로 DB에 저장
  - DB fallback 없이 API 응답만 의존
- 변경 파일:
  - src/engine.py:
    - `_resolve_stock_name()` 신규: API에서 이름 못 받으면 stocks 테이블에서 조회
    - `_process_stock()`: current.stock_name이 비어있으면 DB fallback 적용
    - `_update_stock_name_if_needed()`: stock.name이 빈 문자열인 경우도 갱신 대상에 포함
- 기존 데이터 수정:
  - signals: 2,323건 종목명 복원 (000660 SK하이닉스, 034020 두산에너빌리티, 034220 LG디스플레이)
  - trades: 4건 종목명 복원
  - stocks: 034220 "034220" → "LG디스플레이"
- 프로세스 재시작: 완료 (DB fallback 정상 동작 확인)

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
