"""add_trajectory_entries_and_prediction

Revision ID: 9374c8f9c742
Revises: ecdd397b8238
Create Date: 2026-05-18 22:33:31.461227

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9374c8f9c742"
down_revision: str | None = "ecdd397b8238"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """trajectory_entries 테이블 + proposals.prediction 컬럼 추가."""
    op.create_table(
        "trajectory_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cycle_id", sa.String(length=64), nullable=False),
        sa.Column(
            "step",
            sa.Enum(
                "INITIALIZER",
                "VALIDATOR",
                "IMPLEMENTER",
                "VERIFIER",
                "EVALUATOR",
                "RECORDER",
                "ROLLBACK",
                name="trajectory_step_enum",
            ),
            nullable=False,
        ),
        sa.Column("proposal_path", sa.String(length=300), nullable=True),
        sa.Column("agent", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            sa.Enum("OK", "FAIL", "SKIP", name="trajectory_status_enum"),
            nullable=False,
        ),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("token_usage_input", sa.Integer(), nullable=True),
        sa.Column("token_usage_output", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_trajectory_entries_cycle_id"),
        "trajectory_entries",
        ["cycle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trajectory_entries_started_at"),
        "trajectory_entries",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trajectory_entries_step"),
        "trajectory_entries",
        ["step"],
        unique=False,
    )
    op.add_column(
        "proposals",
        sa.Column(
            "prediction",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """trajectory_entries 테이블 + proposals.prediction 컬럼 + 신규 enum 제거."""
    op.drop_column("proposals", "prediction")
    op.drop_index(
        op.f("ix_trajectory_entries_step"),
        table_name="trajectory_entries",
    )
    op.drop_index(
        op.f("ix_trajectory_entries_started_at"),
        table_name="trajectory_entries",
    )
    op.drop_index(
        op.f("ix_trajectory_entries_cycle_id"),
        table_name="trajectory_entries",
    )
    op.drop_table("trajectory_entries")
    # 신규 enum drop (기존 enum은 유지)
    sa.Enum(name="trajectory_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="trajectory_step_enum").drop(op.get_bind(), checkfirst=True)
