from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.scratch_card import DistributionMethod, ScratchCardType
from app.schemas.scratch_card import DistributionRequest, ScratchCardCreate


def card_payload(**overrides):
    start = datetime.now(UTC) + timedelta(hours=1)
    values = {
        "title": "Birthday coffee",
        "reward_type": "free_item",
        "starts_at": start,
        "ends_at": start + timedelta(days=7),
        "expires_at": start + timedelta(days=14),
        "scratch_card_type": ScratchCardType.ADMIN_REWARD,
    }
    values.update(overrides)
    return values


def test_shopkeeper_promotion_requires_shop():
    with pytest.raises(ValidationError, match="shop_id is required"):
        ScratchCardCreate(
            **card_payload(scratch_card_type=ScratchCardType.SHOPKEEPER_PROMOTION)
        )

    card = ScratchCardCreate(
        **card_payload(
            scratch_card_type=ScratchCardType.SHOPKEEPER_PROMOTION,
            shop_id=uuid4(),
        )
    )
    assert card.shop_id is not None


def test_card_window_and_limits_are_validated():
    start = datetime.now(UTC)
    with pytest.raises(ValidationError, match="ends_at must be after"):
        ScratchCardCreate(**card_payload(starts_at=start, ends_at=start))
    with pytest.raises(ValidationError, match="daily redemption limit"):
        ScratchCardCreate(
            **card_payload(daily_redemption_limit=20, total_redemption_limit=10)
        )
    with pytest.raises(ValidationError, match="coupon_code is required"):
        ScratchCardCreate(**card_payload(coupon_type="shared"))


def test_redemption_prefix_is_normalized_and_free_product_requires_shop():
    card = ScratchCardCreate(
        **card_payload(redemption_code_prefix=" birthday-26 ")
    )
    assert card.redemption_code_prefix == "BIRTHDAY26"
    with pytest.raises(ValidationError, match="physical free-product"):
        ScratchCardCreate(**card_payload(reward_type="free_product"))


@pytest.mark.parametrize(
    ("method", "message"),
    [
        (DistributionMethod.RANDOM, "quantity"),
        (DistributionMethod.BIRTHDAY, "quantity"),
        (DistributionMethod.NEARBY, "radius_km"),
        (DistributionMethod.NEARBY_QUANTITY, "quantity"),
        (DistributionMethod.TARGETED, "user_ids"),
        (DistributionMethod.AREA, "area and city"),
    ],
)
def test_distribution_methods_require_their_filters(method, message):
    with pytest.raises(ValidationError, match=message):
        DistributionRequest(distribution_method=method)


def test_distribution_job_filters_are_serializable():
    user_id = uuid4()
    request = DistributionRequest(
        distribution_method=DistributionMethod.TARGETED,
        user_ids=[user_id],
    )
    assert request.job_filters() == {"user_ids": [str(user_id)]}
