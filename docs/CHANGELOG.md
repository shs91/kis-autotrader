# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (82건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-22] 일일 MDD halt 순손실 가드 — 흑자 구간 조기 halt 제거 (v0.4.2) — 🔴 핫픽스
- 제안서: docs/proposals/2026-05-21_daily-drawdown-peak-denominator-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/strategy/risk.py: `record_trade_result`의 MDD 발동 조건에 `self._daily_cumulative_pnl < 0` 순손실 가드 추가. 분모가 '당일 실현이익 피크'라 장 초반 작은 피크 직후 정상 손절 1건만으로 비율이 폭증하던 흑자 구간 오발동 제거.
  - tests/test_strategy/test_risk.py: 신규 `TestDailyDrawdownNetLossGuard` 3종(흑자 무halt 회귀 / 순손실 halt 보존 / 연패 경로 무영향) + 기존 `test_daily_drawdown_halt_returns_specific_code`를 순손실 시나리오로 갱신.
  - tests/test_engine_buy_gate_metric.py: 구 동작(흑자 halt) 의존 케이스를 순손실 시나리오로 갱신.
- 배경: 2026-05-21 09:11 익절 +39,440(피크) → 09:21 손절 -24,300 → 누적 +15,140(흑자)인데 피크 대비 회수폭 61.6% ≥ 5%로 `MAX_DAILY_DRAWDOWN` halt 발동, 장 마감까지 5시간 35분 전면 중단(66사이클, 평소 500~700 대비 91% 급감). trip 값 61.6% > 허용 상한 15%라 param 튜닝으로 막을 수 없는 분모 정의(로직) 결함. 사용자가 안 (a) 순손실 가드 채택(고위험 리스크 게이트 완화 → 수동 승인 후 PR #37).
- 영향: 일일 MDD halt는 당일 누적이 순손실(<0)일 때만 발동(일일 '손실' 한도 취지 일치). 흑자 구간 '첫 익절 → 손절' 오발동 제거로 정상 매매 지속(추정 600~700사이클 정상화). 흑자 구간 give-back 보호는 per-position 트레일링 스톱이 담당.
- 검증 결과: pytest test_risk 53 + 전체 908 passed (flaky test_health_endpoint 1건 deselect — 실DB 신선도 의존, 무관) | ruff ✅ | mypy ✅.
- 비고: 운영자 액션 — 전략 로직 변경 반영을 위해 `com.kis.autotrader` 재시작 필요. 동반 권장(별도): halt 발동 시 system_metrics(HALT) 1회 적재로 모니터링 가시성 확보.

---

## [2026-05-22] Stop 훅 검증 게이트를 in-session verifier와 실제 연결 — 충족불가 게이트의 헛돌이 루프 제거 (v0.4.1)
- 카테고리: bug_fix
- 변경 파일:
  - scripts/harness/run_verifier.py: `HARNESS_CYCLE_ARTIFACTS_PATH`가 설정되면 Stop 훅이 읽는 표준 산출물 파일(`cycle_artifacts.json`, top-level pytest/mypy/ruff 키)을 함께 기록. in-session verifier agent가 step 5에서 실행하면 게이트 자동 충족. env 미설정(수동 실행)이면 미기록.
  - src/harness/cycle/orchestrator.py: 위 env를 `claude` 서브프로세스에 주입 + 사이클 시작 시 이전 사이클 산출물 제거(거짓 통과 방지).
  - scripts/claude-hooks/run_hook.py: 페이로드→파일 폴백 + 재진입 가드(`stop_hook_active`). 첫 종료 시도엔 차단(검증 유도), 재진입에도 부재면 통과+경고로 무한루프 차단. 최종 강제력은 후처리 verifier 재시작 게이트가 유지.
  - scripts/auto_implement_prompt_v2.txt: step 5 verifier 실행이 게이트를 자동 충족함을 명시(코디네이터의 수동 파일 작성 방지).
  - tests: test_hook_wrapper(재진입 가드/첫 시도 차단/격리 보강), test_verifier_cli(canonical 쓰기·스킵), test_cycle_orchestrator(env 주입·stale 제거) 신규 7종.
- 배경: orchestrator가 `HARNESS_CYCLE_VERIFICATION_REQUIRED=1`로 `claude -p`를 띄우면 Stop 훅이 `verification_artifacts`를 요구하나 Claude Code Stop 이벤트는 이를 절대 싣지 않음. 산출물을 만드는 후처리 verifier는 claude 종료 *후* 실행돼 시점상 게이트 충족 불가 → 매 종료 차단 → headless claude가 강제 재개되어 Claude Code 내부 상한까지 무의미한 턴/토큰/시간 소모(검증 강제는 못 함). 격리 재현 테스트로 headless가 Stop exit 2를 정직히 따라 재진입(loop)함을 실증했고, 호스트 `~/.kis-autotrader/cycle_artifacts.json`에 코디네이터가 수동으로 써넣은 흔적(5/22 17:16)으로 실제 차단 발생을 확증.
- 영향: verifier(쓰기)와 Stop 훅(읽기)이 단일 산출물 경로를 공유해 게이트가 의도대로 작동. step 5 verifier 실행만으로 종료 게이트 충족, 재진입 가드로 헛돌이 루프 제거(이전 11분대 사이클 정상화 기대).
- 검증 결과: pytest test_harness 169 passed (신규 7 포함) | ruff 변경 파일 ✅ | mypy 변경 파일 ✅ | E2E 배선 4시나리오 실증(쓰기→읽기 통과 / 첫 시도 차단(2) / 재진입 루프 차단(0+경고)).
- 비고: PR #36 머지. 함께 묶였던 2026-05-21 파이프라인 문서 3건은 `docs/pipeline-artifacts-2026-05-21` 브랜치로 분리(critical drawdown 제안서 (a)/(b) 결정 대기). 하네스 내부 도구 변경이라 서비스 재시작 불요 — 다음 자동구현 cron(월 17:15)부터 적용.

---

## [2026-05-22] 트레일링 스톱 + 마감 청산 게이트 — 고점 대비 되돌림 청산 (v0.4.0)
- 계획서: docs/superpowers/plans/2026-05-22-trailing-stop-and-market-close-gate.md (설계: docs/superpowers/specs/2026-05-22-trailing-stop-and-market-close-gate-design.md)
- 카테고리: feature
- 변경 파일:
  - src/strategy/risk.py: `should_trailing_stop(current, avg, peak)`(시간 무관 — 무장 임계 도달 후 고점 대비 되돌림 청산), `should_close_for_market_end(current, avg, now)`(마감 임박 + 최소 수익률 이상 이익 포지션만 강제 실현; 트레일링과 독립) 신설. `should_stop_loss`/`should_take_profit` 미변경(후자는 폴백 경로에서만 사용).
  - src/engine.py: `_process_held_stock` 청산 우선순위 재구성 — 손절 > 마감 청산 게이트 > 트레일링(또는 TRAILING_STOP_ENABLED=false 시 고정 익절) > 전략매도. 인메모리 `_peak_prices` 고점 추적(평가 시작 시 `max(seed, 현재가)` 갱신, 매수/매도 성공 시 pop), `pre_market`에서 `_load_peak_prices()`로 portfolios.peak_price 시드. 일봉 없는 ETN 경로(`_evaluate_held_without_daily`)에도 동일 적용.
  - src/config.py: `TRAILING_STOP_ENABLED`(true)·`TRAILING_ACTIVATION_RATIO`(0.05)·`TRAILING_DRAWDOWN_RATIO`(0.05)·`MIN_PROFITABLE_CLOSE`(0.015) 4종.
  - src/db/models.py·repository.py: `Portfolio.peak_price`(Float nullable), `SellReason.TRAILING_STOP`/`MARKET_CLOSE`, `PortfolioRepository.upsert(peak_price)`(미지정 시 기존 고점 보존) + `get_peak_prices()` 시드 조회. src/worker/handlers.py·engine `_enqueue_sync_portfolio`: peak_price를 비동기 sync_portfolio 경로로 영속화(핫패스 동기 DB 0개).
  - alembic: peak_price 컬럼 + sell_reason enum 값 마이그레이션(autocommit_block, 적용 보류).
  - tests: risk 단위(트레일링 4 + 마감게이트 5), 엔진 통합(test_engine_trailing_stop 9), repo(test_portfolio_peak 4), 모델(2), ETN 경로 테스트 트레일링 의미로 갱신.
- 배경: 기존 청산은 +5% 고정 익절뿐이라 고점 대비 되돌림을 못 잡음. 760027(키움 인버스 2X 전력 TOP5 ETN)이 평균단가 3,565원 대비 +27%까지 상승 후 되돌림에도 무한 보유. 트레일링이 익절을 대체(수익 나면 추격)하고, 마감 게이트로 이익 포지션을 장 마감 전 실현하되 손실 포지션은 손절에만 맡김(시간 의존 파라미터 0개 — 게이트 발동 조건만 시간 기반).
- 영향: 무장(고점 ≥ avg×1.05) 후 고점 대비 5% 되돌림 시 "트레일링" 청산. 마감 임박 + 수익률 ≥ 1.5%면 "마감청산". 일봉 미조회 ETN도 동일 평가. peak는 재시작/장 간 portfolios.peak_price로 복원.
- 검증 결과: pytest 869 passed | ruff 변경 파일 All checks passed(사전 models.py E501 1건 무관) | mypy 신규 에러 0.
- 비고: 운영자 액션 — 머지 후 `alembic upgrade head`(공유 kis-postgres에 peak_price 컬럼 + enum 값) + `com.kis.autotrader` 재시작 + `scripts/record_implementation.py`로 DB 구현 이력 기록 필요(worktree에 .env 부재로 보류).

---

## [2026-05-21] 일봉 부재 시 보유 종목 현재가 기준 손절/익절 평가 — ETN 리스크 청산 누락 수정 (v0.3.1) — 🔴 핫픽스
- 카테고리: bug_fix
- 변경 파일:
  - src/engine.py: `_process_stock`의 `_get_daily_df() is None` 분기를 분리 — 보유 종목이면 `_evaluate_held_without_daily()`로 현재가만 실시간 조회해 손절/익절을 평가(HOLD 시그널 주입으로 전략매도 분기 제외), 미보유 종목은 기존대로 `EVAL_SKIP`. 종목명 해결 로직을 `_resolve_current_stock_name()` 헬퍼로 추출(두 경로 공유, 중복 제거). `RISK_ONLY_EVAL` 메트릭 신설.
  - tests/test_engine_risk_only_eval.py: 신설 — 손절 발동/익절 발동/데드존 미발동/미보유 스킵 4케이스.
- 배경: ETN(760027)처럼 KIS 일봉 조회가 0건이면 `_get_daily_df`가 None을 반환, `_process_stock`이 `EVAL_SKIP` 후 즉시 return → 보유 종목의 손절/익절/전략매도가 통째로 누락. 평균단가 3,565원 대비 현재가 4,535원(+27%)으로 익절선(+5%)을 한참 넘겼는데도 매도 평가 자체가 실행되지 않아 무한 보유. `system_metrics`에 `DAILY_DATA_INSUFFICIENT`(returned_count=0) + `EVAL_SKIP`이 매 사이클 반복 적재된 것으로 확인.
- 영향: 일봉이 없어도 보유 종목은 현재가 vs 평균단가 기준 손절(-3%)/익절(+5%, 14:30 이후 +2.5%)을 평가한다. 전략매도(데드크로스 등)는 일봉 의존이라 제외. 데이터 없으면 보유분 리스크 관리가 통째로 멈추던 빈틈 차단. 760027은 다음 사이클에 익절 매도 예상.
- 검증 결과: pytest 85 passed (신규 4 포함) | ruff ✅ All checks passed | mypy 신규 에러 0 (baseline 43→42).
- 비고: 운영자 액션 — 수정 반영을 위해 `com.kis.autotrader` 재시작 필요. 트레일링 스톱 부재는 별도 과제로 잔존.

---

## [2026-05-21] 뉴스 청크 sentiment/importance 룰베이스 스코어링 + 백필 (v0.3.0)
- 계획서: docs/superpowers/plans/2026-05-21-news-sentiment-importance-scoring.md (설계: docs/superpowers/specs/2026-05-21-news-sentiment-importance-scoring-design.md)
- 카테고리: feature
- 변경 파일:
  - src/rag/scorer.py: 신설. `Scorer` Protocol + `ChunkScore`(sentiment[-1,1]/importance[0,1]/method) 데이터클래스 + `RuleBasedScorer`(호재/악재 lexicon·source_type 가중·고영향 boost) + `get_scorer()` 팩토리. longest-match-wins로 부분문자열 이중계산 방지, 어떤 입력에도 예외 없이 중립 폴백.
  - src/worker/collectors/base.py: `_build_new_chunks`에서 NewsChunk 생성 시 `get_scorer().score()`로 sentiment/importance 인라인 계산, `chunk_metadata.score_method`로 provenance 기록(고정 키 우선순위 보정).
  - src/db/analytics.py: `get_news_quality_stats` by_source 쿼리에 `AVG(sentiment)` 추가.
  - scripts/backfill_news_scores.py: 신설. sentiment NULL 청크를 배치별 commit으로 백필(idempotent, 단일 postgres 락 점유 최소화).
  - tests: test_rag/test_scorer.py 14건, test_base.py 스코어링 2건, test_db/test_backfill_news_scores.py 2건.
- 배경: news_chunks가 임베딩(Vector 1024)까지 적재되나 sentiment/importance가 전부 NULL이고 스코어링 로직이 부재. 소비처는 리포트/대시보드 우선(매매 전략 미연결), 적재 데이터는 향후 로컬 모델 의사결정의 피처로 확장 예정 → `Scorer` 추상화·`ChunkScore`·provenance로 교체 seam 마련.
- 영향: 신규 적재 청크가 자동 스코어링되고 기존 청크는 백필로 채워짐. `get_news_quality_stats`가 비-NULL 평균(importance+sentiment)을 리포트/대시보드에 노출. 룰베이스는 추후 모델 스코어러로 호출부·스키마 무변경 전환 가능.
- 검증 결과: pytest 222 passed (rag+worker+db) | ruff 변경파일 All checks passed (analytics 사전 E501 2건 무관) | mypy 신규 에러 0.
- 비고: 운영자 액션 — 신규 적재분 스코어링 반영을 위해 `com.kis.news-collector` 재시작 + 기존분 백필 `scripts/backfill_news_scores.py` 1회 실행 필요.

---


