from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentCustomer
from app.core.database import get_db
from app.core.exceptions import ConflictException, NotFoundException
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
    ShopStatus,
)
from app.schemas.common import MessageResponse
from app.schemas.marketplace import (
    AddressCreate,
    AddressResponse,
    CartItemInput,
    CartItemUpdate,
    CartResponse,
    CampaignResponse,
    CategoryResponse,
    CheckoutRequest,
    CustomerHomeResponse,
    OrderResponse,
    ProductResponse,
    PromotionResponse,
    RewardClaimResponse,
    ShopProductSearchResult,
    ShopResponse,
    ShopStorefrontResponse,
)
from app.services.marketplace_service import MarketplaceService

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


async def enriched_shops(db: AsyncSession, shops: list[Shop]) -> list[ShopResponse]:
    """Add storefront summary data without duplicating it in the shops table."""
    if not shops:
        return []
    shop_ids = [shop.id for shop in shops]
    rows = (
        await db.execute(
            select(
                Product.shop_id,
                Category.name,
                Product.price_paise,
                Product.compare_at_price_paise,
            )
            .join(Category, Category.id == Product.category_id)
            .where(
                Product.shop_id.in_(shop_ids),
                Product.is_deleted.is_(False),
                Product.is_available.is_(True),
                Category.is_active.is_(True),
            )
            .order_by(Category.sort_order, Category.name)
        )
    ).all()
    category_names: dict[UUID, list[str]] = {shop_id: [] for shop_id in shop_ids}
    discounts: dict[UUID, int] = {shop_id: 0 for shop_id in shop_ids}
    for shop_id, category_name, price, compare_at_price in rows:
        if category_name not in category_names[shop_id]:
            category_names[shop_id].append(category_name)
        if compare_at_price and compare_at_price > price:
            discount = round((compare_at_price - price) * 100 / compare_at_price)
            discounts[shop_id] = max(discounts[shop_id], discount)
    return [
        ShopResponse.model_validate(shop).model_copy(
            update={
                "category_names": category_names[shop.id],
                "offer_label": f"{discounts[shop.id]}% OFF" if discounts[shop.id] else None,
            }
        )
        for shop in shops
    ]


async def active_promotions(
    db: AsyncSession, placement: Literal["hero", "offer"] | None = None
) -> list[Promotion]:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    query = select(Promotion).where(
        Promotion.is_active.is_(True),
        or_(Promotion.starts_at.is_(None), Promotion.starts_at <= now),
        or_(Promotion.ends_at.is_(None), Promotion.ends_at >= now),
    )
    if placement:
        query = query.where(Promotion.placement == placement)
    query = query.order_by(Promotion.sort_order, Promotion.created_at.desc())
    return list((await db.scalars(query)).all())


@router.get("/promotions", response_model=list[PromotionResponse])
async def promotions(db: DB, placement: Literal["hero", "offer"] | None = Query(default=None)):
    return await active_promotions(db, placement)


@router.get("/home", response_model=CustomerHomeResponse)
async def customer_home(db: DB):
    promotion_items = await active_promotions(db, "hero")
    offer_items = await active_promotions(db, "offer")
    category_items = list(
        (
            await db.scalars(
                select(Category)
                .where(Category.is_active.is_(True))
                .order_by(Category.sort_order, Category.name)
            )
        ).all()
    )
    shop_items = list(
        (
            await db.scalars(
                select(Shop)
                .where(Shop.status == ShopStatus.ACTIVE)
                .order_by(Shop.rating_average.desc())
                .limit(20)
            )
        ).all()
    )
    product_items = list(
        (
            await db.scalars(
                select(Product)
                .join(Shop)
                .where(
                    Product.is_deleted.is_(False),
                    Product.is_available.is_(True),
                    Shop.status == ShopStatus.ACTIVE,
                )
                .order_by(Product.is_featured.desc(), Product.rating_average.desc())
                .limit(20)
            )
        ).all()
    )
    return CustomerHomeResponse(
        promotions=promotion_items,
        offers=offer_items,
        categories=category_items,
        shops=shop_items,
        featured_products=product_items,
    )


