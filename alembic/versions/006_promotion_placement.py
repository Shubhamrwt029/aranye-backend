"""separate hero and offer promotions

Revision ID: 006
Revises: 005
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "promotions",
        sa.Column("placement", sa.String(20), nullable=False, server_default="hero"),
    )
    op.create_index("ix_promotions_placement", "promotions", ["placement"])


def downgrade() -> None:
    op.drop_index("ix_promotions_placement", table_name="promotions")
    op.drop_column("promotions", "placement")
