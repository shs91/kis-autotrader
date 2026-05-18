"""add_proposals_table

Revision ID: ecdd397b8238
Revises: edb0690663bb
Create Date: 2026-05-14 19:30:29.638695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ecdd397b8238'
down_revision: Union[str, None] = 'edb0690663bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 신규 enum 정의 (proposals 전용). impl_category_enum 은 기존 type 재사용.
proposal_state_enum = postgresql.ENUM(
    'DRAFT',
    'READY',
    'IN_FLIGHT',
    'IMPLEMENTED',
    'FAILED',
    'SKIPPED',
    'REVIEW_REQUIRED',
    name='proposal_state_enum',
)
proposal_priority_enum = postgresql.ENUM(
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL',
    name='proposal_priority_enum',
)
# 기존 type 재사용 — CREATE TYPE 발생시키지 말 것 (create_type=False).
impl_category_enum_existing = postgresql.ENUM(
    'BUG_FIX',
    'REFACTOR',
    'PARAM_TUNING',
    'FEATURE',
    'ENHANCEMENT',
    'PERFORMANCE',
    'DOCS',
    'CONFIG',
    name='impl_category_enum',
    create_type=False,
)


def upgrade() -> None:
    # 신규 enum 2종(proposal_state_enum, proposal_priority_enum)은
    # create_table 안에서 SQLAlchemy가 자동으로 CREATE TYPE 한다.
    # impl_category_enum 은 create_type=False 로 재사용한다.
    op.create_table(
        'proposals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('path', sa.String(length=300), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('category', impl_category_enum_existing, nullable=False),
        sa.Column('state', proposal_state_enum, nullable=False),
        sa.Column('priority', proposal_priority_enum, nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('skip_reason', sa.String(length=100), nullable=True),
        sa.Column('cycle_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path', name='uq_proposals_path'),
    )
    op.create_index('ix_proposals_state', 'proposals', ['state'], unique=False)
    op.create_index('ix_proposals_cycle_id', 'proposals', ['cycle_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index('ix_proposals_cycle_id', table_name='proposals')
    op.drop_index('ix_proposals_state', table_name='proposals')
    op.drop_table('proposals')

    # impl_category_enum 은 다른 테이블(implementation_logs)에서 사용 중이므로 drop 금지.
    # 신규 enum 2종만 drop.
    proposal_priority_enum.drop(bind, checkfirst=True)
    proposal_state_enum.drop(bind, checkfirst=True)
