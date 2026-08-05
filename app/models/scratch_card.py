import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.marketplace import TimestampMixin


def enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_type]


class ScratchCardType(str, enum.Enum):
    ADMIN_REWARD = "admin_reward"
    SHOPKEEPER_PROMOTION = "shopkeeper_promotion"


class ScratchCardStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHING = "publishing"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    EXPIRED = "expired"
    FAILED = "failed"
    ARCHIVED = "archived"


class DistributionMethod(str, enum.Enum):
    RANDOM = "random"
    NEARBY = "nearby"
    NEARBY_QUANTITY = "nearby_quantity"
    TARGETED = "targeted"
    BIRTHDAY = "birthday"
    AREA = "area"


class DistributionJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScratchAssignmentStatus(str, enum.Enum):
    ASSIGNED = "assigned"
    VIEWED = "viewed"
    SCRATCHED = "scratched"
    REDEEMED = "redeemed"
    EXPIRED = "expired"


class ScratchCard(Base, TimestampMixin):
    __tablename__ = "scratch_cards"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_scratch_cards_date_window"),
        CheckConstraint("expires_at >= ends_at", name="ck_scratch_cards_expiry"),
        CheckConstraint("priority >= 0", name="ck_scratch_cards_priority"),
        CheckConstraint(
            "daily_redemption_limit IS NULL OR daily_redemption_limit > 0",
            name="ck_scratch_cards_daily_limit",
        ),
        CheckConstraint(
            "total_redemption_limit IS NULL OR total_redemption_limit > 0",
            name="ck_scratch_cards_total_limit",
        ),
        Index("ix_scratch_cards_visibility", "status", "starts_at", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), index=True)
    subtitle: Mapped[str | None] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(800))
    banner_url: Mapped[str | None] = mapped_column(String(800))
    reward_type: Mapped[str] = mapped_column(String(50))
    offer_type: Mapped[str | None] = mapped_column(String(50))
    terms_and_conditions: Mapped[str | None] = mapped_column(Text)
    coupon_code: Mapped[str | None] = mapped_column(String(80))
    coupon_type: Mapped[str] = mapped_column(String(20), default="unique")
    redemption_code_prefix: Mapped[str | None] = mapped_column(String(12))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[ScratchCardStatus] = mapped_column(
        Enum(
            ScratchCardStatus,
            name="scratch_card_status",
            values_callable=enum_values,
        ),
        default=ScratchCardStatus.DRAFT,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    daily_redemption_limit: Mapped[int | None] = mapped_column(Integer)
    total_redemption_limit: Mapped[int | None] = mapped_column(Integer)
    scratch_card_type: Mapped[ScratchCardType] = mapped_column(
        Enum(
            ScratchCardType,
            name="scratch_card_type",
            values_callable=enum_values,
        ),
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_redeemed: Mapped[int] = mapped_column(Integer, default=0)


class ScratchCardDistributionJob(Base, TimestampMixin):
    __tablename__ = "scratch_card_distribution_jobs"
    __table_args__ = (
        CheckConstraint(
            "requested_quantity IS NULL OR requested_quantity > 0",
            name="ck_scratch_distribution_quantity",
        ),
        Index("ix_scratch_distribution_claim", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scratch_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scratch_cards.id", ondelete="CASCADE"), index=True
    )
    distribution_method: Mapped[DistributionMethod] = mapped_column(
        Enum(
            DistributionMethod,
            name="scratch_distribution_method",
            values_callable=enum_values,
        ),
        index=True,
    )
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_quantity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[DistributionJobStatus] = mapped_column(
        Enum(
            DistributionJobStatus,
            name="scratch_distribution_job_status",
            values_callable=enum_values,
        ),
        default=DistributionJobStatus.PENDING,
        index=True,
    )
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)
    assigned_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScratchCardAssignment(Base, TimestampMixin):
    __tablename__ = "scratch_card_assignments"
    __table_args__ = (
        UniqueConstraint("scratch_card_id", "user_id", name="uq_scratch_card_assignment_user"),
        UniqueConstraint("redemption_code", name="uq_scratch_card_redemption_code"),
        Index("ix_scratch_assignments_card_status", "scratch_card_id", "status"),
        Index("ix_scratch_assignments_user_status", "user_id", "status"),
        Index("ix_scratch_assignments_card_assigned", "scratch_card_id", "assigned_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scratch_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scratch_cards.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    distribution_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scratch_card_distribution_jobs.id", ondelete="SET NULL"),
        index=True,
    )
    distribution_method: Mapped[DistributionMethod] = mapped_column(
        Enum(
            DistributionMethod,
            name="scratch_distribution_method",
            values_callable=enum_values,
            create_type=False,
        ),
        index=True,
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    status: Mapped[ScratchAssignmentStatus] = mapped_column(
        Enum(
            ScratchAssignmentStatus,
            name="scratch_assignment_status",
            values_callable=enum_values,
        ),
        default=ScratchAssignmentStatus.ASSIGNED,
        index=True,
    )
    redemption_code: Mapped[str] = mapped_column(String(24), index=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scratched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
