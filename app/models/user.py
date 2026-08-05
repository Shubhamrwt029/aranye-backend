import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRole(str, enum.Enum):
    CUSTOMER = "customer"
    SHOPKEEPER = "shopkeeper"
    ADMIN = "admin"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class User(Base):
    """
    Single users table with role-based access control (RBAC).
    MNCs prefer one user table + role field over separate tables per role.
    Role-specific data (shop details, etc.) goes in separate profile tables later.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("phone", "role", name="uq_users_phone_role"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Login identifiers — phone for customer/shopkeeper, email for admin
    phone: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)

    # Password only for admin panel (customer/shopkeeper use OTP)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )

    # Profile fields (filled after first login — "Add Your Detail" screen)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gender: Mapped[Gender | None] = mapped_column(
        Enum(Gender, name="gender", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(15), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_profile_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(120))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
