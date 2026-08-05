"""add catalog ratings

Revision ID: 004
Revises: 003
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("shops", "products"):
        existing = {column["name"] for column in inspector.get_columns(table)}
        if "rating_average" not in existing:
            op.add_column(
                table,
                sa.Column("rating_average", sa.Numeric(3, 2), nullable=False, server_default="0"),
            )
        if "rating_count" not in existing:
            op.add_column(
                table,
                sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("products", "shops"):
        existing = {column["name"] for column in inspector.get_columns(table)}
        if "rating_count" in existing:
            op.drop_column(table, "rating_count")
        if "rating_average" in existing:
            op.drop_column(table, "rating_average")
