from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.exceptions import AppException
from app.main import app
from app.schemas.reel import ReelCreate, ReelMediaPresignRequest, ReelUpdate
from app.services.media_service import MediaService


def test_reel_routes_cover_mobile_and_publishing_features():
    paths = app.openapi()["paths"]
    expected_methods = {
        "/api/v1/customer/reels": {"get"},
        "/api/v1/customer/reels/categories": {"get"},
        "/api/v1/customer/reels/{reel_id}": {"get"},
        "/api/v1/customer/reels/{reel_id}/like": {"put", "delete"},
        "/api/v1/customer/reels/{reel_id}/save": {"put", "delete"},
        "/api/v1/customer/reels/{reel_id}/view": {"post"},
        "/api/v1/customer/reels/{reel_id}/share": {"post"},
        "/api/v1/customer/reels/{reel_id}/cta-click": {"post"},
        "/api/v1/shopkeeper/reels": {"get", "post"},
        "/api/v1/shopkeeper/reels/media/presign": {"post"},
        "/api/v1/shopkeeper/reels/media/{asset_id}/complete": {"post"},
        "/api/v1/shopkeeper/reels/{reel_id}": {"get", "patch", "delete"},
        "/api/v1/shopkeeper/reels/{reel_id}/publish": {"post"},
        "/api/v1/shopkeeper/reels/{reel_id}/pause": {"post"},
        "/api/v1/shopkeeper/reels/{reel_id}/analytics": {"get"},
    }
    for path, methods in expected_methods.items():
        assert path in paths
        assert methods <= set(paths[path])


def test_reel_create_validates_cta_and_dates():
    asset_id = UUID("5e6e6ac9-f79d-4a89-8da7-bdb9154f09d6")
    start = datetime.now(UTC) + timedelta(hours=1)
    with pytest.raises(ValidationError, match="product_id is required"):
        ReelCreate(
            title="Fresh arrivals",
            category="Daily Needs",
            media_type="video",
            media_asset_id=asset_id,
            cta_type="product",
            starts_at=start,
            ends_at=start + timedelta(days=1),
        )
    with pytest.raises(ValidationError, match="ends_at must be after"):
        ReelCreate(
            title="Fresh arrivals",
            category="Daily Needs",
            media_type="video",
            media_asset_id=asset_id,
            starts_at=start,
            ends_at=start - timedelta(minutes=1),
        )


def test_reel_media_update_is_atomic_and_video_upload_is_supported():
    asset_id = UUID("5e6e6ac9-f79d-4a89-8da7-bdb9154f09d6")
    request = ReelMediaPresignRequest(
        filename="offer.mp4", content_type="video/mp4", size_bytes=5_000_000
    )
    assert request.content_type == "video/mp4"
    with pytest.raises(ValidationError, match="must be supplied together"):
        ReelUpdate(media_asset_id=asset_id)
    with pytest.raises(ValidationError, match="must be supplied together"):
        ReelUpdate(media_type=None, media_asset_id=None)
    with pytest.raises(ValidationError, match="cannot be null"):
        ReelUpdate(title=None)


def test_reel_upload_limits_distinguish_images_and_videos():
    service = MediaService.__new__(MediaService)
    service.validate_reel_size(10_485_760, "image/jpeg")
    service.validate_reel_size(104_857_600, "video/mp4")
    with pytest.raises(AppException, match="Image exceeds 10 MB"):
        service.validate_reel_size(10_485_761, "image/jpeg")
    with pytest.raises(AppException, match="Video exceeds 100 MB"):
        service.validate_reel_size(104_857_601, "video/mp4")


def test_reel_category_is_normalized_for_backend_driven_chips():
    data = ReelCreate(
        title="  Fresh   arrivals ",
        category=" Daily   Needs ",
        media_type="image",
        media_asset_id=UUID("5e6e6ac9-f79d-4a89-8da7-bdb9154f09d6"),
    )
    assert data.title == "Fresh arrivals"
    assert data.category == "Daily Needs"
