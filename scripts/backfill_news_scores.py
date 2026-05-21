"""기존 news_chunks 중 sentiment NULL인 청크를 룰베이스 스코어러로 백필.

배치별 commit으로 단일 kis-postgres 락 점유를 최소화한다(2026-05-20 락 고갈
사고 교훈). idempotent — 이미 채워진 청크는 sentiment IS NULL 필터로 제외된다.

실행:
    .venv/bin/python scripts/backfill_news_scores.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.db.models import NewsChunk  # noqa: E402
from src.db.session import get_session  # noqa: E402
from src.rag.scorer import get_scorer  # noqa: E402
from src.utils.logger import setup_logger  # noqa: E402

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
    """엔트리포인트 — 전체 DB를 대상으로 백필 실행."""
    with get_session() as session:
        total = backfill_scores(session)
    logger.info("백필 완료: 총 %d건", total)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
