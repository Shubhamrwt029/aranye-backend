"""create users table

Revision ID: 001
Revises:
Create Date: 2026-07-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role_enum = postgresql.ENUM(
    "customer", "shopkeeper", "admin", name="user_role", create_type=False
)
gender_enum = postgresql.ENUM("male", "female", "other", name="gender", create_type=False)


def upgrade() -> None:
    # Create enums once via raw SQL (idempotent)
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE user_role AS ENUM ('customer', 'shopkeeper', 'admin'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE gender AS ENUM ('male', 'female', 'other'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("phone", sa.String(length=15), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("gender", gender_enum, nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("whatsapp_number", sa.String(length=15), nullable=True),
        sa.Column("profile_image_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_profile_complete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_phone_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone", "role", name="uq_users_phone_role"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_phone", "users", ["phone"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role", "users", ["role"])


def downgrade() -> None:
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS gender")
    op.execute("DROP TYPE IF EXISTS user_role")
