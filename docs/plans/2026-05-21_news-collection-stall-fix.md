# 작업계획 A — 뉴스 수집 정지(5/19 stall) + 임베딩 낭비 수정

- 작성일: 2026-05-21
- 상태: planned (자동 파이프라인 비대상 — docs/proposals/ 아님)
- 담당: db-scheduler-engineer / api-engineer 협업 (src/db/, src/worker/)
- 우선순위: HIGH
- 선행 의존: 없음 (단독 실행 가능)

## 1. 배경 (자기완결 — 컨텍스트 없이 읽어도 됨)

2026-05-21 데이터 점검에서 뉴스 수집 파이프라인이 **2026-05-19부터 사실상 정지**한 것을 발견.

DB 사실(점검 시점):
- `news_collection_state`: dart/rss 모두 `last_collected_at`/`updated_at`이 **2026-05-19 고정**, 이후 미갱신.
- `news_chunks`: `event_time` 최댓값 5/19 고정. 오늘 신규 적재 20건뿐 (총 714건, NEWS 582/DISCLOSURE 132).
- `system_metrics`의 `NEWS_COLLECTED` 메트릭은 오늘도 289건(dart 144, rss 144, pykrx 1) 기록 → 워커는 수집 루프를 돌고 임베딩(오늘 438배치)도 하지만 거의 다 중복.

## 2. 근본 원인 (코드 확정)

### 원인 ① 사이클별 commit 부재 → state 전진이 durable하지 않음 (stall의 핵심)
- `news_worker_main.py:137-141` — `with get_session() as session:` **하나**가 워커 전체 수명을 감싸고, 그 안에서 모든 사이클이 돈다. `repo`(NewsChunkRepository)와 `metric_repo`(SystemMetricRepository)가 이 단일 세션을 공유.
- `src/db/session.py` `get_session()` — **정상 컨텍스트 종료 시에만 `session.commit()`**, 예외 시 `session.rollback()`. 즉 워커가 graceful 종료할 때 단 한 번 커밋.
- `src/db/repository.py` `NewsChunkRepository.update_collection_state()` — `self._session.flush()`만, **commit 없음**.
- `src/db/repository.py` `SystemMetricRepository.record_metric()` — `flush()`만, commit 없음.
- `src/worker/news_collector.py` `NewsCollectorWorker.run()/run_once()` — 루프 어디에도 `commit()` 없음.
- 결과: 사이클별 state/청크/메트릭 변경이 **flush만 되고 커밋되지 않은 채 누적**. 워커가 크래시(launchd `com.kis.news-collector` 과거 종료코드 1 관측)나 SIGKILL로 비정상 종료하면 `get_session`의 commit이 실행되지 않거나 rollback → 그 사이 state 전진이 유실. 5/20 OOM 사고 + 재시작 반복으로 커서가 5/19에 묶임.

### 원인 ② 중복 판정 전에 임베딩 → 컴퓨트 낭비
- `src/worker/collectors/base.py:104-105` — `chunks = self._build_chunks(docs)` 가 **모든 doc을 임베딩한 뒤**(`_build_chunks` 내부 `embedder.encode`) `insert_chunks(chunks)`에서 중복을 버린다.
- `insert_chunks`(repository.py)는 이미 "배치 dedup → 단일 SELECT 필터 → add_all"로 중복을 거르지만, **임베딩이 그 앞단에서 이미 수행**되어 낭비. DB 증거: 오늘 438 임베딩 배치 → 실적재 20건(95%+ 낭비).

### 참고 — state 갱신 조건
- `src/worker/collectors/base.py:107-113` — `if docs:` 일 때 `update_collection_state(now(), cursor=None)`. `inserted`가 아니라 `docs` 기준이라, 원인 ①이 해결돼도 "중복만 받아도 커서 전진" 동작은 정상(중복=이미 그 시점까지 봤다는 뜻)이므로 유지 가능. 단 원인 ①이 우선.

## 3. 목표 / 범위
- 뉴스 수집 커서가 매 사이클 durable하게 전진하여 신선한 공시/뉴스를 다시 수집.
- 중복 doc에 대한 임베딩 컴퓨트 낭비 제거.
- 범위: `src/worker/`, `src/db/repository.py`(필요 시). 매매 엔진/전략 무관.

## 4. 작업 단계

