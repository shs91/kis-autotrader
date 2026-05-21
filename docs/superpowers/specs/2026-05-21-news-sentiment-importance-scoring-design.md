# 설계서 — 뉴스 sentiment/importance 룰베이스 스코어링 (작업계획 B)

- 작성일: 2026-05-21
- 원천 작업계획: `docs/plans/2026-05-21_news-sentiment-importance-scoring.md`
- 선행 의존: **작업계획 A(뉴스 수집 stall 수정) 완료** — PR #24 merge, 운영 검증 완료(stall 해제, 신선 청크 적재 재개).
- 상태: 설계 승인 대기 → 승인 시 writing-plans로 구현 계획 작성

## 1. 배경

`news_chunks`는 임베딩(Vector 1024)까지 적재되지만 `sentiment`/`importance`가 전부 NULL이고, 스코어링 로직이 코드 어디에도 없다. RAG 의미검색은 가능하나 뉴스를 "호재/악재·중요도"로 요약할 수단이 없다. 현재 `news_chunks`는 매매 전략과 미연결이며, `get_news_quality_stats()`만 `AVG(importance)`를 리포트용으로 읽는다(NULL만 반환 중).

## 2. Phase 0 설계 결정 (brainstorming 확정)

| # | 항목 | 결정 |
|---|------|------|
| 1 | 소비처 | **리포트/대시보드 먼저**. 매매 전략 연결은 본 작업 범위 밖(향후 별도). |
| 2 | 스코어링 방식 | **룰베이스**(키워드 lexicon + 공시유형 가중). 순수 함수로 설계해 추후 모델/LLM 교체 가능. |
| 3 | 정의 | `sentiment` = 종목관점 호재(+)/악재(−) 연속값 **[-1,1]**. `importance` = 시장영향 크기 **[0,1]**. NULL = '미스코어'만 의미. 키워드 무매칭 = 중립 `0.0`. |
| 4 | 계산 시점 | **적재 시 인라인**(`_build_new_chunks`). 룰베이스는 모델/네트워크 없이 빠름 → A의 사이클별 commit 구조에 그대로 편승. |
| 5 | 백필 | **예** — 기존 NULL 청크(~1,300건) 일회성 스크립트로 재스코어링. |
| 6 | lexicon 위치 | **scorer.py 내 상수 dict**(하드코딩). 버전관리·결정적·테스트 용이. |

## 3. 아키텍처

### 3.1 모듈 / 인터페이스 — `src/rag/scorer.py`

향후 **로컬 모델 기반 의사결정**으로의 확장을 전제로, 스코어러를 교체 가능한 추상화로 둔다(룰베이스는 그 첫 구현).

```python
@dataclass(frozen=True)
class ChunkScore:
    sentiment: float          # [-1, 1]
    importance: float         # [0, 1]
    method: str               # provenance: "rule_v1" 등 (= scorer 식별자)

class Scorer(Protocol):
    method: str               # 이 스코어러의 식별자/버전
    def score(
        self, text: str, source_type: NewsSourceType,
        title: str | None, metadata: dict[str, object],
    ) -> ChunkScore: ...

class RuleBasedScorer:        # Scorer 구현 #1 (method="rule_v1")
    ...

def get_scorer() -> Scorer:   # 팩토리. 현재는 RuleBasedScorer 고정,
    ...                       # 추후 env/config로 로컬 모델 스코어러 선택.
```

- **반환 타입을 tuple이 아닌 `ChunkScore` 데이터클래스로**: 추후 confidence·feature 벡터 등 필드를 추가해도 호출부 무변경. `method`로 provenance를 함께 운반.
- **순수/결정적**: 룰베이스 구현은 I/O·네트워크·모델 없음. chunker/embedder와 같은 `src/rag/` 도메인.
- **에러 내성**: 빈 텍스트·`None` title·이상 metadata 등 어떤 입력에도 예외를 던지지 않고 중립 `ChunkScore(0.0, 0.0, method)` 폴백. 스코어링 실패가 적재를 절대 막지 않는다.
- **교체 가능성(핵심)**: 호출부(`base.py`, 백필)는 `get_scorer().score(...)`만 호출 → 추후 로컬 모델 스코어러를 새 `Scorer` 구현으로 추가하고 팩토리에 등록하면 호출부·스키마 무변경으로 전환. 룰베이스 점수는 모델 도입 후에도 안정적 baseline 피처로 공존 가능.

### 3.2 스코어링 로직

