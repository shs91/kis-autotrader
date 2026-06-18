"""add market column + composite unique to daily_summary/daily_performances (P3c #4)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-18

멀티마켓 결산 격리: KRX/US 분리 프로세스가 같은 날짜 결산 행을 덮어쓰지 않도록
market 컬럼 추가 + 유일성을 (날짜, 시장) 복합으로 변경. 기존 행은 server_default로
KRX 백필(과거 US 오염 행도 KRX 라벨 — 데이터 백필은 별도 운영자 판단).
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # daily_summary: report_date 단일 unique → (report_date, market) 복합 unique
    op.add_column(
        "daily_summary",
        sa.Column(
            "market", sa.String(length=10), nullable=False, server_default="KRX"
        ),
    )
    op.drop_index("ix_daily_summary_report_date", table_name="daily_summary")
    op.create_index(
        "ix_daily_summary_report_date", "daily_summary", ["report_date"]
    )
    op.create_index("ix_daily_summary_market", "daily_summary", ["market"])
    op.create_unique_constraint(
        "uq_daily_summary_date_market", "daily_summary", ["report_date", "market"]
    )

    # daily_performances: date 단일 unique → (date, market) 복합 unique
    op.add_column(
        "daily_performances",
        sa.Column(
            "market", sa.String(length=10), nullable=False, server_default="KRX"
        ),
    )
    op.drop_index("ix_daily_performances_date", table_name="daily_performances")
    op.create_index(
        "ix_daily_performances_date", "daily_performances", ["date"]
    )
    op.create_index(
        "ix_daily_performances_market", "daily_performances", ["market"]
    )
    op.create_unique_constraint(
        "uq_daily_perf_date_market", "daily_performances", ["date", "market"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_daily_perf_date_market", "daily_performances", type_="unique"
    )
    op.drop_index("ix_daily_performances_market", table_name="daily_performances")
    op.drop_index("ix_daily_performances_date", table_name="daily_performances")
    op.create_index(
        "ix_daily_performances_date", "daily_performances", ["date"], unique=True
    )
    op.drop_column("daily_performances", "market")

    op.drop_constraint(
        "uq_daily_summary_date_market", "daily_summary", type_="unique"
    )
    op.drop_index("ix_daily_summary_market", table_name="daily_summary")
    op.drop_index("ix_daily_summary_report_date", table_name="daily_summary")
    op.create_index(
        "ix_daily_summary_report_date", "daily_summary", ["report_date"], unique=True
    )
    op.drop_column("daily_summary", "market")
