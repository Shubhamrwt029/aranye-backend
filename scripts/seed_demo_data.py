"""Idempotently seed a dense, realistic marketplace in non-production environments.

The seed covers public catalog APIs and every existing customer account's private
collections so a newly verified development/staging customer sees a complete demo.

Usage:
    DEMO_DATA_ENABLED=true uv run python scripts/seed_demo_data.py
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.marketplace import (
    Address,
    Cart,
    CartItem,
    Category,
    Favorite,
    FulfillmentType,
    Notification,
    Order,
    OrderStatus,
    Product,
    Promotion,
    RewardCampaign,
    RewardClaim,
    Shop,
    ShopStatus,
)
from app.models.reel import Reel, ReelCTAType, ReelMediaType, ReelStatus
from app.models.user import Gender, User, UserRole

settings = get_settings()
DEMO_NAMESPACE = UUID("d138ed22-3c30-43d5-b347-90945c311418")
DEMO_SIZE = 20

REELS = [
    (
        "daily-needs-arrivals",
        "Fresh arrivals for your home",
        "Daily essentials, delivered from a trusted shop near you.",
        "Daily Needs",
        "daily-needs",
        "reel-daily-needs.mp4",
        "shop-category-v2-grocery.webp",
    ),
    (
        "food-favourites",
        "Fresh food favourites",
        "Discover bakery favourites prepared fresh today.",
        "Food",
        "golden-bakery",
        "reel-food.mp4",
        "reel-food-poster.png",
    ),
    (
        "fashion-picks",
        "New season fashion picks",
        "Explore everyday styles from Urban Weaves.",
        "Fashion",
        "urban-weaves",
        "reel-showcase.mp4",
        "shop-fashion-banner.webp",
    ),
    (
        "beauty-essentials",
        "Beauty essentials",
        "Shop personal-care picks from a local store.",
        "Beauty",
        "style-studio",
        "reel-food.mp4",
        "product-skincare.webp",
    ),
]

CATEGORIES = [
    ("fresh-vegetables", "Fresh Vegetables", "category-v4-fresh-vegetables.webp"),
    ("fruits", "Fresh Fruits", "category-v4-fresh-fruits.webp"),
    ("dairy", "Dairy, Bread and Eggs", "category-v4-dairy-bread-eggs.webp"),
    ("rice-atta-dals", "Rice, Atta and Dals", "category-v4-rice-atta-dals.webp"),
    ("masalas-dry-fruits", "Masalas and Dry Fruits", "category-v4-masalas-dry-fruits.webp"),
    ("edible-oils-ghee", "Edible Oils and Ghee", "category-v4-edible-oils-ghee.webp"),
    ("munchies", "Munchies", "category-v4-munchies.webp"),
    (
        "chocolates-ice-cream",
        "Chocolates and Ice Creams",
        "category-v4-chocolates-ice-cream.webp",
    ),
    (
        "cold-drinks-juices",
        "Cold Drinks and Juices",
        "category-v4-cold-drinks-juices.webp",
    ),
    ("biscuits-cakes", "Biscuits and Cakes", "category-v4-biscuits-cakes.webp"),
    (
        "instant-frozen-food",
        "Instant and Frozen Food",
        "category-v4-instant-frozen.webp",
    ),
    (
        "meat-seafood",
        "Chicken, Mutton and Seafood",
        "category-v4-chicken-mutton-seafood.webp",
    ),
    ("bakery", "Bakery", "category-bakery.webp"),
    ("restaurants", "Restaurants", "product-thali.webp"),
    ("fashion", "Fashion", "product-kurta.webp"),
    ("beauty", "Beauty & Personal Care", "product-skincare.webp"),
    ("footwear", "Footwear", "product-sneakers.webp"),
    ("electronics", "Electronics", "product-headphones.webp"),
    ("home-living", "Home & Living", "product-home-decor.webp"),
    ("pharmacy", "Pharmacy & Wellness", "product-skincare.webp"),
]

CITY_SHOP_CATEGORY_SLUGS = {
    "fresh-vegetables",
    "fruits",
    "dairy",
    "rice-atta-dals",
    "masalas-dry-fruits",
    "edible-oils-ghee",
    "munchies",
    "chocolates-ice-cream",
    "cold-drinks-juices",
    "biscuits-cakes",
    "instant-frozen-food",
    "meat-seafood",
}

SHOPS = [
    ("golden-bakery", "Golden Bakery", "Bakery", "Sector 17", "shop-category-v2-bakery.webp"),
    ("fresh-basket", "Fresh Basket Market", "Grocery", "Sector 7", "shop-category-v2-produce.webp"),
    (
        "spice-route",
        "Kurukshetra Fresh Meat & Seafood",
        "Meat & Seafood",
        "Model Town",
        "shop-category-v2-meat.webp",
    ),
    ("urban-weaves", "Urban Weaves", "Fashion", "Sector 13", "shop-fashion-banner.webp"),
    ("tech-corner", "Tech Corner", "Electronics", "Railway Road", "shop-electronics-banner.webp"),
    ("bean-and-bloom", "Bean & Bloom Cafe", "Cafe", "Sector 17", "shop-category-v2-dairy.webp"),
    (
        "daily-needs",
        "Daily Needs Supermart",
        "Grocery",
        "Pipli Road",
        "shop-category-v2-grocery.webp",
    ),
    ("royal-bakes", "Royal Bakes", "Bakery", "University Road", "shop-category-v2-bakery.webp"),
    (
        "punjabi-tadka",
        "Punjab Meat House",
        "Meat & Seafood",
        "Sector 10",
        "shop-category-v2-meat.webp",
    ),
    ("style-studio", "Style Studio", "Fashion", "Sector 5", "shop-fashion-banner.webp"),
    (
        "smart-life",
        "Smart Life Electronics",
        "Electronics",
        "Main Bazaar",
        "shop-electronics-banner.webp",
    ),
    (
        "harvest-store",
        "Harvest Organic Store",
        "Grocery",
        "Sector 3",
        "shop-category-v2-produce.webp",
    ),
    ("oven-story", "The Oven Story", "Bakery", "Model Town", "shop-category-v2-bakery.webp"),
    (
        "green-leaf",
        "Fresh Catch Fish Market",
        "Meat & Seafood",
        "Sector 8",
        "shop-category-v2-meat.webp",
    ),
    ("thread-tales", "Thread & Tales", "Fashion", "Sector 17", "shop-fashion-banner.webp"),
    ("gadget-hub", "Gadget Hub", "Electronics", "KDB Road", "shop-electronics-banner.webp"),
    ("morning-mug", "The Morning Mug", "Cafe", "Sector 13", "shop-category-v2-dairy.webp"),
    ("family-grocer", "Family Grocer", "Grocery", "Sector 4", "shop-category-v2-snacks.webp"),
    ("sweet-crust", "Sweet Crust Patisserie", "Bakery", "Sector 2", "shop-category-v2-bakery.webp"),
    (
        "desi-rasoi",
        "Royal Chicken & Seafood",
        "Meat & Seafood",
        "Pipli",
        "shop-category-v2-meat.webp",
    ),
]

GROCERY_CATEGORIES = {
    "fresh-vegetables",
    "fruits",
    "dairy",
    "rice-atta-dals",
    "masalas-dry-fruits",
    "edible-oils-ghee",
    "munchies",
    "chocolates-ice-cream",
    "cold-drinks-juices",
    "biscuits-cakes",
    "instant-frozen-food",
}
SHOP_CATEGORY_PORTFOLIOS = {
    "golden-bakery": {"dairy", "bakery", "biscuits-cakes"},
    "fresh-basket": GROCERY_CATEGORIES,
    "spice-route": {"meat-seafood"},
    "urban-weaves": {"fashion"},
    "tech-corner": {"electronics"},
    "bean-and-bloom": {"dairy", "bakery", "biscuits-cakes", "cold-drinks-juices"},
    "daily-needs": GROCERY_CATEGORIES,
    "royal-bakes": {"dairy", "bakery", "biscuits-cakes"},
    "punjabi-tadka": {"meat-seafood"},
    "style-studio": {"fashion", "beauty"},
    "smart-life": {"electronics", "home-living"},
    "harvest-store": {
        "fresh-vegetables",
        "fruits",
        "dairy",
        "rice-atta-dals",
        "masalas-dry-fruits",
        "edible-oils-ghee",
        "munchies",
    },
    "oven-story": {"dairy", "bakery", "biscuits-cakes"},
    "green-leaf": {"meat-seafood"},
    "thread-tales": {"fashion"},
    "gadget-hub": {"electronics"},
    "morning-mug": {"dairy", "bakery", "biscuits-cakes", "cold-drinks-juices"},
    "family-grocer": GROCERY_CATEGORIES,
    "sweet-crust": {"dairy", "bakery", "biscuits-cakes"},
    "desi-rasoi": {"meat-seafood"},
}

PRODUCTS = [
    (
        "farm-tomatoes",
        "Farm Fresh Tomatoes",
        "fresh-vegetables",
        5500,
        "product-v2-tomatoes.webp",
    ),
    (
        "leafy-spinach",
        "Fresh Leafy Spinach",
        "fresh-vegetables",
        3500,
        "product-v2-spinach.webp",
    ),
    (
        "potato-onion-pack",
        "Potato & Onion Value Pack",
        "fresh-vegetables",
        8900,
        "product-v2-potato-onion.webp",
    ),
    ("butter-croissant", "Butter Croissant", "bakery", 32500, "product-croissant.webp"),
    ("chocolate-muffin", "Chocolate Muffin", "biscuits-cakes", 27500, "product-muffin.webp"),
    ("sourdough-bread", "Sourdough Bread", "bakery", 59900, "product-sourdough.webp"),
    ("fruit-danish", "Seasonal Fruit Danish", "bakery", 45000, "product-danish.webp"),
    ("kinnaur-apples", "Kinnaur Apples", "fruits", 12000, "product-apples.webp"),
    ("fresh-bananas", "Fresh Bananas", "fruits", 6000, "product-bananas.webp"),
    (
        "seasonal-fruit-basket",
        "Seasonal Fruit Basket",
        "fruits",
        24900,
        "product-v2-fruit-basket.webp",
    ),
    ("farm-milk", "Farm Fresh Milk", "dairy", 6500, "product-milk.webp"),
    (
        "fresh-eggs",
        "Farm Fresh Eggs - 12 Pack",
        "dairy",
        11000,
        "product-v2-eggs.webp",
    ),
    ("fresh-paneer", "Fresh Malai Paneer", "dairy", 9500, "product-v2-paneer.webp"),
    (
        "basmati-rice",
        "Premium Basmati Rice",
        "rice-atta-dals",
        79900,
        "product-v2-basmati-rice.webp",
    ),
    (
        "whole-wheat-atta",
        "Whole Wheat Atta",
        "rice-atta-dals",
        44900,
        "product-v2-atta.webp",
    ),
    ("toor-dal", "Unpolished Toor Dal", "rice-atta-dals", 18900, "product-v2-toor-dal.webp"),
    (
        "turmeric-powder",
        "Pure Turmeric Powder",
        "masalas-dry-fruits",
        7800,
        "product-v2-turmeric.webp",
    ),
    (
        "garam-masala",
        "Classic Garam Masala",
        "masalas-dry-fruits",
        9200,
        "product-v2-garam-masala.webp",
    ),
    (
        "california-almonds",
        "California Almonds",
        "masalas-dry-fruits",
        39900,
        "product-v2-almonds.webp",
    ),
    (
        "mustard-oil",
        "Cold Pressed Mustard Oil",
        "edible-oils-ghee",
        18900,
        "product-v2-mustard-oil.webp",
    ),
    (
        "sunflower-oil",
        "Refined Sunflower Oil",
        "edible-oils-ghee",
        16500,
        "product-v2-sunflower-oil.webp",
    ),
    (
        "desi-ghee",
        "Pure Cow Desi Ghee",
        "edible-oils-ghee",
        64900,
        "product-v2-ghee.webp",
    ),
    (
        "potato-chips",
        "Classic Salted Potato Chips",
        "munchies",
        5000,
        "product-v2-potato-chips.webp",
    ),
    ("bhujia-namkeen", "Crispy Bhujia Namkeen", "munchies", 8500, "product-v2-bhujia.webp"),
    (
        "roasted-snacks",
        "Healthy Roasted Snack Mix",
        "munchies",
        12000,
        "product-v2-roasted-mix.webp",
    ),
    (
        "cookie-ice-cream",
        "Cookies & Cream Ice Cream",
        "chocolates-ice-cream",
        27500,
        "product-v2-cookie-ice-cream.webp",
    ),
    (
        "silk-chocolate",
        "Premium Milk Chocolate",
        "chocolates-ice-cream",
        17500,
        "product-v2-milk-chocolate.webp",
    ),
    (
        "chocolate-cookies",
        "Chocolate Sandwich Cookies",
        "chocolates-ice-cream",
        9000,
        "product-v2-sandwich-cookies.webp",
    ),
    (
        "orange-juice",
        "Orange Fruit Juice",
        "cold-drinks-juices",
        11000,
        "product-v2-orange-juice.webp",
    ),
    (
        "cola-can",
        "Chilled Cola Can",
        "cold-drinks-juices",
        4500,
        "product-v2-cola.webp",
    ),
    (
        "mineral-water",
        "Natural Mineral Water",
        "cold-drinks-juices",
        2500,
        "product-v2-water.webp",
    ),
    (
        "butter-biscuits",
        "Classic Butter Biscuits",
        "biscuits-cakes",
        7500,
        "product-v2-butter-biscuits.webp",
    ),
    (
        "instant-noodles",
        "Masala Instant Noodles",
        "instant-frozen-food",
        8500,
        "product-v2-instant-noodles.webp",
    ),
    (
        "frozen-samosas",
        "Frozen Punjabi Samosas",
        "instant-frozen-food",
        22500,
        "product-v2-samosas.webp",
    ),
    (
        "french-fries",
        "Crispy Frozen French Fries",
        "instant-frozen-food",
        19900,
        "product-v2-fries.webp",
    ),
    (
        "chicken-breast",
        "Fresh Chicken Breast",
        "meat-seafood",
        32900,
        "product-v2-chicken.webp",
    ),
    (
        "mutton-curry-cut",
        "Premium Mutton Curry Cut",
        "meat-seafood",
        79900,
        "product-v2-mutton.webp",
    ),
    (
        "fresh-rohu",
        "Fresh Rohu Fish",
        "meat-seafood",
        34900,
        "product-v2-rohu.webp",
    ),
    ("paneer-pizza", "Farmhouse Paneer Pizza", "restaurants", 39900, "product-pizza.webp"),
    ("classic-burger", "Classic Veg Burger", "restaurants", 24900, "product-burger.webp"),
    ("deluxe-thali", "Deluxe Vegetarian Thali", "restaurants", 34900, "product-thali.webp"),
    ("hakka-noodles", "Garden Hakka Noodles", "restaurants", 22900, "product-noodles.webp"),
    ("embroidered-kurta", "Embroidered Cotton Kurta", "fashion", 149900, "product-kurta.webp"),
    ("running-shoes", "Everyday Running Shoes", "footwear", 249900, "product-sneakers.webp"),
    ("leather-handbag", "Premium Everyday Handbag", "fashion", 189900, "product-handbag.webp"),
    ("cotton-tshirts", "Premium Cotton T-Shirt", "fashion", 79900, "product-tshirts.webp"),
    ("skincare-set", "Daily Skincare Essentials", "beauty", 89900, "product-skincare.webp"),
    (
        "wireless-headphones",
        "Wireless Headphones",
        "electronics",
        299900,
        "product-headphones.webp",
    ),
    ("smartwatch", "Active Smartwatch", "electronics", 449900, "product-smartwatch.webp"),
    ("home-decor", "Artisan Home Decor Set", "home-living", 129900, "product-home-decor.webp"),
    ("chocolate-pastry", "Belgian Chocolate Pastry", "biscuits-cakes", 22500, "reward-pastry.webp"),
]

OFFER_PROMOTIONS = [
    (
        "grocery-50",
        "50% Off Grocery Shopping",
        "Fresh essentials at a better price",
        "offer-grocery-50.png",
        "family-grocer",
    ),
    (
        "beauty-40",
        "40% Off Beauty Essentials",
        "Save on personal-care favourites",
        "offer-beauty-40.png",
        "style-studio",
    ),
    (
        "electronics-500",
        "₹500 Off Electronics",
        "Limited-time savings on smart devices",
        "offer-electronics-500.png",
        "tech-corner",
    ),
    (
        "bakery-bogo",
        "Buy 1 Get 1 Bakery Treats",
        "Freshly baked favourites for today",
        "offer-bakery-bogo.png",
        "golden-bakery",
    ),
    (
        "fashion-30",
        "30% Off Fashion Picks",
        "New-season styles from nearby shops",
        "offer-fashion-30.png",
        "urban-weaves",
    ),
    (
        "free-delivery",
        "Free Delivery on ₹499+",
        "Your daily essentials delivered",
        "offer-free-delivery.png",
        "daily-needs",
    ),
]


def demo_id(kind: str, key: str) -> UUID:
    return uuid5(DEMO_NAMESPACE, f"{kind}:{key}")


def image_url(filename: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/static/demo/{filename}"


async def upsert(session: AsyncSession, instance):
    return await session.merge(instance)


async def seed_users(session: AsyncSession) -> dict[str, User]:
    users: dict[str, User] = {}
    customer = User(
        id=demo_id("user", "customer"),
        phone="+919876540001",
        role=UserRole.CUSTOMER,
        name="Aarav Sharma",
        gender=Gender.MALE,
        date_of_birth=date(1996, 8, 14),
        whatsapp_number="+919876540001",
        profile_image_url=image_url("profile-aarav.webp"),
        is_phone_verified=True,
        is_profile_complete=True,
        is_active=True,
    )
    users["customer"] = await upsert(session, customer)
    owner_names = [
        "Meera Kapoor",
        "Rohan Verma",
        "Simran Kaur",
        "Arjun Mehta",
        "Kavya Nair",
        "Rahul Gupta",
        "Neha Bansal",
        "Aditya Jain",
        "Pooja Saini",
        "Vikram Singh",
        "Ishita Arora",
        "Manish Kumar",
        "Ritu Sharma",
        "Karan Malhotra",
        "Ananya Rao",
        "Nitin Sood",
        "Sneha Joshi",
        "Mohit Khanna",
        "Tanya Bhatia",
        "Deepak Yadav",
    ]
    for index, ((key, *_), owner_name) in enumerate(zip(SHOPS, owner_names, strict=True), start=1):
        users[key] = await upsert(
            session,
            User(
                id=demo_id("user", key),
                phone=f"+91987654{1000 + index:04d}",
                role=UserRole.SHOPKEEPER,
                name=owner_name,
                is_phone_verified=True,
                is_profile_complete=True,
                is_active=True,
            ),
        )
    return users


async def seed_categories(session: AsyncSession) -> dict[str, Category]:
    # Only update records owned by this seed. Categories created later through
    # the admin API must survive demo reseeding unchanged.
    result = {}
    for sort_order, (slug, name, filename) in enumerate(CATEGORIES, start=1):
        result[slug] = await upsert(
            session,
            Category(
                id=demo_id("category", slug),
                name=name,
                slug=slug,
                image_url=image_url(filename),
                is_active=slug in CITY_SHOP_CATEGORY_SLUGS,
                sort_order=sort_order,
            ),
        )
    return result


async def seed_shops(session: AsyncSession, users: dict[str, User]) -> dict[str, Shop]:
    result = {}
    for index, (key, name, business_type, area, banner) in enumerate(SHOPS, start=1):
        is_grocery = business_type == "Grocery"
        result[key] = await upsert(
            session,
            Shop(
                id=demo_id("shop", key),
                owner_id=users[key].id,
                name=name,
                business_type=business_type,
                description=f"A trusted local {business_type.lower()} offering carefully selected products and friendly service.",
                phone=f"+91987654{1000 + index:04d}",
                whatsapp_number=f"+91987654{1000 + index:04d}",
                address_line=f"{10 + index}, {area} Market",
                area=area,
                city="Kurukshetra",
                postal_code="136118",
                latitude=Decimal("29.960000") + Decimal(index) / 1000,
                longitude=Decimal("76.830000") + Decimal(index) / 1000,
                service_radius_km=Decimal("10"),
                delivery_fee_paise=0 if index % 3 == 0 else 2500,
                minimum_order_paise=19900 if is_grocery else 9900,
                supports_delivery=True,
                supports_pickup=True,
                is_open=index % 7 != 0,
                status=ShopStatus.ACTIVE,
                logo_url=image_url(
                    "shop-fresh-logo.webp" if is_grocery else "shop-golden-logo.webp"
                ),
                banner_url=image_url(banner),
                rating_average=Decimal("4.10") + Decimal(index % 9) / 10,
                rating_count=75 + index * 17,
            ),
        )
    return result


async def seed_products(
    session: AsyncSession, shops: dict[str, Shop], categories: dict[str, Category]
) -> list[Product]:
    demo_product_ids = [
        demo_id("product", f"{shop_key}:{product_key}")
        for shop_key in shops
        for product_key, *_ in PRODUCTS
    ]
    await session.execute(
        update(Product)
        .where(Product.id.in_(demo_product_ids))
        .values(is_available=False, is_featured=False)
    )
    seeded = []
    for shop_index, (shop_key, shop) in enumerate(shops.items()):
        for product_index, (key, name, category_key, price, filename) in enumerate(PRODUCTS):
            if category_key not in SHOP_CATEGORY_PORTFOLIOS[shop_key]:
                continue
            product_key = f"{shop_key}:{key}"
            product = await upsert(
                session,
                Product(
                    id=demo_id("product", product_key),
                    shop_id=shop.id,
                    category_id=categories[category_key].id,
                    name=name,
                    description=f"Quality {name.lower()} prepared or selected by {shop.name}.",
                    ingredients="Full ingredient and allergen information available from the shop.",
                    price_paise=price + shop_index * 200,
                    # MRP is set so the customer-facing saving is a true 10%.
                    compare_at_price_paise=(price + shop_index * 200) * 100 // 90,
                    stock_quantity=35 + product_index,
                    is_available=True,
                    is_featured=product_index < 5,
                    is_deleted=False,
                    image_urls=[image_url(filename)],
                    rating_average=Decimal("4.20") + Decimal(product_index % 7) / 10,
                    rating_count=40 + shop_index * 11 + product_index * 7,
                ),
            )
            seeded.append(product)
    return seeded


async def seed_campaigns(session: AsyncSession, shops: dict[str, Shop]) -> list[RewardCampaign]:
    now = datetime.now(UTC)
    campaigns = []
    prizes = ["Free Pastry", "20% Off", "Free Delivery", "₹100 Cashback", "Buy 1 Get 1"]
    for index, (shop_key, shop) in enumerate(shops.items()):
        campaigns.append(
            await upsert(
                session,
                RewardCampaign(
                    id=demo_id("campaign", shop_key),
                    shop_id=shop.id,
                    title=f"{shop.name} Scratch & Win",
                    area=shop.area,
                    city=shop.city,
                    starts_at=now - timedelta(days=7 + index),
                    ends_at=now + timedelta(days=60 + index),
                    reward_valid_until=date.today() + timedelta(days=120 + index),
                    total_inventory=1000,
                    claimed_count=15 + index,
                    per_user_limit=4,
                    prizes=[
                        {
                            "label": prizes[index % len(prizes)],
                            "weight": 15,
                            "image_url": image_url("reward-pastry.webp"),
                        },
                        {"label": "15% Off", "weight": 35},
                        {"label": "5% Off", "weight": 50},
                    ],
                    artwork_url=image_url("reward-scratch.webp"),
                    status="active",
                ),
            )
        )
    return campaigns


async def seed_promotions(session: AsyncSession, shops: dict[str, Shop]) -> None:
    banners = [
        "shop-golden-banner.webp",
        "shop-fresh-banner.webp",
        "shop-restaurant-banner.webp",
        "shop-fashion-banner.webp",
        "shop-electronics-banner.webp",
        "shop-cafe-banner.webp",
    ]
    for index, (shop_key, shop) in enumerate(shops.items()):
        await upsert(
            session,
            Promotion(
                id=demo_id("promotion", shop_key),
                title=f"Up to {20 + index % 5 * 10}% off at {shop.name}",
                subtitle="Limited-time local offer",
                image_url=image_url(banners[index % len(banners)]),
                action_type="shop",
                action_value=str(shop.id),
                placement="hero",
                sort_order=index + 1,
                target_city=shop.city,
                target_area=shop.area,
                is_active=True,
            ),
        )

    for index, (key, title, subtitle, filename, shop_key) in enumerate(OFFER_PROMOTIONS, start=1):
        shop = shops[shop_key]
        await upsert(
            session,
            Promotion(
                id=demo_id("promotion-offer", key),
                title=title,
                subtitle=subtitle,
                image_url=image_url(filename),
                action_type="shop",
                action_value=str(shop.id),
                placement="offer",
                sort_order=index,
                target_city=shop.city,
                is_active=True,
            ),
        )


async def seed_reels(session: AsyncSession, shops: dict[str, Shop]) -> list[Reel]:
    """Seed published media without overwriting engagement accumulated in development."""
    now = datetime.now(UTC)
    seeded = []
    for priority, (
        key,
        title,
        caption,
        category,
        shop_key,
        media_filename,
        poster_filename,
    ) in enumerate(REELS, start=1):
        reel_id = demo_id("reel", key)
        reel = await session.get(Reel, reel_id)
        values = {
            "shop_id": shops[shop_key].id,
            "product_id": None,
            "title": title,
            "caption": caption,
            "category": category,
            "media_type": ReelMediaType.VIDEO,
            "media_url": image_url(media_filename),
            "poster_url": image_url(poster_filename),
            "cta_type": ReelCTAType.SHOP,
            "cta_value": str(shops[shop_key].id),
            "status": ReelStatus.ACTIVE,
            "priority": priority,
            "starts_at": now - timedelta(days=1),
            "ends_at": now + timedelta(days=365),
            "published_at": now - timedelta(minutes=priority),
        }
        if reel is None:
            reel = Reel(id=reel_id, **values)
            session.add(reel)
        else:
            for field, value in values.items():
                setattr(reel, field, value)
        seeded.append(reel)
    return seeded


async def seed_customer_collections(
    session: AsyncSession,
    customer: User,
    shops: list[Shop],
    products: list[Product],
    campaigns: list[RewardCampaign],
) -> None:
    customer_key = str(customer.id)
    now = datetime.now(UTC)

    # Delivery addresses are customer-owned personal data, never demo content.
    demo_address_ids = [demo_id("address", f"{customer_key}:{index}") for index in range(15)]
    await session.execute(
        update(Order)
        .where(Order.address_id.in_(demo_address_ids))
        .values(address_id=None, fulfillment_type=FulfillmentType.PICKUP)
    )
    await session.execute(delete(Address).where(Address.id.in_(demo_address_ids)))
    await session.flush()

    for index, shop in enumerate(shops[:15]):
        await upsert(
            session,
            Favorite(
                id=demo_id("favorite", f"{customer_key}:{shop.id}"),
                user_id=customer.id,
                shop_id=shop.id,
                created_at=now - timedelta(days=index),
            ),
        )

    cart = await upsert(
        session,
        Cart(
            id=demo_id("cart", customer_key),
            user_id=customer.id,
            shop_id=shops[0].id,
        ),
    )
    await session.flush()
    cart_products = [product for product in products if product.shop_id == shops[0].id][:20]
    for index, product in enumerate(cart_products):
        await upsert(
            session,
            CartItem(
                id=demo_id("cart-item", f"{customer_key}:{product.id}"),
                cart_id=cart.id,
                product_id=product.id,
                quantity=1 + index % 3,
            ),
        )

    for index in range(DEMO_SIZE):
        shop = shops[index]
        product = next(item for item in products if item.shop_id == shop.id)
        unit_price = product.price_paise
        quantity = 1 + index % 3
        subtotal = unit_price * quantity
        delivery_fee = shop.delivery_fee_paise
        status_value = [
            OrderStatus.COMPLETED,
            OrderStatus.COMPLETED,
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.PREPARING,
            OrderStatus.ACCEPTED,
        ][index % 5]
        await upsert(
            session,
            Order(
                id=demo_id("order", f"{customer_key}:{index}"),
                order_number=f"DEMO-{str(customer.id)[:4].upper()}-{index + 1:04d}",
                customer_id=customer.id,
                shop_id=shop.id,
                address_id=None,
                status=status_value,
                fulfillment_type=FulfillmentType.PICKUP,
                payment_method="cod" if index % 2 == 0 else "online",
                subtotal_paise=subtotal,
                delivery_fee_paise=delivery_fee,
                total_paise=subtotal + delivery_fee,
                idempotency_key=f"demo-{customer_key}-{index}",
                snapshot={
                    "shop": {"id": str(shop.id), "name": shop.name},
                    "items": [
                        {
                            "product_id": str(product.id),
                            "name": product.name,
                            "image_url": product.image_urls[0],
                            "unit_price_paise": unit_price,
                            "quantity": quantity,
                            "total_paise": subtotal,
                        }
                    ],
                },
                completed_at=now - timedelta(days=index)
                if status_value == OrderStatus.COMPLETED
                else None,
                created_at=now - timedelta(days=index),
            ),
        )

    for index, campaign in enumerate(campaigns[:15]):
        await upsert(
            session,
            RewardClaim(
                id=demo_id("reward-claim", f"{customer_key}:{campaign.id}"),
                campaign_id=campaign.id,
                user_id=customer.id,
                claim_sequence=1,
                prize=campaign.prizes[0],
                status="claimed",
                revealed_at=now - timedelta(days=index),
                created_at=now - timedelta(days=index),
            ),
        )

    notification_messages = [
        ("Order update", "Your order is being prepared."),
        ("Deal unlocked", "A new local offer is available near you."),
        ("Reward reminder", "Your scratch-card reward is ready to use."),
        ("Fresh arrivals", "New products were added by a favorite shop."),
    ]
    for index in range(DEMO_SIZE):
        title, body = notification_messages[index % len(notification_messages)]
        await upsert(
            session,
            Notification(
                id=demo_id("notification", f"{customer_key}:{index}"),
                user_id=customer.id,
                title=f"{title} #{index + 1}",
                body=body,
                data={"screen": "home", "demo": True},
                read_at=now - timedelta(days=index) if index % 3 == 0 else None,
                created_at=now - timedelta(hours=index * 6),
            ),
        )


async def seed_demo_data() -> None:
    if settings.environment == "production":
        raise RuntimeError("Demo data seeding is forbidden in production")
    if not settings.demo_data_enabled:
        raise RuntimeError("Set DEMO_DATA_ENABLED=true to seed demo data")

    async with AsyncSessionLocal() as session:
        users = await seed_users(session)
        await session.flush()
        categories = await seed_categories(session)
        await session.flush()
        shops_by_key = await seed_shops(session, users)
        await session.flush()
        products = await seed_products(session, shops_by_key, categories)
        await session.flush()
        campaigns = await seed_campaigns(session, shops_by_key)
        await seed_promotions(session, shops_by_key)
        reels = await seed_reels(session, shops_by_key)
        await session.flush()

        customers = list(
            (await session.scalars(select(User).where(User.role == UserRole.CUSTOMER))).all()
        )
        shops = list(shops_by_key.values())
        for customer in customers:
            await seed_customer_collections(session, customer, shops, products, campaigns)
            await session.flush()

        await session.commit()
    print(
        f"Demo marketplace seeded for {settings.environment}: "
        f"{len(categories)} categories, {len(shops_by_key)} shops, "
        f"{len(products)} products, {len(campaigns)} campaigns, "
        f"{len(reels)} reels, "
        f"{len(customers)} customer accounts enriched"
    )


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
