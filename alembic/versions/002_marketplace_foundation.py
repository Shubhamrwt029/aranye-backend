"""marketplace foundation

Revision ID: 002
Revises: 001
"""

from typing import Sequence

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = [
    "refresh_sessions",
    "addresses",
    "shops",
    "shop_hours",
    "bank_accounts",
    "categories",
    "products",
    "favorites",
    "carts",
    "cart_items",
    "orders",
    "order_items",
    "payments",
    "reward_campaigns",
    "reward_claims",
    "notifications",
    "audit_logs",
    "app_settings",
]


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind, checkfirst=True)
