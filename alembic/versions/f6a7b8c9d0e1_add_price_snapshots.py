"""add price_snapshots table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-19 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=10), server_default="KRX", nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="KRW", nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_snapshots_code_time",
        "price_snapshots",
        ["stock_code", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_price_snapshots_time",
        "price_snapshots",
        ["captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_price_snapshots_time", table_name="price_snapshots")
    op.drop_index("ix_price_snapshots_code_time", table_name="price_snapshots")
    op.drop_table("price_snapshots")
