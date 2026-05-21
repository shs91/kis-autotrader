# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (82건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

---

## [2026-05-21] 뉴스 수집 stall 수정 — 사이클별 commit/rollback + 임베딩 dedup 선행 (v0.2.12) — 🔴 핫픽스
- 계획서: docs/plans/2026-05-21_news-collection-stall-fix.md
- 카테고리: bug_fix
- 변경 파일:
  - src/worker/news_collector.py: `NewsCollectorWorker`에 `session` 주입. `run_once`가 collector 사이클마다 성공 시 `commit()`, 예외 시 `rollback()` 호출. 단일 장기 세션이 무한 루프를 감싸 변경이 graceful 종료 시 1회만 commit되던 구조를 사이클 단위로 durable하게 전환.
  - src/worker/collectors/base.py: `_build_chunks`→`_build_new_chunks`. `content_hash`(text만으로 산출)로 (배치 내 + DB 적재분) 중복을 임베딩 *앞단*에서 제거하고 살아남은 신규 청크만 `embedder.encode` 호출.
  - src/db/repository.py: `NewsChunkRepository.existing_keys(keys)` 신설 — (ticker, content_hash) 기존분을 단일 쿼리로 조회. `insert_chunks`도 이를 재사용(DRY).
  - news_worker_main.py: 워커가 공유하는 `session`을 `NewsCollectorWorker`에 주입.
  - tests: `TestPerCycleCommit` 3건(commit/rollback/세션 미주입 호환), `TestEmbedOnlyNewChunks` 2건(신규만 임베딩/전부 중복 시 미호출), `TestExistingKeys` 2건.
- 배경: 2026-05-21 점검에서 뉴스 수집이 5/19부터 stall. 단일 장기 세션이 워커 무한 루프를 감싸 `insert_chunks`/`update_collection_state`가 flush만 되고 commit은 graceful 종료 시 1회뿐. `_record_metric`만 별도 세션으로 commit돼 메트릭은 매일 적재되나 `news_collection_state`는 5/19 고정. `out.log`에서 `PendingRollbackError` 확인 — 한 번 오염된 세션이 종료까지 모든 op 실패. 또한 모든 doc을 임베딩한 뒤 `insert_chunks`에서 중복을 폐기해 컴퓨트 낭비(임베딩 다수 대비 실적재 20건).
- 영향: 사이클(collector)마다 commit으로 `news_collection_state.updated_at`/`news_chunks`가 durable 전진, 실패 시 rollback으로 세션 오염을 회복(다음 사이클 정상화). 신규 청크만 임베딩하여 중복 재임베딩 컴퓨트 제거. 단일 kis-postgres 공유 구조에서 per-cycle commit이 락 점유 시간도 단축.
- 검증 결과: pytest 824 passed | ruff ✅ (변경 파일 All checks passed) | mypy 신규 에러 0 (사전 dict type-arg 부채 14건 무관, baseline 14=14).
- 비고: 운영자 액션 — 수정 반영을 위해 `com.kis.news-collector` 재시작 필요. 재시작 후 `news_collection_state.updated_at` 당일 갱신 + `news_chunks.event_time` 최댓값 진행 + 임베딩 배치 수 ≈ 실적재 수 수렴 확인.

---

## [2026-05-20] 뉴스 청크 적재 SAVEPOINT 누적 → PG 락 테이블 고갈 수정 + 시각 의존 테스트 결함 정리 (v0.2.11) — 🔴 핫픽스
- 카테고리: bug_fix
- 변경 파일:
  - src/db/repository.py: `NewsChunkRepository.insert_chunks`를 "배치 내 (ticker,content_hash) 중복 제거 → 단일 SELECT로 기존분 필터 → 1회 add_all/flush"로 재작성. 정상 경로의 행별 `begin_nested()`(SAVEPOINT)를 제거하고 동시 적재 레이스 시에만 행별 폴백.
  - tests/test_db/test_news_chunk_repo.py: 배치 내 중복 dedup / 대량(50건) 중복 재적재 0건 테스트 3건 추가.
  - tests/test_strategy/test_risk.py: `TestShouldTakeProfit`·`TestValidateOrder` setup_method에 `is_near_market_close=False` 시각 격리 추가(파일 내 기존 컨벤션 일치). 프로덕션 로직 무변경.
  - tests/test_analytics.py → tests/test_analytics_queries.py: `tests/test_analytics/` 디렉토리와의 import 이름 충돌(전체 수집 차단) 해소 위해 리네임. `test_get_optimal_risk_params` lookback을 오늘 기준 산출로 바꿔 고정 과거 seed의 시각 의존 제거.
