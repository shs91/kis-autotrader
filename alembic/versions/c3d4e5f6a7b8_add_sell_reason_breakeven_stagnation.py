"""add SellReason BREAKEVEN/STAGNATION (v0.16.0 청산 사유)

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-06-17

"""
from __future__ import annotations

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # v0.16.0 본전 스톱·정체 청산의 sell_reason. 엔진 매핑 누락으로 NULL 기록되던 것을 정합화.
    # PG enum 값 추가는 트랜잭션 밖에서 수행 (ALTER TYPE ... ADD VALUE 제약)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sell_reason_enum ADD VALUE IF NOT EXISTS 'BREAKEVEN'")
        op.execute("ALTER TYPE sell_reason_enum ADD VALUE IF NOT EXISTS 'STAGNATION'")


def downgrade() -> None:
    # PG enum 값 제거는 비가역(라벨 삭제 미지원) — no-op
    pass
