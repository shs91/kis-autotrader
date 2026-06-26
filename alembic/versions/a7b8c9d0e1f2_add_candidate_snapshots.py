"""add candidate_snapshots table

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-26 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=20), nullable=False),
        sa.Column("market", sa.String(length=10), server_default="KRX", nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("ensemble_action", sa.String(length=8), nullable=False),
        sa.Column(
            "ensemble_confidence", sa.Numeric(precision=6, scale=4), nullable=False
        ),
        sa.Column("ensemble_reason", sa.String(length=200), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_snapshots_code_time",
        "candidate_snapshots",
        ["stock_code", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_snapshots_captured_at",
        "candidate_snapshots",
        ["captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_snapshots_captured_at", table_name="candidate_snapshots"
    )
    op.drop_index("ix_candidate_snapshots_code_time", table_name="candidate_snapshots")
    op.drop_table("candidate_snapshots")
