# 뉴스 sentiment/importance 룰베이스 스코어링 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `news_chunks`에 적재되는 청크마다 종목관점 sentiment[-1,1]·시장영향 importance[0,1]를 룰베이스로 계산해 채우고, 기존 NULL 청크를 백필하며, 리포트 집계에 노출한다.

**Architecture:** `src/rag/scorer.py`에 교체 가능한 `Scorer` 추상화(룰베이스 첫 구현)를 두고, collector 적재 경로(`base.py`)에서 인라인 호출해 점수+provenance(`score_method`)를 기록한다. 일회성 스크립트로 기존 청크를 백필하고, `get_news_quality_stats()`에 `AVG(sentiment)`를 추가한다. 향후 로컬 모델 스코어러는 `get_scorer()` 팩토리에 새 `Scorer` 구현을 등록하면 호출부·스키마 무변경으로 전환된다.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, pytest (+sqlite in-memory), pgvector(운영), ruff, mypy(strict).

**설계서:** `docs/superpowers/specs/2026-05-21-news-sentiment-importance-scoring-design.md`

---

## File Structure

- **Create** `src/rag/scorer.py` — `ChunkScore` 데이터클래스, `Scorer` Protocol, `RuleBasedScorer`, lexicon 상수, `get_scorer()` 팩토리. (스코어링 도메인 단일 책임)
- **Create** `tests/test_rag/test_scorer.py` — 스코어러 단위테스트.
- **Modify** `src/worker/collectors/base.py` — `BaseCollector.__init__`에 scorer 주입, `_build_new_chunks`에서 인라인 스코어링 + `score_method` 기록.
- **Modify** `tests/test_worker/test_collectors/test_base.py` — 적재 청크 점수/`score_method` 검증 테스트 추가.
- **Modify** `src/db/analytics.py` — `get_news_quality_stats()` by_source 쿼리에 `AVG(sentiment)` 추가.
- **Create** `scripts/backfill_news_scores.py` — NULL 청크 배치 백필(idempotent).
- **Create** `tests/test_db/test_backfill_news_scores.py` — 백필 동작·idempotency 테스트.
- **Modify** `pyproject.toml`, `src/__version__.py` — 버전 범프.
- **Modify** `docs/CHANGELOG.md` — rolling 갱신.

---

## Task 1: scorer 모듈 (Scorer 추상화 + RuleBasedScorer)

**Files:**
- Create: `src/rag/scorer.py`
- Test: `tests/test_rag/test_scorer.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_rag/test_scorer.py`:
```python
from __future__ import annotations

import math

from src.db.models import NewsSourceType
from src.rag.scorer import ChunkScore, RuleBasedScorer, get_scorer


def test_get_scorer_returns_rule_based() -> None:
    scorer = get_scorer()
    assert isinstance(scorer, RuleBasedScorer)
    assert scorer.method == "rule_v1"


def test_positive_text_has_positive_sentiment() -> None:
    s = get_scorer().score("사상최대 실적 흑자전환 신규수주", NewsSourceType.NEWS, None, {})
    assert s.sentiment > 0
    assert s.method == "rule_v1"


def test_negative_text_has_negative_sentiment() -> None:
    s = get_scorer().score("횡령 혐의로 압수수색, 영업손실 적자전환", NewsSourceType.NEWS, None, {})
    assert s.sentiment < 0


def test_no_keyword_text_is_neutral() -> None:
    s = get_scorer().score("회사가 정기 주주총회를 개최한다", NewsSourceType.NEWS, None, {})
    assert s.sentiment == 0.0


def test_empty_content_returns_zero_zero() -> None:
    s = get_scorer().score("", NewsSourceType.NEWS, None, {})
    assert s == ChunkScore(0.0, 0.0, "rule_v1")


def test_disclosure_base_importance_higher_than_news() -> None:
    disc = get_scorer().score("정기보고서 제출", NewsSourceType.DISCLOSURE, None, {})
    news = get_scorer().score("정기보고서 제출", NewsSourceType.NEWS, None, {})
    assert disc.importance > news.importance


def test_high_impact_term_raises_importance() -> None:
    plain = get_scorer().score("실적 발표", NewsSourceType.NEWS, None, {})
    impact = get_scorer().score("상장폐지 사유 발생", NewsSourceType.NEWS, None, {})
    assert impact.importance > plain.importance


def test_score_ranges_are_bounded() -> None:
    s = get_scorer().score(
        "상장폐지 횡령 배임 부도 적자전환 영업정지 거래정지", NewsSourceType.DISCLOSURE, None, {},
    )
    assert -1.0 <= s.sentiment <= 1.0
    assert 0.0 <= s.importance <= 1.0


def test_title_is_included_in_matching() -> None:
    s = get_scorer().score("본문에는 키워드 없음", NewsSourceType.NEWS, "흑자전환 신규수주", {})
    assert s.sentiment > 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_rag/test_scorer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.rag.scorer'`

