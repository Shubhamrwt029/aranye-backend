"""add OTP delivery events

Revision ID: 003
Revises: 002
"""

from typing import Sequence

from alembic import op

import app.models  # noqa: F401
from app.core.database import Base

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["otp_delivery_events"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["otp_delivery_events"].drop(op.get_bind(), checkfirst=True)
