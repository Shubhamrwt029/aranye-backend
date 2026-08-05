from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.api.v1.endpoints.customer import search_shops
from app.models.marketplace import Product, Shop, ShopStatus


class QueryResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class SearchSession:
    def __init__(self, shop, product):
        self.responses = [QueryResult([(shop, product)]), QueryResult([])]
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_search_returns_product_image_with_one_ranked_result_per_shop():
    now = datetime.now(UTC)
    shop = Shop(
        id=uuid4(),
        owner_id=uuid4(),
        name="Fresh Basket",
        business_type="grocery",
        description=None,
        phone="+919999999999",
        whatsapp_number=None,
        address_line="Market Road",
        area="Central",
        city="Kurukshetra",
        postal_code="136118",
        latitude=Decimal("29.9695"),
        longitude=Decimal("76.8783"),
        service_radius_km=Decimal("5"),
        delivery_fee_paise=0,
        minimum_order_paise=0,
        supports_delivery=True,
        supports_pickup=True,
        status=ShopStatus.ACTIVE,
        is_open=True,
        rejection_reason=None,
        logo_url="/shop.webp",
        banner_url=None,
        rating_average=Decimal("4.50"),
        rating_count=10,
        created_at=now,
    )
    product = Product(
        id=uuid4(),
        shop_id=shop.id,
        name="Whole Milk",
        category_id=None,
        description="Fresh dairy milk",
        ingredients=None,
        price_paise=6500,
        compare_at_price_paise=None,
        stock_quantity=20,
        is_available=True,
        is_featured=True,
        is_deleted=False,
        image_urls=["/product-milk.webp"],
        rating_average=Decimal("4.75"),
        rating_count=20,
        created_at=now,
    )
    session = SearchSession(shop, product)

    results = await search_shops(
        session, q="milk", city="Kurukshetra", limit=20, offset=0
    )

    assert len(results) == 1
    assert results[0].shop.id == shop.id
    assert results[0].matched_product.id == product.id
    assert results[0].matched_product.image_urls == ["/product-milk.webp"]

    sql = str(
        session.queries[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "row_number() OVER (PARTITION BY shops.id" in sql
    assert "products.is_deleted IS false" in sql
    assert "products.is_available IS true" in sql
    assert "lower(shops.city) = 'kurukshetra'" in sql