- [ ] **Step 3: scorer 모듈 구현**

`src/rag/scorer.py`:
```python
"""뉴스/공시 청크의 sentiment·importance 룰베이스 스코어링.

교체 가능한 `Scorer` 추상화 — 룰베이스가 첫 구현. 향후 로컬 모델 스코어러는
같은 인터페이스로 추가하고 `get_scorer()`에 등록하면 호출부·스키마 무변경으로
전환된다. 순수·결정적이며 어떤 입력에도 예외를 던지지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from src.db.models import NewsSourceType

# 호재(+)/악재(-) 가중 키워드. 부분 문자열 매칭(한국어 금융 표현).
POSITIVE_TERMS: dict[str, float] = {
    "흑자전환": 1.0, "사상최대": 1.0, "최대실적": 1.0, "어닝서프라이즈": 1.0, "호실적": 0.8,
    "신규수주": 0.9, "공급계약": 0.8, "계약체결": 0.8, "수주": 0.6, "실적개선": 0.7,
    "자사주매입": 0.8, "자사주취득": 0.8, "배당확대": 0.7, "특허취득": 0.6,
    "임상성공": 1.0, "품목허가": 0.9, "승인": 0.5, "흑자": 0.5,
    "목표주가상향": 0.8, "투자의견상향": 0.8,
}
NEGATIVE_TERMS: dict[str, float] = {
    "적자전환": 1.0, "어닝쇼크": 1.0, "분식회계": 1.0, "부도": 1.0, "회생절차": 1.0, "상장폐지": 1.0,
    "횡령": 1.0, "배임": 1.0, "압수수색": 0.9, "영업손실": 0.8, "실적부진": 0.7, "적자": 0.6,
    "거래정지": 0.9, "영업정지": 0.9, "관리종목": 0.9, "불성실공시": 0.8, "감자": 0.8,
    "유상증자": 0.7, "리콜": 0.7, "피소": 0.6, "소송": 0.5, "전환사채": 0.4,
    "목표주가하향": 0.8, "투자의견하향": 0.8,
}
# tanh 정규화 스케일: 가중합 ≈1.5 → sentiment ≈0.66.
SENTIMENT_SCALE = 1.5

# importance source_type 기본 가중 (공시/실적 > 리포트 > 뉴스).
IMPORTANCE_BASE: dict[NewsSourceType, float] = {
    NewsSourceType.DISCLOSURE: 0.5,
    NewsSourceType.EARNINGS: 0.5,
    NewsSourceType.REPORT: 0.35,
    NewsSourceType.NEWS: 0.3,
}
_IMPORTANCE_DEFAULT = 0.3
# 방향 무관 '시장영향 크기' boost.
HIGH_IMPACT_TERMS: dict[str, float] = {
    "상장폐지": 0.5, "부도": 0.5, "회생절차": 0.5, "거래정지": 0.4, "영업정지": 0.4,
    "횡령": 0.4, "배임": 0.4, "분식회계": 0.4, "합병": 0.35, "임상성공": 0.35,
    "유상증자": 0.3, "감자": 0.3, "분할": 0.3, "최대실적": 0.3, "어닝서프라이즈": 0.3,
    "어닝쇼크": 0.3, "품목허가": 0.3, "자사주매입": 0.25,
}


@dataclass(frozen=True)
class ChunkScore:
    """스코어링 결과 + provenance. 추후 confidence/feature 필드 확장 가능."""

    sentiment: float  # [-1, 1]
    importance: float  # [0, 1]
    method: str  # 생성 스코어러 식별자 (예: "rule_v1")


class Scorer(Protocol):
    """스코어러 인터페이스 — 룰베이스/모델 구현 교체점."""

    method: str

    def score(
        self,
        text: str,
        source_type: NewsSourceType,
        title: str | None,
        metadata: dict[str, object],
    ) -> ChunkScore: ...


class RuleBasedScorer:
    """키워드 lexicon + source_type 가중 기반 룰베이스 스코어러."""

    method = "rule_v1"

    def score(
        self,
        text: str,
        source_type: NewsSourceType,
        title: str | None,
        metadata: dict[str, object],
    ) -> ChunkScore:
        try:
            return self._score(text, source_type, title)
        except Exception:  # noqa: BLE001 — 스코어링 실패가 적재를 막지 않도록 중립 폴백
            return ChunkScore(0.0, 0.0, self.method)

    def _score(
        self, text: str, source_type: NewsSourceType, title: str | None,
    ) -> ChunkScore:
        haystack = f"{title or ''} {text or ''}".strip()
        if not haystack:
            return ChunkScore(0.0, 0.0, self.method)

        pos = sum(w for term, w in POSITIVE_TERMS.items() if term in haystack)
        neg = sum(w for term, w in NEGATIVE_TERMS.items() if term in haystack)
        sentiment = math.tanh((pos - neg) / SENTIMENT_SCALE)

        base = IMPORTANCE_BASE.get(source_type, _IMPORTANCE_DEFAULT)
        boost = sum(w for term, w in HIGH_IMPACT_TERMS.items() if term in haystack)
        importance = max(0.0, min(1.0, base + boost))

        return ChunkScore(round(sentiment, 4), round(importance, 4), self.method)


_DEFAULT_SCORER: Scorer = RuleBasedScorer()


def get_scorer() -> Scorer:
    """현재 활성 스코어러를 반환. 추후 env/config로 모델 스코어러 선택 확장."""
    return _DEFAULT_SCORER
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_rag/test_scorer.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: 린트/타입 확인**

Run: `ruff check src/rag/scorer.py && python -m mypy src/rag/scorer.py`
Expected: ruff "All checks passed!", mypy 신규 에러 0

- [ ] **Step 6: 커밋**

```bash
git add src/rag/scorer.py tests/test_rag/test_scorer.py
git commit -m "feat(rag): 뉴스 청크 sentiment/importance 룰베이스 스코어러 추가"
```

---

## Task 2: 적재 경로 인라인 스코어링 (base.py)

**Files:**
- Modify: `src/worker/collectors/base.py` (`__init__` ≈66-74, `_build_new_chunks` 끝 ≈198-214)
- Test: `tests/test_worker/test_collectors/test_base.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_worker/test_collectors/test_base.py`의 `TestRunCycle` 클래스에 메서드 추가:
```python
    async def test_chunks_get_sentiment_importance_and_method(self) -> None:
        repo = _mock_repo()
        # 호재 키워드 포함 본문 → sentiment > 0
        docs = [_doc(body="삼성전자 흑자전환 신규수주 사상최대 실적")]
        collector = StubCollector(_mock_embedder(), repo, docs=docs)
        await collector.run_cycle()

        chunks = repo.insert_chunks.call_args.args[0]
        assert len(chunks) > 0
        for c in chunks:
            assert c.sentiment is not None
            assert -1.0 <= c.sentiment <= 1.0
            assert c.importance is not None
            assert 0.0 <= c.importance <= 1.0
            assert c.chunk_metadata["score_method"] == "rule_v1"
        # 호재 본문이므로 양수 sentiment
        assert chunks[0].sentiment > 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_worker/test_collectors/test_base.py::TestRunCycle::test_chunks_get_sentiment_importance_and_method -v`
Expected: FAIL — `c.sentiment is None` (현재 미설정) 또는 `KeyError: 'score_method'`

- [ ] **Step 3: base.py에 scorer 주입 + 인라인 스코어링**

`src/worker/collectors/base.py` import 블록(상단)에 추가:
```python
from src.rag.scorer import get_scorer
```
TYPE_CHECKING 블록에 추가:
```python
    from src.rag.scorer import Scorer