### Phase 0 — 실측 검증 (수정 전 1회)
1. 워커 로그(`logs/news_collector.out.log`)와 `system_metrics`(NEWS_COLLECTED)·`news_collection_state.updated_at`을 대조해, 사이클별 커밋이 실제로 없는지/크래시 시 rollback으로 state가 유실되는지 확인.
2. 의문 해소: 메트릭은 DB에 보이는데 state는 5/19 — 어느 시점에 commit이 발생하는지(=재시작 시 graceful commit 추정) 로그로 확정.
3. `git log -- src/worker/ src/db/repository.py`에서 5/19 전후 관련 변경 확인.

### Phase 1 — 사이클별 commit 도입 (원인 ①)
- `NewsCollectorWorker.run_once()` 또는 `BaseCollector.run_cycle()` 끝에서 **collector 단위로 `session.commit()`** 호출(실패 시 `rollback()` 후 다음 collector로 격리). 또는 run_cycle을 `get_session()` 사용 per-cycle 구조로 재설계.
- 선택지 비교(둘 중 하나):
  - (a) per-cycle commit 추가: 변경 최소. 단일 세션 유지하되 사이클 끝 commit/rollback.
  - (b) per-cycle 세션: `run_cycle`마다 `with get_session()`으로 repo 재바인딩 — 트랜잭션 격리 명확, 변경 큼.
- 권장: (a) 먼저. 크래시 내성 확보가 목적.

### Phase 2 — 임베딩을 dedup 후로 이동 (원인 ②)
- `insert` 전에 `(ticker, content_hash)` 신규 여부를 먼저 판정하고, **신규 doc만 임베딩**하도록 `base.py`/`insert_chunks` 경계 재구성.
  - 옵션: `_build_chunks`를 (1) chunk 생성/hash 계산(임베딩 X) → (2) repo로 신규 hash 필터 → (3) 신규만 `embedder.encode` 두 단계로 분리.
  - `content_hash`는 임베딩 없이 계산 가능(`_content_hash`는 text만 사용) → dedup을 임베딩 앞으로 옮길 수 있음.

### Phase 3 — 검증 & 가동 확인
- 단위 테스트: 사이클 후 commit으로 state가 전진/persist 되는지, 크래시(예외) 시 다음 collector가 격리되는지, 신규만 임베딩되는지(임베딩 호출 수 = 신규 청크 수) 테스트.
- 기존 테스트 회귀 없음: `pytest tests/test_db/ tests/test_worker/ -q`, `ruff check src/`, `mypy src/db/repository.py src/worker/`.
- 반영: `com.kis.news-collector` 재시작 후 `news_collection_state.updated_at`이 당일로 갱신되고 `news_chunks.event_time` 최댓값이 오늘로 진행되는지, 임베딩 배치 수가 실적재 수에 수렴하는지 DB로 확인.

## 5. 수용 기준
- [ ] 워커 가동 중 `news_collection_state.updated_at`이 사이클마다(또는 신규 수집 시) 당일로 갱신.
- [ ] `news_chunks` 최신 `event_time`이 당일까지 진행.
- [ ] 임베딩 배치 수 ≈ 실제 신규 적재 수 (대량 중복 재임베딩 소거).
- [ ] pytest/ruff/mypy 통과, 회귀 0.

## 6. 주의 / 제약
- `src/db/`는 db-scheduler-engineer 영역, `src/worker/collectors/`·`api/`는 api-engineer 영역 — 인터페이스 변경 시 합의(CLAUDE.md 모듈 경계).
- 단일 kis-postgres 공유 구조이므로(2026-05-20 락 고갈 사고 참고) 트랜잭션을 너무 길게 열어 락 점유를 키우지 말 것 — per-cycle commit이 오히려 유리.
- 코드 변경 시 `scripts/record_implementation.py` 기록 + `docs/CHANGELOG.md` rolling 갱신 + 커밋(브랜치) 필수.

## 7. 트리거 프롬프트 (이 파일을 시작점으로 새 세션에서 실행)
```
docs/plans/2026-05-21_news-collection-stall-fix.md 를 읽고 작업계획 A를 실행해줘.
Phase 0(실측 검증)부터 시작해 근본 원인(사이클별 commit 부재 + 임베딩 낭비)을
확정한 뒤 Phase 1~3을 TDD로 진행해. DB는 `docker exec kis-postgres psql -U kis_user
-d kis_trader`로 조회(postgres MCP 미연결 시 폴백). 수정 후 pytest/ruff/mypy 통과를
확인하고, scripts/record_implementation.py 기록 + CHANGELOG rolling 갱신 후 새 브랜치에
커밋해줘. 반영 확인을 위해 com.kis.news-collector 재시작이 필요하면 나에게 `! launchctl
stop ... && launchctl start ...` 명령을 제시해줘(직접 실행은 분류기에 막힐 수 있음).
```
