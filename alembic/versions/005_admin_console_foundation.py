"""admin console foundation

Revision ID: 005
Revises: 004
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promotions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("subtitle", sa.String(240), nullable=False),
        sa.Column("image_url", sa.String(500), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("action_value", sa.String(500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_city", sa.String(120)),
        sa.Column("target_area", sa.String(120)),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_promotions_sort_order", "promotions", ["sort_order"])
    op.create_index("ix_promotions_is_active", "promotions", ["is_active"])
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("object_key", sa.String(500), nullable=False, unique=True),
        sa.Column("bucket", sa.String(120), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("public_url", sa.String(800)),
        sa.Column(
            "uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_media_assets_object_key", "media_assets", ["object_key"], unique=True)
    op.create_index("ix_media_assets_status", "media_assets", ["status"])
    op.create_table(
        "notification_broadcasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    existing = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("audit_logs")
    }
    if "reason" not in existing:
        op.add_column("audit_logs", sa.Column("reason", sa.String(500)))
    if "ip_address" not in existing:
        op.add_column("audit_logs", sa.Column("ip_address", sa.String(64)))
    if "user_agent" not in existing:
        op.add_column("audit_logs", sa.Column("user_agent", sa.String(500)))


def downgrade() -> None:
    op.drop_column("audit_logs", "user_agent")
    op.drop_column("audit_logs", "ip_address")
    op.drop_column("audit_logs", "reason")
    op.drop_table("notification_broadcasts")
    op.drop_table("media_assets")
    op.drop_table("promotions")
