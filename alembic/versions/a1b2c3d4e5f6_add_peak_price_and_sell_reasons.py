"""add portfolios.peak_price and SellReason TRAILING_STOP/MARKET_CLOSE

Revision ID: a1b2c3d4e5f6
Revises: 4ea33aed4c86
Create Date: 2026-05-22

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "4ea33aed4c86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolios",
        sa.Column("peak_price", sa.Float(), nullable=True),
    )
    # PG enum 값 추가는 트랜잭션 밖에서 수행 (ALTER TYPE ... ADD VALUE 제약)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sell_reason_enum ADD VALUE IF NOT EXISTS 'TRAILING_STOP'")
        op.execute("ALTER TYPE sell_reason_enum ADD VALUE IF NOT EXISTS 'MARKET_CLOSE'")


def downgrade() -> None:
    op.drop_column("portfolios", "peak_price")
    # PG enum 값 제거는 비가역(라벨 삭제 미지원) — no-op
