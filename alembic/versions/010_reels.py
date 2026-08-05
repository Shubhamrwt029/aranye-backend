"""add reel advertising and engagement tables

Revision ID: 010
Revises: 009
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    media_type = postgresql.ENUM("image", "video", name="reel_media_type", create_type=False)
    status = postgresql.ENUM(
        "draft", "active", "paused", "archived", name="reel_status", create_type=False
    )
    cta_type = postgresql.ENUM(
        "none",
        "shop",
        "product",
        "external",
        "call",
        name="reel_cta_type",
        create_type=False,
    )
    event_type = postgresql.ENUM("share", "cta_click", name="reel_event_type", create_type=False)
    media_type.create(bind, checkfirst=True)
    status.create(bind, checkfirst=True)
    cta_type.create(bind, checkfirst=True)
    event_type.create(bind, checkfirst=True)

    op.create_table(
        "reels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("media_type", media_type, nullable=False),
        sa.Column("media_url", sa.String(1000), nullable=False),
        sa.Column("poster_url", sa.String(1000)),
        sa.Column("cta_type", cta_type, nullable=False, server_default="shop"),
        sa.Column("cta_value", sa.String(1000)),
        sa.Column("status", status, nullable=False, server_default="draft"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("save_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("priority >= 0", name="ck_reels_priority"),
        sa.CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="ck_reels_window"
        ),
        sa.CheckConstraint("like_count >= 0", name="ck_reels_like_count"),
        sa.CheckConstraint("save_count >= 0", name="ck_reels_save_count"),
        sa.CheckConstraint("share_count >= 0", name="ck_reels_share_count"),
        sa.CheckConstraint("view_count >= 0", name="ck_reels_view_count"),
        sa.CheckConstraint("click_count >= 0", name="ck_reels_click_count"),
    )
    for column in (
        "shop_id",
        "product_id",
        "category",
        "status",
        "priority",
        "starts_at",
        "ends_at",
        "published_at",
    ):
        op.create_index(f"ix_reels_{column}", "reels", [column])
    op.create_index("ix_reels_feed", "reels", ["status", "category", "priority", "published_at"])

    for table, unique_name in (
        ("reel_likes", "uq_reel_likes_user"),
        ("reel_saves", "uq_reel_saves_user"),
    ):
        op.create_table(
            table,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "reel_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("reels.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("reel_id", "user_id", name=unique_name),
        )
        op.create_index(f"ix_{table}_reel_id", table, ["reel_id"])
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    op.create_table(
        "reel_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("watched_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("reel_id", "user_id", name="uq_reel_views_user"),
        sa.CheckConstraint("watched_ms >= 0", name="ck_reel_views_watched_ms"),
    )
    op.create_index("ix_reel_views_reel_id", "reel_views", ["reel_id"])
    op.create_index("ix_reel_views_user_id", "reel_views", ["user_id"])

    op.create_table(
        "reel_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("platform", sa.String(30)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_reel_events_reel_id", "reel_events", ["reel_id"])
    op.create_index("ix_reel_events_user_id", "reel_events", ["user_id"])
    op.create_index("ix_reel_events_event_type", "reel_events", ["event_type"])
    op.create_index("ix_reel_events_created_at", "reel_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("reel_events")
    op.drop_table("reel_views")
    op.drop_table("reel_saves")
    op.drop_table("reel_likes")
    op.drop_table("reels")
    bind = op.get_bind()
    for name in ("reel_event_type", "reel_cta_type", "reel_status", "reel_media_type"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