```

`BaseCollector.__init__` 시그니처/본문 교체:
```python
    def __init__(
        self,
        embedder: Embedder,
        repo: NewsChunkRepository,
        metric_repo: SystemMetricRepository | None = None,
        scorer: Scorer | None = None,
    ) -> None:
        self._embedder = embedder
        self._repo = repo
        self._metric_repo = metric_repo
        self._scorer = scorer or get_scorer()
```

`_build_new_chunks`의 5) NewsChunk 생성 루프(현재 `out.append(NewsChunk(...))`)를 교체:
```python
        # 5) 스코어링 + NewsChunk 생성
        out: list[NewsChunk] = []
        for (doc, chunk, content_hash), vec in zip(survivors, vectors, strict=True):
            score = self._scorer.score(
                chunk.text, doc.source_type, doc.title, doc.metadata,
            )
            out.append(NewsChunk(
                ticker=doc.ticker,
                source_type=doc.source_type,
                source_url=doc.source_url,
                source_id=doc.source_id,
                title=doc.title,
                chunk_text=chunk.text,
                chunk_index=chunk.chunk_index,
                content_hash=content_hash,
                embedding=vec.tolist(),
                event_time=doc.event_time,
                sentiment=score.sentiment,
                importance=score.importance,
                chunk_metadata={
                    "section": chunk.section,
                    "score_method": score.method,
                    **doc.metadata,
                },
            ))
        return out
