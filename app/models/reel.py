import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.marketplace import TimestampMixin


def enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_type]


class ReelMediaType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class ReelStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ReelCTAType(str, enum.Enum):
    NONE = "none"
    SHOP = "shop"
    PRODUCT = "product"
    EXTERNAL = "external"
    CALL = "call"


class ReelEventType(str, enum.Enum):
    SHARE = "share"
    CTA_CLICK = "cta_click"


class Reel(Base, TimestampMixin):
    __tablename__ = "reels"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="ck_reels_priority"),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="ck_reels_window"
        ),
        CheckConstraint("like_count >= 0", name="ck_reels_like_count"),
        CheckConstraint("save_count >= 0", name="ck_reels_save_count"),
        CheckConstraint("share_count >= 0", name="ck_reels_share_count"),
        CheckConstraint("view_count >= 0", name="ck_reels_view_count"),
        CheckConstraint("click_count >= 0", name="ck_reels_click_count"),
        Index("ix_reels_feed", "status", "category", "priority", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    caption: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), index=True)
    media_type: Mapped[ReelMediaType] = mapped_column(
        Enum(ReelMediaType, name="reel_media_type", values_callable=enum_values)
    )
    media_url: Mapped[str] = mapped_column(String(1000))
    poster_url: Mapped[str | None] = mapped_column(String(1000))
    cta_type: Mapped[ReelCTAType] = mapped_column(
        Enum(ReelCTAType, name="reel_cta_type", values_callable=enum_values),
        default=ReelCTAType.SHOP,
    )
    cta_value: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[ReelStatus] = mapped_column(
        Enum(ReelStatus, name="reel_status", values_callable=enum_values),
        default=ReelStatus.DRAFT,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    save_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    click_count: Mapped[int] = mapped_column(Integer, default=0)


class ReelLike(Base):
    __tablename__ = "reel_likes"
    __table_args__ = (UniqueConstraint("reel_id", "user_id", name="uq_reel_likes_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReelSave(Base):
    __tablename__ = "reel_saves"
    __table_args__ = (UniqueConstraint("reel_id", "user_id", name="uq_reel_saves_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReelView(Base, TimestampMixin):
    __tablename__ = "reel_views"
    __table_args__ = (
        UniqueConstraint("reel_id", "user_id", name="uq_reel_views_user"),
        CheckConstraint("watched_ms >= 0", name="ck_reel_views_watched_ms"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    watched_ms: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class ReelEvent(Base):
    __tablename__ = "reel_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[ReelEventType] = mapped_column(
        Enum(ReelEventType, name="reel_event_type", values_callable=enum_values), index=True
    )
    platform: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
