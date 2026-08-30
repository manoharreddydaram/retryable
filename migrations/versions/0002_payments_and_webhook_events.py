"""payments and webhook_events: Stage 2 ingest tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("order_id", sa.String(length=128), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("latest_payment_id", sa.String(length=128), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "webhook_events",
        sa.Column("event_id", sa.String(length=128), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payment_id", sa.String(length=128), nullable=True),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhook_events_order_id", "webhook_events", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_events_order_id", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_table("payments")
