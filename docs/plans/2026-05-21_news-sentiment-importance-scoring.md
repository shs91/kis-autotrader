# 작업계획 B — news_chunks sentiment/importance 스코어링 구현

- 작성일: 2026-05-21
- 상태: planned (자동 파이프라인 비대상)
- 담당: strategy-engineer + db-scheduler-engineer (스코어링 로직 + 적재)
- 우선순위: MEDIUM (범위 큼 — 설계 선행 필요)
- 선행 의존: **작업계획 A(뉴스 수집 정지 수정) 먼저 권장** — 수집이 멈춰 있으면 스코어링해도 신선 데이터가 없음.

## 1. 배경 (자기완결)

2026-05-21 데이터 점검 결과, `news_chunks` 714건 **전부** `sentiment`/`importance`가 NULL.
- `embedding`(Vector 1024)은 전부 채워져 있어 RAG 의미검색은 가능하나, 감성/중요도 점수가 없어 **뉴스를 매매 신호로 연결할 수 없음**.

## 2. 근본 원인 (코드 확정) — "미구현"

- `src/db/models.py:642-643` — `NewsChunk.sentiment: Mapped[float|None]`, `importance: Mapped[float|None]` (nullable). 컬럼은 `alembic/versions/84febb2fdc0a_*` (2026-05-19 마이그레이션)에 추가됨.
- `src/worker/collectors/base.py:180-192` — `NewsChunk(...)` 생성 시 `sentiment`/`importance`를 **set하지 않음** → 기본 None 적재.
- 스코어링(감성/중요도 계산) 로직이 **코드 어디에도 없음**. `docs/proposals/`에도 관련 제안서 0건 → 설계 단계에서 컬럼만 잡고 구현은 미착수.
- `src/db/analytics.py`의 `get_news_quality_stats()` (≈line 1163-1207)는 `AVG(importance)`를 **읽으려 시도**하지만 NULL만 반환 → 소비처는 존재(리포트/대시보드용), 매매 전략(`src/strategy/`)은 아직 미사용.

## 3. 목표 / 범위 (설계 결정 필요 항목 포함)

핵심: 이 작업은 **구현 전 설계 결정이 필요**하다. 새 세션에서 먼저 brainstorming으로 아래를 확정할 것.

설계 질문:
1. **스코어링 방식**: (a) 룰베이스(키워드/공시유형 가중), (b) 경량 한국어 감성 모델, (c) LLM(Claude API) 호출 — 비용·지연·정확도 트레이드오프. 임베딩 모델 재사용 가능 여부.
2. **sentiment 정의**: 종목 관점 호재/악재 [-1,1]? importance: 공시/뉴스 시장영향 [0,1]?
3. **계산 시점**: 적재 시 인라인(수집 지연↑) vs 배치 후처리 잡(분리). 단일 kis-postgres 부하 고려.
4. **소비처**: 매매 전략에 실제로 연결할지(예: 강한 악재 시 매수 억제/매도 가점), 아니면 리포트/대시보드 우선.
5. **백필**: 기존 714건 재스코어링 여부.

## 4. 작업 단계 (설계 확정 후)

### Phase 0 — 설계 (brainstorming 스킬 사용)
- 위 5개 질문을 사용자와 확정. 외부 모델/LLM 사용 시 비용·키·레이트리밋 정책 합의. 가능하면 `docs/proposals/` 또는 본 plan에 결정 기록.

### Phase 1 — 스코어링 함수 구현
- 새 모듈(예: `src/rag/scorer.py` 또는 `src/news/scoring.py`) — RawDocument/chunk를 받아 `(sentiment, importance)` 반환. 순수 함수로 단위 테스트 용이하게.
- 전략 모듈은 데이터를 인자로 받는다는 경계(CLAUDE.md) 준수 — API 직접 호출 금지.

### Phase 2 — 적재 경로 연결
- `src/worker/collectors/base.py:180-192`에서 `NewsChunk(... sentiment=..., importance=...)` 설정. (작업계획 A의 임베딩 위치 재구성과 충돌 가능 → A 먼저 끝낸 뒤 그 구조 위에서.)

### Phase 3 — 소비 (선택)
- `get_news_quality_stats()` 검증(이제 NULL 아님). 매매 전략 연결을 결정했다면 `src/strategy/`에서 데이터 인자로 소비.

### Phase 4 — 백필 (선택)
- 기존 청크 재스코어링 일회성 스크립트(`scripts/`).

## 5. 수용 기준
- [ ] 신규 적재 청크의 sentiment/importance가 채워짐.
- [ ] 스코어링 함수 단위 테스트 통과.
- [ ] `get_news_quality_stats()`가 비-NULL 평균 반환.
- [ ] pytest/ruff/mypy 통과.

## 6. 주의 / 제약
- 범위가 크고 외부 모델/비용 결정이 끼므로 **반드시 설계 합의 후 구현**. 임의로 LLM 호출/모델 추가하지 말 것.
- 작업계획 A와 `base.py` 동일 구간을 건드리므로 순서: **A → B**.
- 코드 변경 시 record_implementation + CHANGELOG rolling + 브랜치 커밋.

## 7. 트리거 프롬프트
```
docs/plans/2026-05-21_news-sentiment-importance-scoring.md 를 읽고 작업계획 B를 진행해줘.
먼저 Phase 0에서 brainstorming 스킬로 스코어링 방식(룰베이스/경량모델/LLM)·정의·계산시점·
소비처·백필 여부 5가지를 나와 확정한 뒤에 구현에 들어가. 작업계획 A(뉴스 수집 정지)가
아직 안 끝났으면 그걸 먼저 하자고 알려줘. DB 조회는 docker exec kis-postgres psql 사용.
```
