"""diagnoses table, decisions.diagnosis_id, payments.payer_contact: Stage 7

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("payer_contact", sa.String(length=32), nullable=True))

    op.create_table(
        "diagnoses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id", sa.String(length=128), sa.ForeignKey("payments.order_id"), nullable=False
        ),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("evidence_bundle", postgresql.JSONB(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=48), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.String(length=2048), nullable=True),
        sa.Column("cited_evidence_ids", postgresql.JSONB(), nullable=True),
        sa.Column("suggested_intervention", sa.String(length=32), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_diagnoses_order_id", "diagnoses", ["order_id"])

    op.add_column(
        "decisions",
        sa.Column(
            "diagnosis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("diagnoses.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("decisions", "diagnosis_id")
    op.drop_index("ix_diagnoses_order_id", table_name="diagnoses")
    op.drop_table("diagnoses")
    op.drop_column("payments", "payer_contact")
