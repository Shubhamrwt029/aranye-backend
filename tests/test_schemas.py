from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.marketplace import CampaignCreate, CheckoutRequest, PromotionResponse, ShopCreate


def test_delivery_checkout_requires_address():
    with pytest.raises(ValidationError):
        CheckoutRequest(
            cart_id="e47729e8-1b18-4dc6-8fea-307a7ac52618",
            fulfillment_type="delivery",
            payment_method="cod",
        )


def test_shop_requires_fulfillment_mode():
    with pytest.raises(ValidationError):
        ShopCreate(
            name="Fresh Mart",
            business_type="grocery",
            phone="+919999999999",
            address_line="Main road",
            area="Central",
            city="Indore",
            postal_code="452001",
            latitude=22.7,
            longitude=75.8,
            supports_delivery=False,
            supports_pickup=False,
        )


def test_campaign_dates_and_weights():
    start = datetime.now(UTC) + timedelta(days=1)
    campaign = CampaignCreate(
        title="Monsoon prizes",
        area="Central",
        city="Indore",
        starts_at=start,
        ends_at=start + timedelta(days=3),
        reward_valid_until=date.today() + timedelta(days=10),
        total_inventory=100,
        prizes=[{"label": "10% off", "weight": 80}, {"label": "Free item", "weight": 20}],
    )
    assert sum(p["weight"] for p in campaign.prizes) == 100


def test_promotion_response_accepts_database_uuid_and_serializes_it():
    promotion_id = UUID("97c76ead-48e3-5cb6-930f-4bc2d43691ce")
    promotion = PromotionResponse.model_validate(
        SimpleNamespace(
            id=promotion_id,
            title="Jaipur summer sale",
            subtitle="Save on daily essentials",
            image_url="https://example.com/promotion.jpg",
            action_type="category",
            action_value="ec2bf0ec-3987-4d57-b5d1-c834de9d7b20",
            placement="offer",
            sort_order=1,
        )
    )

    assert promotion.id == promotion_id
    assert promotion.placement == "offer"
    assert f'"id":"{promotion_id}"' in promotion.model_dump_json()