```

- [ ] **Step 4: 테스트 통과 확인 (신규 + 회귀)**

Run: `pytest tests/test_worker/test_collectors/test_base.py -q`
Expected: PASS (기존 + 신규 1건 모두)

- [ ] **Step 5: 린트/타입 확인**

Run: `ruff check src/worker/collectors/base.py && python -m mypy src/worker/collectors/base.py`
Expected: ruff 통과, mypy 신규 에러 0

- [ ] **Step 6: 커밋**

```bash
git add src/worker/collectors/base.py tests/test_worker/test_collectors/test_base.py
git commit -m "feat(worker): 적재 시 청크 sentiment/importance 인라인 스코어링 + score_method 기록"
```

---

## Task 3: 리포트 집계에 avg_sentiment 추가 (analytics)

> **참고:** `get_news_quality_stats()`는 PostgreSQL 전용 SQL(`::text`, `->>`, `percentile_cont`)이라 SQLite 단위테스트가 불가하다. 따라서 이 변경은 **라이브 postgres 쿼리로 검증**한다(아래 Step 3).

**Files:**
- Modify: `src/db/analytics.py` (`get_news_quality_stats` by_source 쿼리 ≈1179-1189)

- [ ] **Step 1: by_source 쿼리에 AVG(sentiment) 추가**

`src/db/analytics.py`의 `by_source_rows` 쿼리에서 `AVG(importance) AS avg_importance` 라인 다음에 `AVG(sentiment)` 컬럼을 추가:
```python
    by_source_rows = session.execute(_text(
        "SELECT source_type::text AS source_type, "
        "       COALESCE(chunk_metadata->>'provider','-') AS provider, "
        "       COALESCE(chunk_metadata->>'category','-') AS category, "
        "       COUNT(*) AS chunks, "
        "       AVG(importance) AS avg_importance, "
        "       AVG(sentiment) AS avg_sentiment "
        "FROM news_chunks "
        "WHERE fetched_at >= :start AND fetched_at < :end "
        "GROUP BY source_type, provider, category "
        "ORDER BY chunks DESC"
    ), {"start": day_start, "end": day_end}).mappings().all()
