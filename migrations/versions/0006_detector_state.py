"""detector_baselines and detector_runs tables: Stage 8

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "detector_baselines",
        sa.Column("cohort", sa.String(length=64), primary_key=True),
        sa.Column("ewma_rate", sa.Float(), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "detector_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cohort", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_count", sa.BigInteger(), nullable=False),
        sa.Column("total_count", sa.BigInteger(), nullable=False),
        sa.Column("observed_rate", sa.Float(), nullable=False),
        sa.Column("baseline_rate", sa.Float(), nullable=False),
        sa.Column("probability_degraded", sa.Float(), nullable=True),
        sa.Column("fired", sa.Boolean(), nullable=False),
        sa.Column("suppressed_reason", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_detector_runs_cohort", "detector_runs", ["cohort"])


def downgrade() -> None:
    op.drop_index("ix_detector_runs_cohort", table_name="detector_runs")
    op.drop_table("detector_runs")
    op.drop_table("detector_baselines")
