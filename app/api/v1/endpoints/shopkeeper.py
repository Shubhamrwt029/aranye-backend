from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentShopkeeper
from app.core.database import get_db
from app.core.encryption import encrypt_value
from app.core.exceptions import ConflictException, NotFoundException
from app.models.marketplace import (
    BankAccount,
    Order,
    OrderStatus,
    Product,
    RewardCampaign,
    Shop,
    ShopHour,
)
from app.schemas.marketplace import (
    BankAccountInput,
    CampaignCreate,
    CampaignResponse,
    OrderResponse,
    OrderStatusUpdate,
    ProductCreate,
    ProductResponse,
    ShopCreate,
    ShopHourInput,
    ShopResponse,
)
from app.services.marketplace_service import MarketplaceService

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/shop", response_model=ShopResponse, status_code=status.HTTP_201_CREATED)
async def create_shop(data: ShopCreate, user: CurrentShopkeeper, db: DB):
    if (await db.execute(select(Shop.id).where(Shop.owner_id == user.id))).scalar_one_or_none():
        raise ConflictException("Shop already exists")
    shop = Shop(owner_id=user.id, **data.model_dump())
    db.add(shop)
    await db.flush()
    return shop


@router.get("/shop", response_model=ShopResponse)
async def my_shop(user: CurrentShopkeeper, db: DB):
    return await MarketplaceService(db).get_owned_shop(user)


@router.put("/shop/hours")
async def update_hours(data: list[ShopHourInput], user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    if len({item.weekday for item in data}) != len(data):
        raise ConflictException("Duplicate weekday")
    existing = {
        h.weekday: h
        for h in (await db.scalars(select(ShopHour).where(ShopHour.shop_id == shop.id))).all()
    }
    for item in data:
        hour = existing.get(item.weekday) or ShopHour(shop_id=shop.id, weekday=item.weekday)
        for key, value in item.model_dump().items():
            setattr(hour, key, value)
        db.add(hour)
    return {"updated": len(data)}


@router.put("/shop/bank-account")
async def bank_account(data: BankAccountInput, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    account = (
        await db.execute(select(BankAccount).where(BankAccount.shop_id == shop.id))
    ).scalar_one_or_none()
    values = {
        "account_holder_name": data.account_holder_name,
        "account_number_encrypted": encrypt_value(data.account_number),
        "account_number_last4": data.account_number[-4:],
        "ifsc_encrypted": encrypt_value(data.ifsc),
        "is_verified": False,
    }
    if account:
        for key, value in values.items():
            setattr(account, key, value)
    else:
        account = BankAccount(shop_id=shop.id, **values)
        db.add(account)
    await MarketplaceService(db).audit(user, "bank_account.updated", "shop", shop.id)
    return {
        "account_holder_name": account.account_holder_name,
        "account_number_masked": f"••••{account.account_number_last4}",
        "is_verified": account.is_verified,
    }


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductCreate, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    product = Product(shop_id=shop.id, **data.model_dump())
    db.add(product)
    await db.flush()
    return product


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(product_id: UUID, data: ProductCreate, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    product = await db.get(Product, product_id)
    if not product or product.shop_id != shop.id:
        raise NotFoundException("Product")
    for key, value in data.model_dump().items():
        setattr(product, key, value)
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: UUID, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    product = await db.get(Product, product_id)
    if not product or product.shop_id != shop.id:
        raise NotFoundException("Product")
    product.is_deleted = True
    product.is_available = False


@router.get("/orders", response_model=list[OrderResponse])
async def orders(user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    return list(
        (
            await db.scalars(
                select(Order).where(Order.shop_id == shop.id).order_by(Order.created_at.desc())
            )
        ).all()
    )


@router.patch("/orders/{order_id}/status", response_model=OrderResponse)
async def order_status(order_id: UUID, data: OrderStatusUpdate, user: CurrentShopkeeper, db: DB):
    return await MarketplaceService(db).transition_order(
        user, order_id, OrderStatus(data.status), data.reason
    )


@router.post(
    "/reward-campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED
)
async def campaign(data: CampaignCreate, user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    item = RewardCampaign(shop_id=shop.id, status="active", **data.model_dump())
    db.add(item)
    await db.flush()
    return item


@router.get("/earnings")
async def earnings(user: CurrentShopkeeper, db: DB):
    shop = await MarketplaceService(db).get_owned_shop(user)
    completed = select(func.coalesce(func.sum(Order.total_paise), 0), func.count(Order.id)).where(
        Order.shop_id == shop.id, Order.status == OrderStatus.COMPLETED
    )
    total, count = (await db.execute(completed)).one()
    return {
        "gross_earnings_paise": total,
        "completed_orders": count,
        "settled_paise": 0,
        "pending_paise": total,
    }