```
docstring의 by_source 필드 설명에 `avg_sentiment`를 추가한다.

- [ ] **Step 2: 린트/타입 확인**

Run: `ruff check src/db/analytics.py && python -m mypy src/db/analytics.py`
Expected: ruff 통과, mypy 신규 에러 0 (기존 부채 외)

- [ ] **Step 3: 라이브 DB로 동작 검증 (Task 2·4 적용 후 실행)**

> 이 검증은 백필(Task 4) 실행 후에 의미가 있다. 먼저 백필을 돌리고 워커를 재시작한 뒤 실행.

Run:
```bash
docker exec kis-postgres psql -U kis_user -d kis_trader -c \
"SELECT source_type, AVG(importance) imp, AVG(sentiment) sen, COUNT(*) FROM news_chunks GROUP BY source_type;"
```
Expected: `imp`/`sen` 컬럼이 NULL이 아닌 평균값 반환.

- [ ] **Step 4: 커밋**

```bash
git add src/db/analytics.py
git commit -m "feat(db): get_news_quality_stats에 avg_sentiment 추가"
```

---

## Task 4: 기존 청크 백필 스크립트

**Files:**
- Create: `scripts/backfill_news_scores.py`
- Test: `tests/test_db/test_backfill_news_scores.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_db/test_backfill_news_scores.py`:
```python
"""backfill_news_scores 동작/idempotency 테스트 (SQLite in-memory)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, NewsChunk, NewsSourceType
from scripts.backfill_news_scores import backfill_scores


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        def visit_jsonb(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "JSON"
        SQLiteTypeCompiler.visit_JSONB = visit_jsonb  # type: ignore[attr-defined]
    if not hasattr(SQLiteTypeCompiler, "visit_VECTOR"):
        def visit_vector(self, type_, **kw):  # type: ignore[no-untyped-def]
            return "TEXT"
        SQLiteTypeCompiler.visit_VECTOR = visit_vector  # type: ignore[attr-defined]

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def _chunk(hash_seed: str, body: str) -> NewsChunk:
    return NewsChunk(
        ticker="005930",
        source_type=NewsSourceType.NEWS,
        source_id=hash_seed,
        chunk_text=body,
        chunk_index=0,
        content_hash=(hash_seed * 64)[:64],
        embedding=[0.0] * 1024,
        event_time=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
    )


def test_backfill_fills_null_scores(session: Session) -> None:
    session.add(_chunk("a", "흑자전환 신규수주"))
    session.add(_chunk("b", "정기 주주총회 개최"))
    session.commit()

    updated = backfill_scores(session, batch_size=10)
    assert updated == 2

    rows = session.execute(select(NewsChunk)).scalars().all()
    for r in rows:
        assert r.sentiment is not None
        assert r.importance is not None
        assert r.chunk_metadata["score_method"] == "rule_v1"


def test_backfill_is_idempotent(session: Session) -> None:
    session.add(_chunk("a", "흑자전환"))
    session.commit()
    assert backfill_scores(session, batch_size=10) == 1
    # 재실행 시 NULL이 없으므로 0건
    assert backfill_scores(session, batch_size=10) == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_db/test_backfill_news_scores.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_news_scores'`

- [ ] **Step 3: 백필 스크립트 구현**

`scripts/backfill_news_scores.py`:
```python
"""기존 news_chunks 중 sentiment NULL인 청크를 룰베이스 스코어러로 백필.

배치별 commit으로 단일 kis-postgres 락 점유를 최소화한다(2026-05-20 락 고갈
사고 교훈). idempotent — 이미 채워진 청크는 sentiment IS NULL 필터로 제외된다.

실행:
    .venv/bin/python scripts/backfill_news_scores.py
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import NewsChunk
from src.db.session import get_session
from src.rag.scorer import get_scorer
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def backfill_scores(session: Session, batch_size: int = 500) -> int:
    """sentiment NULL 청크를 배치로 스코어링·UPDATE. 채운 총 건수 반환."""
    scorer = get_scorer()
    total = 0
    while True:
        rows = session.execute(
            select(NewsChunk)
            .where(NewsChunk.sentiment.is_(None))
            .limit(batch_size)
        ).scalars().all()
        if not rows:
            break
        for chunk in rows:
            score = scorer.score(
                chunk.chunk_text,
                chunk.source_type,
                chunk.title,
                chunk.chunk_metadata or {},
            )
            chunk.sentiment = score.sentiment
            chunk.importance = score.importance
            # JSONB 변경 감지를 위해 dict 재할당.
            chunk.chunk_metadata = {
                **(chunk.chunk_metadata or {}),
                "score_method": score.method,
            }
        session.commit()
        total += len(rows)
        logger.info("백필 진행: 누적 %d건", total)
    return total


def main() -> int:
    with get_session() as session:
        total = backfill_scores(session)
    logger.info("백필 완료: 총 %d건", total)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_db/test_backfill_news_scores.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 린트/타입 확인**