- 배경: 2026-05-20 15:33 KST 장 마감 직후 뉴스 수집기가 news_chunks에 대량 중복 공시를 INSERT하며 행별 SAVEPOINT 서브트랜잭션 락이 누적 → kis-postgres 락 테이블(6400 = max_locks_per_transaction 64 × max_connections 100) 고갈, `out of shared memory`(31,628회). 같은 DB를 공유하는 자동매매의 15:40 장 마감 결산이 worker 큐 등록(calendar_event/telegram_notify/daily_summary/sync_portfolio/daily_performance) 전부 실패 → 캘린더 매매결과·텔레그램 일일결산 누락. 복구는 `docker restart kis-postgres` + `engine.post_market()` 재실행 보정으로 처리. 충돌 해제 과정에서 시각 의존 테스트 결함(risk 4건, analytics 1건)이 함께 드러남.
- 영향: 대량 중복 공시에도 정상 경로 SAVEPOINT 0건 → 락 테이블 고갈 및 자동매매 결산 동반 차단 재발 차단. 전체 테스트 수집 복구(이전 collection interrupted) + 시각 의존 결함 제거로 야간/장 마감 후 실행에도 안정 통과.
- 검증 결과: pytest 전체 815 passed (이전 collection 단계 interrupted) | ruff ✅ All checks passed | mypy src/db/repository.py 새 에러 0 (사전 dict type-arg 부채 14건 무관).
- 비고: 운영자 액션 — 수정 코드 반영을 위해 `com.kis.news-collector` 재시작 필요(완료). 단일 kis-postgres를 전 서비스가 공유하는 구조라 한 서비스의 락 고갈이 결산까지 전파됨.

---

## [2026-05-19] CircuitBreaker `is_open` lazy reset — engine 자가 복구 결함 수정 (v0.2.10) — 🔴 핫픽스
- 카테고리: bug_fix
- 변경 파일:
  - src/api/client.py: `CircuitBreaker.is_open` property가 timer 만료를 검사해 자동 반개방하도록 변경. 신규 `_try_half_open()` 헬퍼로 `is_open` property와 `is_available()` 메서드의 reset 로직 일관화. 미사용 import `RateLimitExceededError` 정리.
  - tests/test_api/test_client.py: 회귀 테스트 2건 추가 — `test_is_open_resets_after_timeout` / `test_is_open_consistent_with_is_available`. 미사용 import 정리.
- 배경: 2026-05-19 09:34~09:40 약 8분간 장중 매매가 차단됨. `is_available()`은 timer 만료 시 `_failure_count = 0` 리셋하지만 `_is_open` 필드는 그대로 True 유지. `engine.py:317/382`가 `circuit_breaker.is_open` property를 검사 → 영원히 True → `record_success` 호출 기회 자체가 없어 자가 복구 불가.
- 영향: 서킷 브레이커가 timer 만료 후 자동으로 반개방되어 `engine.py`의 다음 사이클이 정상 진입. 첫 실제 요청 성공 시 `record_success()`가 호출되어 완전 close. 추후 같은 패턴의 영구 차단 재발 차단.
- 검증 결과: pytest 11 passed (CircuitBreaker 6 = 기존 4 + 신규 2, KISClient 5) | ruff All checks passed | mypy --strict src/api/client.py ✅.
- 비고: 운영자 액션 — autotrader 재시작 시점에 효과 발생. 장중 위험 회피 위해 15:30 장 마감 후 재시작 권장.