**sentiment ∈ [-1, 1]**
- 모듈 상수 lexicon: `POSITIVE_TERMS: dict[str, float]`(호재), `NEGATIVE_TERMS: dict[str, float]`(악재).
  - 호재 예: 흑자전환·신규수주·계약체결·최대실적·자사주매입·배당확대·특허취득·승인·목표가상향
  - 악재 예: 적자·영업정지·횡령·배임·소송·감자·유상증자·부도·상장폐지·불성실공시·리콜·압수수색·목표가하향
- `text`+`title`(소문자/공백 정규화) 내 매칭 항목의 가중합: `raw = Σ(pos weight) − Σ(neg weight)`.
- 정규화: `sentiment = tanh(raw / SENTIMENT_SCALE)` → [-1,1]. 무매칭이면 `raw=0 → 0.0`.

**importance ∈ [0, 1]**
- `source_type` 기본 가중: `IMPORTANCE_BASE = {DISCLOSURE: ..., EARNINGS: ..., REPORT: ..., NEWS: ...}` (공시/실적이 뉴스보다 높음).
- 고영향 키워드 boost: `HIGH_IMPACT_TERMS`(합병·유상증자·상장폐지·횡령·영업정지 등) 매칭 시 가산 — 방향(호재/악재) 무관, 영향 '크기'.
- DART 공시유형 boost: `metadata`의 `report_nm`/`category` 등 고영향 공시유형 가산.
- `importance = clip(base + boosts, 0.0, 1.0)`.

> 두 lexicon/가중치 상수는 scorer.py 상단에 모아 두고, 단위테스트로 대표 케이스를 고정한다. 튜닝은 상수 수정 + 커밋으로.

### 3.3 적재 연결 (인라인) — `src/worker/collectors/base.py`

`_build_new_chunks`의 survivors 루프(현 `base.py:200-213`)에서 `NewsChunk(...)` 생성 시:
```python
score = scorer.score(chunk.text, doc.source_type, doc.title, doc.metadata)
NewsChunk(
    ...,
    sentiment=score.sentiment,
    importance=score.importance,
    chunk_metadata={"section": chunk.section, "score_method": score.method, **doc.metadata},
)
```
- `scorer`는 `__init__`에서 `get_scorer()`로 1회 주입(collector 인스턴스가 보유) — embedder/repo와 동일 패턴.
- **provenance**: `score.method`를 `chunk_metadata`에 `score_method`로 기록(JSONB, 마이그레이션 불요). 모델 도입 시 룰/모델 청크 구분·재스코어링 기준이 됨.
- 임베딩 직후·DB 적재 직전. A의 collector 단위 commit/rollback 격리 구조를 그대로 사용(추가 트랜잭션/세션 없음).

### 3.4 백필 — `scripts/backfill_news_scores.py`

- `sentiment IS NULL`인 청크를 배치(예: 500건)로 SELECT → `get_scorer().score(chunk_text, source_type, title, chunk_metadata)`로 재계산 → `sentiment`/`importance` + `chunk_metadata.score_method` `UPDATE` → **배치별 commit**(단일 kis-postgres 락 점유 최소화, 2026-05-20 락 고갈 사고 교훈).
- idempotent: 재실행 시 이미 채워진 청크는 `IS NULL` 필터로 자연히 제외.
- 향후 로컬 모델 도입 시 같은 스크립트로 `score_method` 기준 선택 재스코어링 가능(인자로 대상 필터 확장 여지).
- DB 접근은 기존 repository/session 패턴 재사용(프로덕션 DB 직접 접근 규칙 준수).

### 3.5 소비처 검증 — `src/db/analytics.py`

`get_news_quality_stats()`의 `by_source` 쿼리에 `AVG(sentiment) AS avg_sentiment` 추가(현재 `AVG(importance)`만). 리포트/대시보드에서 비-NULL 평균이 노출되는지 확인. 대시보드 표시 변경이 필요하면 해당 페이지에서 컬럼 추가(범위 최소).

## 4. 데이터 흐름

```
[신규 적재 경로]
collect() → _build_new_chunks: chunk+hash → dedup → embed(survivors)
          → score_chunk(survivor)  ← 신규
          → NewsChunk(sentiment, importance) → insert_chunks → per-cycle commit (A)

[백필 경로]
backfill 스크립트 → SELECT(sentiment IS NULL) → score_chunk → UPDATE → 배치 commit

[소비 경로]
news_chunks.{sentiment,importance} → get_news_quality_stats(AVG) → 리포트/대시보드
```

## 5. 에러 처리

