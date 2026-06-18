"""add SellReason BREAKEVEN/STAGNATION (v0.16.0 청산 사유)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-17

수정(2026-06-18): 본 마이그가 Numeric 마이그와 동일한 revision ID(c3d4e5f6a7b8)를
잘못 사용해 alembic head가 갈라지던 사전존재 결함을 해소한다. revision을 고유
ID(d4e5f6a7b8c9)로, down_revision을 실제 선행(Numeric c3d4e5f6a7b8)으로 교정한다.
ADD VALUE IF NOT EXISTS라 라이브 DB(이미 적용)에서 재실행해도 no-op.

"""
from __future__ import annotations

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
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
