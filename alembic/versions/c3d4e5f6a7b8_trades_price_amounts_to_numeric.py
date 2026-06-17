"""convert trades price/total_amount/profit_loss_amount to Numeric(18,4)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-17

미국 주식 확장(P3c-3): trades.price / total_amount / profit_loss_amount를
Integer → Numeric(18,4)로 전환한다. KRX 정수값은 무손실(.0000), US는 센트까지
정밀 저장된다. 기존 행은 USING 캐스트로 무손실 변환(정수 → numeric)된다.

비파괴적: 컬럼 타입만 확장(값/제약 불변). 가격 컬럼은 비범위였던 P3b 마이그
(b2c3d4e5f6a7) 주석에서 예고된 후속 마이그레이션이다. 운영자 액션 필요
(alembic upgrade head) — 별도 PR로 분리.
"""

import sqlalchemy as sa

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

_NUMERIC = sa.Numeric(18, 4)


def upgrade() -> None:
    # NOT NULL 컬럼 — 정수 → numeric(18,4) 무손실 캐스트.
    op.alter_column(
        "trades",
        "price",
        type_=_NUMERIC,
        existing_type=sa.Integer(),
        existing_nullable=False,
        postgresql_using="price::numeric(18,4)",
    )
    op.alter_column(
        "trades",
        "total_amount",
        type_=_NUMERIC,
        existing_type=sa.Integer(),
        existing_nullable=False,
        postgresql_using="total_amount::numeric(18,4)",
    )
    # nullable 컬럼.
    op.alter_column(
        "trades",
        "profit_loss_amount",
        type_=_NUMERIC,
        existing_type=sa.Integer(),
        existing_nullable=True,
        postgresql_using="profit_loss_amount::numeric(18,4)",
    )


def downgrade() -> None:
    # numeric → integer 되돌림. 소수(US 센트)는 round로 정수화(국내 정수는 항등).
    op.alter_column(
        "trades",
        "profit_loss_amount",
        type_=sa.Integer(),
        existing_type=_NUMERIC,
        existing_nullable=True,
        postgresql_using="round(profit_loss_amount)::integer",
    )
    op.alter_column(
        "trades",
        "total_amount",
        type_=sa.Integer(),
        existing_type=_NUMERIC,
        existing_nullable=False,
        postgresql_using="round(total_amount)::integer",
    )
    op.alter_column(
        "trades",
        "price",
        type_=sa.Integer(),
        existing_type=_NUMERIC,
        existing_nullable=False,
        postgresql_using="round(price)::integer",
    )
