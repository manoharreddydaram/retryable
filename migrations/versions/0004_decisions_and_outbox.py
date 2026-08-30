"""decisions, outbox_entries, circuit_breaker_state: Stage 5 execution tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id", sa.String(length=128), sa.ForeignKey("payments.order_id"), nullable=False
        ),
        sa.Column("payer_contact", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("proposed_intervention", sa.String(length=64), nullable=False),
        sa.Column("authorized_intervention", sa.String(length=32), nullable=False),
        sa.Column("overridden", sa.Boolean(), nullable=False),
        sa.Column("rule_id", sa.String(length=48), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decisions_order_id", "decisions", ["order_id"])
    op.create_index("ix_decisions_payer_contact", "decisions", ["payer_contact"])

    op.create_table(
        "outbox_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(length=40), nullable=False, unique=True),
        sa.Column("intervention", sa.String(length=32), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("razorpay_payment_link_id", sa.String(length=64), nullable=True),
        sa.Column("razorpay_short_url", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_outbox_entries_pending_ready", "outbox_entries", ["status", "next_attempt_at"]
    )

    op.create_table(
        "circuit_breaker_state",
        sa.Column("service", sa.String(length=32), primary_key=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="closed"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("circuit_breaker_state")
    op.drop_index("ix_outbox_entries_pending_ready", table_name="outbox_entries")
    op.drop_table("outbox_entries")
    op.drop_index("ix_decisions_payer_contact", table_name="decisions")
    op.drop_index("ix_decisions_order_id", table_name="decisions")
    op.drop_table("decisions")
