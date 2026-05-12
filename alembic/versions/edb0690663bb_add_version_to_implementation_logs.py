"""add version to implementation_logs

Revision ID: edb0690663bb
Revises: dcad1efe8855
Create Date: 2026-05-12 13:07:09.347479

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'edb0690663bb'
down_revision: Union[str, None] = 'dcad1efe8855'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'implementation_logs',
        sa.Column('version', sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('implementation_logs', 'version')