async def build_cart_response(cart: Cart, db: AsyncSession) -> CartResponse:
    rows = (
        await db.execute(
            select(CartItem, Product)
            .join(Product, Product.id == CartItem.product_id)
            .where(CartItem.cart_id == cart.id)
            .order_by(CartItem.created_at)
        )
    ).all()
    shop = await db.get(Shop, cart.shop_id)
    subtotal = sum(item.quantity * product.price_paise for item, product in rows)
    delivery_fee = shop.delivery_fee_paise if shop and shop.supports_delivery else 0
    return CartResponse(
        id=cart.id,
        shop_id=cart.shop_id,
        items=[
            {
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "product": product,
            }
            for item, product in rows
        ],
        subtotal_paise=subtotal,
        delivery_fee_paise=delivery_fee,
        total_paise=subtotal + delivery_fee,
    )


@router.get("/categories", response_model=list[CategoryResponse])
async def categories(db: DB, parent_id: UUID | None = None):
    query = select(Category).where(Category.is_active.is_(True))
    if parent_id:
        query = query.where(Category.parent_id == parent_id)
    return list((await db.scalars(query.order_by(Category.sort_order, Category.name))).all())


@router.get("/shops", response_model=list[ShopResponse])
async def shops(
    db: DB,
    city: str | None = None,
    area: str | None = None,
    q: str | None = None,
    category_id: UUID | None = None,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(Shop).where(Shop.status == ShopStatus.ACTIVE)
    if category_id:
        query = (
            query.join(Product, Product.shop_id == Shop.id)
            .where(
                Product.category_id == category_id,
                Product.is_deleted.is_(False),
                Product.is_available.is_(True),
            )
            .distinct()
        )
    if city:
        query = query.where(func.lower(Shop.city) == city.lower())
    if area:
        query = query.where(func.lower(Shop.area) == area.lower())
    if q:
        query = query.where(Shop.name.ilike(f"%{q}%"))
    items = list(
        (await db.scalars(query.order_by(Shop.name).limit(limit).offset(offset))).all()
    )
    return await enriched_shops(db, items)


@router.get("/search/shops", response_model=list[ShopProductSearchResult])
async def search_shops(
    db: DB,
    q: str = Query(min_length=2, max_length=100),
    city: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    search_term = q.strip()
    if len(search_term) < 2:
        return []

    escaped_term = (
        search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    exact_term = search_term.lower()
    prefix_pattern = f"{escaped_term}%"
    contains_pattern = f"%{escaped_term}%"
    name_matches = Product.name.ilike(contains_pattern, escape="\\")
    description_matches = Product.description.ilike(contains_pattern, escape="\\")
    match_rank = case(
        (func.lower(Product.name) == exact_term, 0),
        (Product.name.ilike(prefix_pattern, escape="\\"), 1),
        (name_matches, 2),
        else_=3,
    )

    ranked_matches = (
        select(
            Shop.id.label("shop_id"),
            Product.id.label("product_id"),
            match_rank.label("match_rank"),
            func.row_number()
            .over(
                partition_by=Shop.id,
                order_by=(
                    match_rank,
                    Product.is_featured.desc(),
                    Product.rating_average.desc(),
                    Product.name,
                    Product.id,
                ),
            )
            .label("position"),
        )
        .select_from(Product)
        .join(Shop, Shop.id == Product.shop_id)
        .where(
            Product.is_deleted.is_(False),
            Product.is_available.is_(True),
            Shop.status == ShopStatus.ACTIVE,
            or_(name_matches, description_matches),
        )
    )
    if city:
        ranked_matches = ranked_matches.where(func.lower(Shop.city) == city.strip().lower())
    ranked_matches = ranked_matches.subquery()

    rows = (
        await db.execute(
            select(Shop, Product)
            .select_from(Shop)
            .join(ranked_matches, ranked_matches.c.shop_id == Shop.id)
            .join(Product, Product.id == ranked_matches.c.product_id)
            .where(ranked_matches.c.position == 1)
            .order_by(
                ranked_matches.c.match_rank,
                Shop.rating_average.desc(),
                Shop.name,
                Shop.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    if not rows:
        return []

    enriched = await enriched_shops(db, [shop for shop, _ in rows])
    enriched_by_id = {shop.id: shop for shop in enriched}
    return [
        ShopProductSearchResult(
            shop=enriched_by_id[shop.id],
            matched_product=ProductResponse.model_validate(product),
        )
        for shop, product in rows
    ]


@router.get("/shops/{shop_id}", response_model=ShopResponse)
async def shop_detail(shop_id: UUID, db: DB):
    shop = await db.get(Shop, shop_id)
    if not shop or shop.status != ShopStatus.ACTIVE:
        raise NotFoundException("Shop")
    return (await enriched_shops(db, [shop]))[0]


@router.get("/shops/{shop_id}/storefront", response_model=ShopStorefrontResponse)
async def shop_storefront(shop_id: UUID, db: DB):
    shop = await db.get(Shop, shop_id)
    if not shop or shop.status != ShopStatus.ACTIVE:
        raise NotFoundException("Shop")
    product_items = list(
        (
            await db.scalars(
                select(Product)
                .where(
                    Product.shop_id == shop_id,
                    Product.is_deleted.is_(False),
                    Product.is_available.is_(True),
                )
                .order_by(Product.is_featured.desc(), Product.name)
                .limit(100)
            )
        ).all()
    )
    category_ids = {item.category_id for item in product_items if item.category_id}
    category_items = (
        list(
            (
                await db.scalars(
                    select(Category)
                    .where(Category.id.in_(category_ids), Category.is_active.is_(True))
                    .order_by(Category.sort_order, Category.name)
                )
            ).all()
        )
        if category_ids
        else []
    )
    return ShopStorefrontResponse(
        shop=(await enriched_shops(db, [shop]))[0],
        categories=[CategoryResponse.model_validate(item) for item in category_items],
        products=[ProductResponse.model_validate(item) for item in product_items],
    )


@router.get("/products", response_model=list[ProductResponse])
async def products(
    db: DB,
    shop_id: UUID | None = None,
    category_id: UUID | None = None,
    q: str | None = None,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
):
    query = (
        select(Product)
        .join(Shop)
        .where(
            Product.is_deleted.is_(False),
            Product.is_available.is_(True),
            Shop.status == ShopStatus.ACTIVE,
        )
    )
    if shop_id:
        query = query.where(Product.shop_id == shop_id)
    if category_id:
        query = query.where(Product.category_id == category_id)
    if q:
        query = query.where(or_(Product.name.ilike(f"%{q}%"), Product.description.ilike(f"%{q}%")))
    return list(
        (
            await db.scalars(
                query.order_by(Product.is_featured.desc(), Product.name).limit(limit).offset(offset)
            )
        ).all()
    )


@router.get("/products/{product_id}", response_model=ProductResponse)
async def product_detail(product_id: UUID, db: DB):
    product = await db.get(Product, product_id)
    if not product or product.is_deleted or not product.is_available:
        raise NotFoundException("Product")
    return product


@router.post("/addresses", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
async def create_address(data: AddressCreate, user: CurrentCustomer, db: DB):
    address_count = int(
        (
            await db.scalar(
                select(func.count()).select_from(Address).where(Address.user_id == user.id)
            )
        )
        or 0
    )
    if address_count >= 4:
        raise ConflictException("A customer can save at most four addresses")
    if data.is_default:
        for item in (await db.scalars(select(Address).where(Address.user_id == user.id))).all():
            item.is_default = False
    address = Address(user_id=user.id, **data.model_dump())
    db.add(address)
    await db.flush()
    return address


@router.get("/addresses", response_model=list[AddressResponse])
async def addresses(user: CurrentCustomer, db: DB):
    return list(
        (
            await db.scalars(
                select(Address)
                .where(Address.user_id == user.id)
                .order_by(Address.is_default.desc())
            )
        ).all()
    )


@router.put("/addresses/{address_id}", response_model=AddressResponse)
async def update_address(address_id: UUID, data: AddressCreate, user: CurrentCustomer, db: DB):
    address = await db.get(Address, address_id)
    if not address or address.user_id != user.id:
        raise NotFoundException("Address")
    if data.is_default:
        for item in (await db.scalars(select(Address).where(Address.user_id == user.id))).all():
            item.is_default = item.id == address.id
    for key, value in data.model_dump().items():
        setattr(address, key, value)
    await db.flush()
    return address


@router.delete("/addresses/{address_id}", response_model=MessageResponse)
async def delete_address(address_id: UUID, user: CurrentCustomer, db: DB):
    address = await db.get(Address, address_id)
    if not address or address.user_id != user.id:
        raise NotFoundException("Address")
    if await db.scalar(
        select(func.count()).select_from(Order).where(Order.address_id == address.id)
    ):
        raise ConflictException("Address is referenced by order history")
    was_default = address.is_default
    await db.delete(address)
    await db.flush()
    if was_default:
        next_address = (
            await db.scalars(
                select(Address)
                .where(Address.user_id == user.id)
                .order_by(Address.created_at.desc())
                .limit(1)
            )
        ).first()
        if next_address:
            next_address.is_default = True
    return MessageResponse(message="Address deleted")


@router.post("/favorites/{shop_id}", response_model=MessageResponse)
async def favorite(shop_id: UUID, user: CurrentCustomer, db: DB):
    existing = (
        await db.execute(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.shop_id == shop_id)
        )
    ).scalar_one_or_none()
    if not existing:
        db.add(Favorite(user_id=user.id, shop_id=shop_id))
    return MessageResponse(message="Shop added to favorites")


@router.delete("/favorites/{shop_id}", response_model=MessageResponse)
async def unfavorite(shop_id: UUID, user: CurrentCustomer, db: DB):
    item = (
        await db.execute(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.shop_id == shop_id)
        )
    ).scalar_one_or_none()
    if item:
        await db.delete(item)
    return MessageResponse(message="Shop removed from favorites")


@router.get("/favorites", response_model=list[ShopResponse])
async def favorites(user: CurrentCustomer, db: DB):
    query = (
        select(Shop)
        .join(Favorite, Favorite.shop_id == Shop.id)
        .where(Favorite.user_id == user.id, Shop.status == ShopStatus.ACTIVE)
        .order_by(Favorite.created_at.desc())
    )
    return list((await db.scalars(query)).all())


@router.get("/cart", response_model=CartResponse | None)
async def get_cart(user: CurrentCustomer, db: DB):
    cart = (
        await db.scalars(
            select(Cart).where(Cart.user_id == user.id).order_by(Cart.updated_at.desc())
        )
    ).first()
    if not cart:
        return None
    return await build_cart_response(cart, db)


@router.post("/cart/items", status_code=status.HTTP_201_CREATED)
async def add_cart_item(data: CartItemInput, user: CurrentCustomer, db: DB):
    product = await db.get(Product, data.product_id)
    if not product or product.is_deleted or not product.is_available:
        raise NotFoundException("Product")
    carts = (await db.scalars(select(Cart).where(Cart.user_id == user.id))).all()
    if carts and all(cart.shop_id != product.shop_id for cart in carts):
        raise ConflictException("Clear the current shop cart before adding another shop")
    cart = next((c for c in carts if c.shop_id == product.shop_id), None)
    if not cart:
        cart = Cart(user_id=user.id, shop_id=product.shop_id)
        db.add(cart)
        await db.flush()
    item = (
        await db.execute(
            select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id)
        )
    ).scalar_one_or_none()
    if item:
        item.quantity = data.quantity
    else:
        item = CartItem(cart_id=cart.id, product_id=product.id, quantity=data.quantity)
        db.add(item)
    await db.flush()
    return {"cart_id": cart.id, "item_id": item.id, "quantity": item.quantity}


@router.patch("/cart/items/{item_id}", response_model=CartResponse)
async def update_cart_item(item_id: UUID, data: CartItemUpdate, user: CurrentCustomer, db: DB):
    row = (
        await db.execute(
            select(CartItem, Cart)
            .join(Cart, Cart.id == CartItem.cart_id)
            .where(CartItem.id == item_id, Cart.user_id == user.id)
        )
    ).one_or_none()
    if not row:
        raise NotFoundException("Cart item")
    item, cart = row
    item.quantity = data.quantity
    await db.flush()
    return await build_cart_response(cart, db)


@router.delete("/cart/items/{item_id}", response_model=MessageResponse)
async def remove_cart_item(item_id: UUID, user: CurrentCustomer, db: DB):
    item = (
        await db.scalars(
            select(CartItem)
            .join(Cart, Cart.id == CartItem.cart_id)
            .where(CartItem.id == item_id, Cart.user_id == user.id)
        )
    ).one_or_none()
    if not item:
        raise NotFoundException("Cart item")
    await db.delete(item)
    return MessageResponse(message="Cart item removed")


@router.delete("/cart", response_model=MessageResponse)
async def clear_cart(user: CurrentCustomer, db: DB):
    carts = (await db.scalars(select(Cart).where(Cart.user_id == user.id))).all()
    for cart in carts:
        await db.delete(cart)
    return MessageResponse(message="Cart cleared")


@router.post("/checkout", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def checkout(
    data: CheckoutRequest,
    user: CurrentCustomer,
    db: DB,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)],
):
    return await MarketplaceService(db).checkout(user, data, idempotency_key)


@router.get("/orders", response_model=list[OrderResponse])
async def orders(user: CurrentCustomer, db: DB):
    return list(
        (
            await db.scalars(
                select(Order).where(Order.customer_id == user.id).order_by(Order.created_at.desc())
            )
        ).all()
    )


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def order_detail(order_id: UUID, user: CurrentCustomer, db: DB):
    order = await db.get(Order, order_id)
    if not order or order.customer_id != user.id:
        raise NotFoundException("Order")
    return order


@router.get("/rewards/campaigns", response_model=list[CampaignResponse])
async def campaigns(user: CurrentCustomer, db: DB, city: str, area: str | None = None):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    query = select(RewardCampaign).where(
        RewardCampaign.city.ilike(city),
        RewardCampaign.status == "active",
        RewardCampaign.starts_at <= now,
        RewardCampaign.ends_at >= now,
    )
    if area:
        query = query.where(RewardCampaign.area.ilike(area))
    return list(
        (await db.scalars(query.order_by(RewardCampaign.ends_at, RewardCampaign.title))).all()
    )


@router.get("/rewards/campaigns/{campaign_id}", response_model=CampaignResponse)
async def campaign_detail(campaign_id: UUID, user: CurrentCustomer, db: DB):
    campaign = await db.get(RewardCampaign, campaign_id)
    if not campaign or campaign.status != "active":
        raise NotFoundException("Reward campaign")
    return campaign


@router.post(
    "/rewards/{campaign_id}/claim",
    response_model=RewardClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
async def claim(campaign_id: UUID, user: CurrentCustomer, db: DB):
    return await MarketplaceService(db).claim_reward(user, campaign_id)


@router.get("/rewards/claims", response_model=list[RewardClaimResponse])
async def reward_claims(user: CurrentCustomer, db: DB):
    query = (
        select(RewardClaim)
        .where(RewardClaim.user_id == user.id)
        .order_by(RewardClaim.created_at.desc())
    )
    return list((await db.scalars(query)).all())


@router.get("/rewards/claims/{claim_id}", response_model=RewardClaimResponse)
async def reward_claim_detail(claim_id: UUID, user: CurrentCustomer, db: DB):
    reward_claim = await db.get(RewardClaim, claim_id)
    if not reward_claim or reward_claim.user_id != user.id:
        raise NotFoundException("Reward claim")
    return reward_claim


@router.get("/notifications")
async def notifications(user: CurrentCustomer, db: DB, limit: int = Query(50, le=100)):
    return list(
        (
            await db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


@router.patch("/notifications/{notification_id}/read")
async def read_notification(notification_id: UUID, user: CurrentCustomer, db: DB):
    item = await db.get(Notification, notification_id)
    if not item or item.user_id != user.id:
        raise NotFoundException("Notification")
    from datetime import UTC, datetime

    item.read_at = datetime.now(UTC)
    return {"read": True}