---

## [2026-05-18] 매수 게이트 진단 메트릭 신설 — BUY_REJECT enqueue + check_buy_gates (v0.2.9)
- 제안서: docs/proposals/2026-05-18_buy-gate-diagnostic-metric.md
- 카테고리: performance
- 변경 파일:
  - src/engine.py: BUY 시그널 경로에 `check_daily_trade_limit` + `check_buy_gates` 진단 추가, 거절 시 `_record_buy_reject(stock_code, reason, confidence, context)` 호출로 BUY_REJECT 메트릭 enqueue.
  - src/strategy/risk.py: `check_buy_gates(signal, balance) -> str | None` 신설. 게이트 평가 순서 RISK_GATE > LOW_CONFIDENCE > INSUFFICIENT_CASH. `validate_order` 하위 호환 유지.
  - tests/test_strategy/test_risk.py: `TestCheckBuyGates` 7건 (게이트별 사유 반환 + 우선순위 검증).
  - tests/test_engine_buy_gate_metric.py: BUY_REJECT 메트릭 통합 테스트 7건 (저신뢰/잔고 부족/리스크/일일 한도 분기 + 기록 실패 swallow).
- 배경: 5/15~17 분석에서 시그널→매수 전환 0% anomaly 재현. `validate_order` 단일 boolean으로는 거절 사유 불명 — 운영자가 어떤 게이트가 트립했는지 진단 불가.
- 영향: BUY_REJECT 메트릭이 `LOW_CONFIDENCE`/`INSUFFICIENT_CASH`/`RISK_GATE`/`DAILY_TRADE_LIMIT`/`OTHER` 분류로 적재. 다음 daily 분석부터 거절 사유 분포 진단 가능. 자동 파이프라인 D5(시그널→매수 전환 0%) 룰의 변별력 확보.
- 검증 결과: pytest 14 passed (TestCheckBuyGates 7 + BUY_REJECT 통합 7) | ruff ✅ All checks passed | mypy --strict 신규 모듈 ✅ (사전 존재 12건은 본 변경 무관).
- 비고: 21:35 KST `/run_implement` cycle은 implementer agent의 git commit 누락 + Verifier `set -e` 스크립트 중단으로 정상 종료 안 됨 → 수동 완료(옵션 A). D1~D5 결함(set -e/Verifier scope/agent commit/progress.json/markdown 갱신)은 후속 hotfix 대상.

---

## [2026-05-18] auto-implement PATH 보강 — verifier ruff FileNotFoundError 수정 (v0.2.8) — 🔴 핫픽스
- 카테고리: bug_fix
- 변경 파일:
  - scripts/run_auto_implement.sh: PATH 선두에 `$HOME/IdeaProjects/kis-autotrader/.venv/bin` prepend. 누락 시 `verifier/runner.py:70`의 `subprocess.run(["ruff", ...])`가 `FileNotFoundError: 'ruff'`로 죽음.
- 배경: 2026-05-17 16:36 텔레그램 `/run_implement` 트리거로 처음 verifier 통합 흐름이 실행됐을 때 종료코드 1. cycle·golden은 통과했으나 verifier 단계 진입 직후 ruff 바이너리를 PATH에서 못 찾아 실패. ruff는 `.venv/bin/ruff`에만 존재했고 launchd PATH(`~/.local/bin:/usr/local/bin:/usr/bin:/bin`)에 venv 경로가 없었음.
- 영향: 정규 평일 17:15 / 금 19:00 트리거 및 텔레그램 `/run_implement` 모두 verifier 단계가 정상 ruff 호출. exit 1 재발 차단.
- 검증 결과: `bash -n scripts/run_auto_implement.sh` ✅ | 새 PATH로 `command -v ruff` → `.venv/bin/ruff` 해결 확인.

---

