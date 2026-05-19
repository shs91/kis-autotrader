"""add news_chunks and collection_state

Revision ID: 84febb2fdc0a
Revises: 9374c8f9c742
Create Date: 2026-05-19 08:51:05.848551

데이터 수집 파이프라인의 RAG 컨텍스트 저장소.
- pgvector extension 활성화
- news_chunks: 청크 + 1024-dim 임베딩 + HNSW + GIN 전문검색
- news_collection_state: 증분 수집 cursor 추적

참고: 자동 생성된 ix_task_queue_poll drop은 partial index 비교 오감지라 제거함.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "84febb2fdc0a"
down_revision: str | None = "9374c8f9c742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector extension 활성화 (CREATE TABLE에서 Vector 컬럼 쓰기 위해 선행)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "news_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "DISCLOSURE", "NEWS", "EARNINGS", "REPORT",
                name="news_source_type",
            ),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("corr_source_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sentiment", sa.Float(), nullable=True),
        sa.Column("importance", sa.Float(), nullable=True),
        sa.Column(
            "chunk_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker", "content_hash", name="uq_news_chunks_ticker_hash"
        ),
    )
    op.create_index(
        op.f("ix_news_chunks_content_hash"), "news_chunks", ["content_hash"]
    )
    op.create_index(
        op.f("ix_news_chunks_corr_source_id"), "news_chunks", ["corr_source_id"]
    )
    op.create_index(
        op.f("ix_news_chunks_event_time"), "news_chunks", ["event_time"]
    )
    op.create_index(
        op.f("ix_news_chunks_source_id"), "news_chunks", ["source_id"]
    )
    op.create_index(
        op.f("ix_news_chunks_source_type"), "news_chunks", ["source_type"]
    )
    op.create_index(op.f("ix_news_chunks_ticker"), "news_chunks", ["ticker"])

    # HNSW 벡터 유사도 인덱스 (cosine). m=16, ef_construction=64는 일반적 default.
    op.create_index(
        "idx_news_chunks_embedding_hnsw",
        "news_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # GIN 전문검색 인덱스 (title + chunk_text). 한국어 형태소는 별도 도입 시 simple → korean.
    op.execute(
        "CREATE INDEX idx_news_chunks_fts ON news_chunks USING GIN "
        "(to_tsvector('simple', COALESCE(title, '') || ' ' || chunk_text))"
    )

    op.create_table(
        "news_collection_state",
        sa.Column("source_name", sa.String(length=50), nullable=False),
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_cursor", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_name"),
    )


def downgrade() -> None:
    op.drop_table("news_collection_state")
    op.execute("DROP INDEX IF EXISTS idx_news_chunks_fts")
    op.drop_index("idx_news_chunks_embedding_hnsw", table_name="news_chunks")
    op.drop_index(op.f("ix_news_chunks_ticker"), table_name="news_chunks")
    op.drop_index(op.f("ix_news_chunks_source_type"), table_name="news_chunks")
    op.drop_index(op.f("ix_news_chunks_source_id"), table_name="news_chunks")
    op.drop_index(op.f("ix_news_chunks_event_time"), table_name="news_chunks")
    op.drop_index(op.f("ix_news_chunks_corr_source_id"), table_name="news_chunks")
    op.drop_index(op.f("ix_news_chunks_content_hash"), table_name="news_chunks")
    op.drop_table("news_chunks")
    postgresql.ENUM(name="news_source_type").drop(op.get_bind(), checkfirst=True)
    # extension은 다른 향후 테이블에서 쓰일 수 있어 downgrade에서 DROP EXTENSION 하지 않는다.
