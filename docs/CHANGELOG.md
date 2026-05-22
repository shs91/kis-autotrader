# 변경 이력 (최근 5건)

> 전체 이력은 `implementation_logs` DB 테이블에 저장됩니다 (82건+).
> 이 파일은 최근 5건만 유지하며, 새 구현 시 가장 오래된 항목이 제거됩니다.
> 제안서 경로: docs/proposals/

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

