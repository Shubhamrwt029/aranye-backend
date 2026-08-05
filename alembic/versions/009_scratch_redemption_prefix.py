"""add scratch-card redemption code prefix

Revision ID: 009
Revises: 008
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scratch_cards",
        sa.Column("redemption_code_prefix", sa.String(length=12), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scratch_cards", "redemption_code_prefix")
