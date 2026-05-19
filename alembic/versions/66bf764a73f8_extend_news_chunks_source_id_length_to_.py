"""extend news_chunks source_id length to 512

Revision ID: 66bf764a73f8
Revises: 84febb2fdc0a
Create Date: 2026-05-19 11:02:04.354895

source_id가 RSS guid(기사 URL을 그대로 사용하는 경우)를 담을 수 있도록 확장:
- news_chunks.source_id / corr_source_id: varchar(64) → varchar(512)
- news_collection_state.last_cursor: 동일

참고: autogen이 함께 잡아낸 HNSW/GIN/task_queue_poll drop은 오감지(파셜·표현식
인덱스 비교 한계)라 모두 제거했다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "66bf764a73f8"
down_revision: str | None = "84febb2fdc0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "news_chunks", "source_id",
        existing_type=sa.VARCHAR(length=64),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
    op.alter_column(
        "news_chunks", "corr_source_id",
        existing_type=sa.VARCHAR(length=64),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
    op.alter_column(
        "news_collection_state", "last_cursor",
        existing_type=sa.VARCHAR(length=64),
        type_=sa.String(length=512),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "news_collection_state", "last_cursor",
        existing_type=sa.String(length=512),
        type_=sa.VARCHAR(length=64),
        existing_nullable=True,
    )
    op.alter_column(
        "news_chunks", "corr_source_id",
        existing_type=sa.String(length=512),
        type_=sa.VARCHAR(length=64),
        existing_nullable=True,
    )
    op.alter_column(
        "news_chunks", "source_id",
        existing_type=sa.String(length=512),
        type_=sa.VARCHAR(length=64),
        existing_nullable=True,
    )
