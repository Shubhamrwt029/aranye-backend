"""add dynamic category display ordering

Revision ID: 007
Revises: 006
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("categories")}
    if "sort_order" not in existing_columns:
        op.add_column(
            "categories",
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes("categories")}
    if "ix_categories_sort_order" not in existing_indexes:
        op.create_index("ix_categories_sort_order", "categories", ["sort_order"])


def downgrade() -> None:
    op.drop_index("ix_categories_sort_order", table_name="categories")
    op.drop_column("categories", "sort_order")
