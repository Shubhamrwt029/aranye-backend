"""add scratch card management and assignment tables

Revision ID: 008
Revises: 007
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

card_status = postgresql.ENUM(
    "draft",
    "publishing",
    "scheduled",
    "active",
    "paused",
    "expired",
    "failed",
    "archived",
    name="scratch_card_status",
    create_type=False,
)
card_type = postgresql.ENUM(
    "admin_reward",
    "shopkeeper_promotion",
    name="scratch_card_type",
    create_type=False,
)
distribution_method = postgresql.ENUM(
    "random",
    "nearby",
    "nearby_quantity",
    "targeted",
    "birthday",
    "area",
    name="scratch_distribution_method",
    create_type=False,
)
job_status = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    name="scratch_distribution_job_status",
    create_type=False,
)
assignment_status = postgresql.ENUM(
    "assigned",
    "viewed",
    "scratched",
    "redeemed",
    "expired",
    name="scratch_assignment_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    card_status.create(bind, checkfirst=True)
    card_type.create(bind, checkfirst=True)
    distribution_method.create(bind, checkfirst=True)
    job_status.create(bind, checkfirst=True)
    assignment_status.create(bind, checkfirst=True)

    op.create_table(
        "scratch_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("shop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shops.id")),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("subtitle", sa.String(240)),
        sa.Column("description", sa.Text()),
        sa.Column("image_url", sa.String(800)),
        sa.Column("banner_url", sa.String(800)),
        sa.Column("reward_type", sa.String(50), nullable=False),
        sa.Column("offer_type", sa.String(50)),
        sa.Column("terms_and_conditions", sa.Text()),
        sa.Column("coupon_code", sa.String(80)),
        sa.Column("coupon_type", sa.String(20), nullable=False, server_default="unique"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", card_status, nullable=False, server_default="draft"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("daily_redemption_limit", sa.Integer()),
        sa.Column("total_redemption_limit", sa.Integer()),
        sa.Column("scratch_card_type", card_type, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("total_redeemed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("ends_at > starts_at", name="ck_scratch_cards_date_window"),
        sa.CheckConstraint("expires_at >= ends_at", name="ck_scratch_cards_expiry"),
        sa.CheckConstraint("priority >= 0", name="ck_scratch_cards_priority"),
        sa.CheckConstraint(
            "daily_redemption_limit IS NULL OR daily_redemption_limit > 0",
            name="ck_scratch_cards_daily_limit",
        ),
        sa.CheckConstraint(
            "total_redemption_limit IS NULL OR total_redemption_limit > 0",
            name="ck_scratch_cards_total_limit",
        ),
    )
    op.create_index("ix_scratch_cards_shop_id", "scratch_cards", ["shop_id"])
    op.create_index("ix_scratch_cards_title", "scratch_cards", ["title"])
    op.create_index("ix_scratch_cards_starts_at", "scratch_cards", ["starts_at"])
    op.create_index("ix_scratch_cards_ends_at", "scratch_cards", ["ends_at"])
    op.create_index("ix_scratch_cards_expires_at", "scratch_cards", ["expires_at"])
    op.create_index("ix_scratch_cards_status", "scratch_cards", ["status"])
    op.create_index("ix_scratch_cards_priority", "scratch_cards", ["priority"])
    op.create_index("ix_scratch_cards_scratch_card_type", "scratch_cards", ["scratch_card_type"])
    op.create_index(
        "ix_scratch_cards_visibility", "scratch_cards", ["status", "starts_at", "ends_at"]
    )

    op.create_table(
        "scratch_card_distribution_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scratch_card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scratch_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("distribution_method", distribution_method, nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("requested_quantity", sa.Integer()),
        sa.Column("status", job_status, nullable=False, server_default="pending"),
        sa.Column("eligible_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assigned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "requested_quantity IS NULL OR requested_quantity > 0",
            name="ck_scratch_distribution_quantity",
        ),
    )
    op.create_index(
        "ix_scratch_card_distribution_jobs_scratch_card_id",
        "scratch_card_distribution_jobs",
        ["scratch_card_id"],
    )
    op.create_index(
        "ix_scratch_card_distribution_jobs_distribution_method",
        "scratch_card_distribution_jobs",
        ["distribution_method"],
    )
    op.create_index(
        "ix_scratch_card_distribution_jobs_status",
        "scratch_card_distribution_jobs",
        ["status"],
    )
    op.create_index(
        "ix_scratch_distribution_claim",
        "scratch_card_distribution_jobs",
        ["status", "created_at"],
    )

    op.create_table(
        "scratch_card_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scratch_card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scratch_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "distribution_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scratch_card_distribution_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column("distribution_method", distribution_method, nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", assignment_status, nullable=False, server_default="assigned"),
        sa.Column("redemption_code", sa.String(24), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True)),
        sa.Column("scratched_at", sa.DateTime(timezone=True)),
        sa.Column("redeemed_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "scratch_card_id", "user_id", name="uq_scratch_card_assignment_user"
        ),
        sa.UniqueConstraint("redemption_code", name="uq_scratch_card_redemption_code"),
    )
    op.create_index(
        "ix_scratch_card_assignments_scratch_card_id",
        "scratch_card_assignments",
        ["scratch_card_id"],
    )
    op.create_index("ix_scratch_card_assignments_user_id", "scratch_card_assignments", ["user_id"])
    op.create_index(
        "ix_scratch_card_assignments_distribution_job_id",
        "scratch_card_assignments",
        ["distribution_job_id"],
    )
    op.create_index(
        "ix_scratch_card_assignments_distribution_method",
        "scratch_card_assignments",
        ["distribution_method"],
    )
    op.create_index("ix_scratch_card_assignments_assigned_at", "scratch_card_assignments", ["assigned_at"])
    op.create_index("ix_scratch_card_assignments_status", "scratch_card_assignments", ["status"])
    op.create_index(
        "ix_scratch_card_assignments_redemption_code",
        "scratch_card_assignments",
        ["redemption_code"],
    )
    op.create_index(
        "ix_scratch_assignments_card_status",
        "scratch_card_assignments",
        ["scratch_card_id", "status"],
    )
    op.create_index(
        "ix_scratch_assignments_user_status",
        "scratch_card_assignments",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_scratch_assignments_card_assigned",
        "scratch_card_assignments",
        ["scratch_card_id", "assigned_at"],
    )

    op.create_index("ix_addresses_coordinates", "addresses", ["latitude", "longitude"])
    op.create_index("ix_addresses_area_city", "addresses", ["area", "city"])
    op.create_index("ix_users_date_of_birth", "users", ["date_of_birth"])


def downgrade() -> None:
    op.drop_index("ix_users_date_of_birth", table_name="users")
    op.drop_index("ix_addresses_area_city", table_name="addresses")
    op.drop_index("ix_addresses_coordinates", table_name="addresses")
    op.drop_table("scratch_card_assignments")
    op.drop_table("scratch_card_distribution_jobs")
    op.drop_table("scratch_cards")
    bind = op.get_bind()
    assignment_status.drop(bind, checkfirst=True)
    job_status.drop(bind, checkfirst=True)
    distribution_method.drop(bind, checkfirst=True)
    card_type.drop(bind, checkfirst=True)
    card_status.drop(bind, checkfirst=True)
