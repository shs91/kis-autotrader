"""add market and currency columns for multi-market support

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-17

미국 주식 확장(P3b): trades/portfolios/signals/screening_results에 market 컬럼,
trades/portfolios에 currency 컬럼을 추가한다. 기존 행은 server_default로
KRX/KRW로 백필된다(비파괴적). 가격(price) 타입 전환은 별도 마이그레이션에서 다룬다.
"""

import sqlalchemy as sa

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("market", sa.String(length=10), nullable=False, server_default="KRX"),
    )
    op.add_column(
        "trades",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KRW"),
    )
    op.create_index("ix_trades_market", "trades", ["market"])

    op.add_column(
        "portfolios",
        sa.Column("market", sa.String(length=10), nullable=False, server_default="KRX"),
    )
    op.add_column(
        "portfolios",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KRW"),
    )
    op.create_index("ix_portfolios_market", "portfolios", ["market"])

    op.add_column(
        "signals",
        sa.Column("market", sa.String(length=10), nullable=False, server_default="KRX"),
    )
    op.create_index("ix_signals_market", "signals", ["market"])

    op.add_column(
        "screening_results",
        sa.Column("market", sa.String(length=10), nullable=False, server_default="KRX"),
    )
    op.create_index("ix_screening_results_market", "screening_results", ["market"])


def downgrade() -> None:
    op.drop_index("ix_screening_results_market", table_name="screening_results")
    op.drop_column("screening_results", "market")

    op.drop_index("ix_signals_market", table_name="signals")
    op.drop_column("signals", "market")

    op.drop_index("ix_portfolios_market", table_name="portfolios")
    op.drop_column("portfolios", "currency")
    op.drop_column("portfolios", "market")

    op.drop_index("ix_trades_market", table_name="trades")
    op.drop_column("trades", "currency")
    op.drop_column("trades", "market")
