"""payments: add classification fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column("payments", sa.Column("error_reason", sa.String(length=64), nullable=True))
    op.add_column("payments", sa.Column("category", sa.String(length=48), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "category")
    op.drop_column("payments", "error_reason")
    op.drop_column("payments", "error_code")
