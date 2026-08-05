"""Seed only the API-backed advertising reels in a non-production database."""

import asyncio

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.marketplace import Shop
from seed_demo_data import REELS, demo_id, seed_reels


async def seed_demo_reels() -> None:
    settings = get_settings()
    if settings.environment == "production":
        raise RuntimeError("Demo reel seeding is forbidden in production")
    if not settings.demo_data_enabled:
        raise RuntimeError("Set DEMO_DATA_ENABLED=true to seed demo reels")

    shop_keys = {item[4] for item in REELS}
    async with AsyncSessionLocal() as session:
        shops = {
            key: shop
            for key in shop_keys
            if (shop := await session.get(Shop, demo_id("shop", key))) is not None
        }
        missing = sorted(shop_keys - shops.keys())
        if missing:
            raise RuntimeError(
                "Missing demo shops; run scripts/seed_demo_data.py first: " + ", ".join(missing)
            )
        reels = await seed_reels(session, shops)
        await session.commit()

    print(f"Seeded {len(reels)} API-backed demo reels")


if __name__ == "__main__":
    asyncio.run(seed_demo_reels())
