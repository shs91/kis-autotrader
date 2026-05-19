"""add market_actions table

Revision ID: 4ea33aed4c86
Revises: 66bf764a73f8
Create Date: 2026-05-19 11:39:02.444229

종목별 시장조치 상태 — KIS 종목마스터 일일 sync 결과 저장.
매매 엔진의 매수 직전 차단 lookup용.

참고: autogen이 함께 잡은 HNSW/GIN/task_queue_poll drop은 표현식·partial
인덱스 비교 오감지라 모두 제거.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4ea33aed4c86"
down_revision: str | None = "66bf764a73f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_actions",
        sa.Column("stock_code", sa.String(length=10), nullable=False),
        sa.Column(
            "is_trading_halted", sa.Boolean(),
            server_default="false", nullable=False,
        ),
        sa.Column(
            "is_administrative", sa.Boolean(),
            server_default="false", nullable=False,
        ),
        sa.Column(
            "is_liquidation", sa.Boolean(),
            server_default="false", nullable=False,
        ),
        sa.Column(
            "is_market_warning", sa.Boolean(),
            server_default="false", nullable=False,
        ),
        sa.Column(
            "is_warning_pretrigger", sa.Boolean(),
            server_default="false", nullable=False,
        ),
        sa.Column(
            "is_dishonest_disclosure", sa.Boolean(),
            server_default="false", nullable=False,
        ),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("stock_code"),
    )


def downgrade() -> None:
    op.drop_table("market_actions")
