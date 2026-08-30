"""ledger_entries: append-only, hash-chained audit log

Revision ID: 0001
Revises:
Create Date: 2026-08-30

The database itself enforces append-only: the two triggers below raise on
any UPDATE or DELETE, so the guarantee does not depend on every future
caller of this table behaving correctly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_entries",
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("this_hash", sa.String(length=64), nullable=False, unique=True),
    )
    op.create_index("ix_ledger_entries_entity", "ledger_entries", ["entity_type", "entity_id"])

    op.execute("""
        CREATE OR REPLACE FUNCTION ledger_entries_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ledger_entries is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER ledger_entries_no_update
        BEFORE UPDATE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION ledger_entries_immutable();
    """)
    op.execute("""
        CREATE TRIGGER ledger_entries_no_delete
        BEFORE DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION ledger_entries_immutable();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_no_delete ON ledger_entries")
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_no_update ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS ledger_entries_immutable()")
    op.drop_index("ix_ledger_entries_entity", table_name="ledger_entries")
    op.drop_table("ledger_entries")
