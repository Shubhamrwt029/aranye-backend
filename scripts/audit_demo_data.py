"""Report non-sensitive demo collection counts for release readiness."""

import asyncio

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.marketplace import (
    Address,
    Cart,
    CartItem,
    Category,
    Favorite,
    Notification,
    Order,
    Product,
    Promotion,
    RewardCampaign,
    RewardClaim,
    Shop,
)
from app.models.user import User, UserRole


async def scalar_count(session, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    return int((await session.scalar(query)) or 0)


async def audit_demo_data() -> None:
    async with AsyncSessionLocal() as session:
        global_counts = {
            "categories": await scalar_count(session, Category, Category.is_active.is_(True)),
            "shops": await scalar_count(session, Shop),
            "products": await scalar_count(session, Product, Product.is_available.is_(True)),
            "campaigns": await scalar_count(
                session, RewardCampaign, RewardCampaign.status == "active"
            ),
            "promotions": await scalar_count(session, Promotion, Promotion.is_active.is_(True)),
            "promotion_heroes": await scalar_count(
                session,
                Promotion,
                Promotion.is_active.is_(True),
                Promotion.placement == "hero",
            ),
            "promotion_offers": await scalar_count(
                session,
                Promotion,
                Promotion.is_active.is_(True),
                Promotion.placement == "offer",
            ),
        }
        category_shop_counts = dict(
            (
                await session.execute(
                    select(Category.slug, func.count(func.distinct(Shop.id)))
                    .join(Product, Product.category_id == Category.id)
                    .join(Shop, Shop.id == Product.shop_id)
                    .where(
                        Category.is_active.is_(True),
                        Product.is_available.is_(True),
                    )
                    .group_by(Category.slug)
                    .order_by(Category.slug)
                )
            ).all()
        )
        customers = list(
            (await session.scalars(select(User.id).where(User.role == UserRole.CUSTOMER))).all()
        )
        per_customer = []
        for customer_id in customers:
            cart_items = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(CartItem)
                        .join(Cart, Cart.id == CartItem.cart_id)
                        .where(Cart.user_id == customer_id)
                    )
                )
                or 0
            )
            per_customer.append(
                {
                    "addresses": await scalar_count(
                        session, Address, Address.user_id == customer_id
                    ),
                    "favorites": await scalar_count(
                        session, Favorite, Favorite.user_id == customer_id
                    ),
                    "cart_items": cart_items,
                    "orders": await scalar_count(session, Order, Order.customer_id == customer_id),
                    "reward_claims": await scalar_count(
                        session, RewardClaim, RewardClaim.user_id == customer_id
                    ),
                    "notifications": await scalar_count(
                        session, Notification, Notification.user_id == customer_id
                    ),
                }
            )
        minimums = (
            {key: min(item[key] for item in per_customer) for key in per_customer[0]}
            if per_customer
            else {}
        )
        print(
            {
                "global": global_counts,
                "category_shops": category_shop_counts,
                "customers": len(customers),
                "minimums": minimums,
            }
        )


if __name__ == "__main__":
    asyncio.run(audit_demo_data())