Run: `ruff check scripts/backfill_news_scores.py && python -m mypy scripts/backfill_news_scores.py`
Expected: ruff 통과, mypy 신규 에러 0

- [ ] **Step 6: 커밋**

```bash
git add scripts/backfill_news_scores.py tests/test_db/test_backfill_news_scores.py
git commit -m "feat(scripts): 기존 news_chunks sentiment/importance 백필 스크립트"
```

---

## Task 5: 전체 검증 + 백필 실행 + 운영 반영 + 문서

**Files:**
- Modify: `pyproject.toml`, `src/__version__.py` (버전 범프), `docs/CHANGELOG.md`

- [ ] **Step 1: 전체 회귀 테스트**

Run: `pytest tests/test_rag/ tests/test_worker/ tests/test_db/ -q`
Expected: 전부 PASS, 회귀 0

- [ ] **Step 2: 전체 린트/타입**

Run: `ruff check src/ scripts/ && python -m mypy src/rag/scorer.py src/worker/collectors/base.py src/db/analytics.py scripts/backfill_news_scores.py`
Expected: ruff 통과, mypy 신규 에러 0

- [ ] **Step 3: 버전 범프**

`pyproject.toml`의 `version`과 `src/__version__.py`의 `__version__`을 현재값에서 patch +1 (예: `0.2.12` → `0.2.13`).

- [ ] **Step 4: 백필 실행 (운영 DB)**

> DB 쓰기 작업. 실행 전 현재 NULL 건수 확인.

Run:
```bash
docker exec kis-postgres psql -U kis_user -d kis_trader -c \
"SELECT count(*) FROM news_chunks WHERE sentiment IS NULL;"
.venv/bin/python scripts/backfill_news_scores.py
docker exec kis-postgres psql -U kis_user -d kis_trader -c \
"SELECT count(*) FILTER (WHERE sentiment IS NULL) null_cnt, count(*) total FROM news_chunks;"
```
Expected: 백필 후 `null_cnt` = 0.

- [ ] **Step 5: Task 3 라이브 검증 + 워커 재시작 (사용자에게 명령 제시)**

신규 적재분에 점수가 붙는지 확인하려면 워커 재시작 필요. 직접 실행하지 말고 사용자에게 제시:
```
! launchctl kickstart -k gui/$(id -u)/com.kis.news-collector
```
재시작 후 라이브 검증:
```bash
docker exec kis-postgres psql -U kis_user -d kis_trader -c \
"SELECT source_type, AVG(importance) imp, AVG(sentiment) sen, count(*) FROM news_chunks GROUP BY source_type;"
```
Expected: `imp`/`sen` 비-NULL, 신규 청크의 `chunk_metadata->>'score_method'` = `rule_v1`.

- [ ] **Step 6: 구현 이력 + CHANGELOG**

Run: `python scripts/record_implementation.py --help` 로 인자 확인 후 본 변경을 DB에 기록하고, `docs/CHANGELOG.md`를 최근 5건 rolling으로 갱신(가장 오래된 항목 제거, 본 항목 추가).

- [ ] **Step 7: 최종 커밋**

```bash
git add pyproject.toml src/__version__.py docs/CHANGELOG.md
git commit -m "chore: 뉴스 스코어링 버전 범프 + CHANGELOG rolling (vX.Y.Z)"
```

---

## Self-Review 결과

- **Spec 커버리지:** §3.1 스코어러 추상화→Task1, §3.2 로직→Task1, §3.3 인라인 적재→Task2, §3.4 백필→Task4, §3.5 avg_sentiment→Task3, §6 테스트→각 Task, §7 수용기준→Task5. 전 항목 매핑됨.
- **Placeholder:** 없음 — 모든 코드/명령 구체화. lexicon 가중치는 실제 값으로 채움.
- **타입 일관성:** `ChunkScore(sentiment, importance, method)`, `Scorer.score(text, source_type, title, metadata)`, `get_scorer()`, `backfill_scores(session, batch_size)` — Task 전반 시그니처 일치.
- **알려진 제약:** Task 3 analytics는 PG 전용 SQL이라 sqlite 단위테스트 대신 라이브 검증(Step 3/5). 향후 매매 전략 연결·로컬 모델·retriever는 범위 밖(설계서 §8/§9).