- `RuleBasedScorer.score`는 어떤 입력에도 예외 없이 중립 `ChunkScore(0.0, 0.0, "rule_v1")` 폴백 — 적재/백필을 막지 않음.
- 백필 배치 중 오류: 해당 배치 rollback 후 다음 배치 진행(전체 중단 금지), 로그 기록.
- lexicon 매칭은 부분 문자열 기반 — 과매칭 위험은 테스트 케이스로 관리(예: '무상증자' vs '유상증자' 구분).

## 6. 테스트 전략

- **스코어러 단위테스트**(`tests/test_rag/test_scorer.py`):
  - 호재 문장 → sentiment > 0, 악재 문장 → sentiment < 0, 무매칭 → 0.0.
  - 고영향 공시(상장폐지 등) → importance 상위, 일반 뉴스 → 하위.
  - 빈 텍스트/`None` title/빈 metadata → `ChunkScore(0.0, 0.0, "rule_v1")`.
  - 값 범위 불변식: sentiment ∈ [-1,1], importance ∈ [0,1].
  - `ChunkScore.method == "rule_v1"`, `get_scorer()`가 `RuleBasedScorer` 반환.
- **적재 연결 테스트**(`tests/test_worker/.../test_base.py` 확장): `_build_new_chunks` 결과 청크의 sentiment/importance 비-NULL·범위 내, `chunk_metadata["score_method"]` 기록 확인.
- **백필 테스트**: NULL 청크 → 채워짐, idempotency(재실행 시 변화 없음).
- 회귀: `pytest tests/test_rag/ tests/test_worker/ tests/test_db/ -q`, `ruff check src/`, `mypy`(신규 에러 0).

## 7. 수용 기준 (작업계획 B §5)

- [ ] 신규 적재 청크의 sentiment/importance가 채워짐.
- [ ] 스코어링 함수 단위 테스트 통과.
- [ ] `get_news_quality_stats()`가 비-NULL 평균(importance + sentiment) 반환.
- [ ] 백필 후 기존 청크 sentiment/importance 비-NULL.
- [ ] pytest/ruff/mypy 통과, 회귀 0.

## 8. 범위 밖 (YAGNI)

- 매매 전략 연결(강한 악재 시 매수억제 등) — 소비처 결정상 제외, 점수 신뢰 검증 후 별도 작업.
- 로컬 모델/LLM 스코어러 **구현** — `Scorer` 인터페이스·`get_scorer()` 팩토리·provenance seam만 마련하고, 실제 모델은 도입 안 함(plan B의 '임의 LLM/모델 추가 금지' 준수). §9 참조.
- lexicon 외부 설정파일/DB화 — 상수 dict로 시작.
- provenance 전용 컬럼/인덱스 — `chunk_metadata` JSONB로 시작, 방식별 대량 쿼리 필요해지면 그때 마이그레이션.

## 9. 향후 확장: 로컬 모델 의사결정 (seam만 마련, 구현 X)

적재 데이터가 추후 **로컬 모델 기반 의사결정의 피처**로 사용될 예정. 본 작업은 그 전환을 막지 않도록 다음 seam을 남긴다:

- **스코어러 교체점**: `Scorer` Protocol + `get_scorer()` 팩토리. 로컬 모델 스코어러는 새 `Scorer` 구현(`method="model_vX"`)으로 추가 + 팩토리 등록만 하면 `base.py`/백필 호출부·DB 스키마 무변경으로 전환.
- **반환 확장점**: `ChunkScore` 데이터클래스 — confidence·feature 등 필드 추가 시 호출부 무변경.
- **provenance**: `chunk_metadata.score_method`로 룰/모델 청크 구분 → 모델 도입 시 선택적 재스코어링·방식 A/B·품질 비교 가능.
- **피처 스토어 관점**: `news_chunks`(embedding 1024 + sentiment + importance + chunk_text + event_time + score_method)를 모델 입력 피처 집합으로 취급. 룰베이스 점수는 모델 도입 후에도 안정적 baseline 피처로 공존.
- **읽기 경계(미구현)**: 종목별 피처 집계/검색은 향후 `src/rag/retriever.py`(현재 부재)가 담당. 본 작업은 `get_news_quality_stats()` 집계까지만, retriever·모델·전략 연결은 후속.

## 10. 모듈 경계 (CLAUDE.md)

- `src/rag/scorer.py` 신설: RAG 도메인. 전략(`src/strategy/`)은 본 작업에서 건드리지 않음.
- `src/worker/collectors/base.py` 수정: api-engineer 영역(인라인 1~2줄 호출 추가) — 인터페이스 변경 아님.
- `src/db/analytics.py` 수정: db-scheduler-engineer 영역(쿼리 컬럼 추가).
- `scripts/backfill_news_scores.py` 신설.
