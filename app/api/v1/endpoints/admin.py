import csv
import io
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdmin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import (
    AppException,
    ConflictException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import hash_password, verify_password
from app.models.marketplace import (
    Address,
    AppSetting,
    AuditLog,
    Cart,
    CartItem,
    Category,
    Favorite,
    MediaAsset,
    Notification,
    NotificationBroadcast,
    Order,
    OrderItem,
    OrderStatus,
    OTPDeliveryEvent,
    Payment,
    PaymentStatus,
    Product,
    Promotion,
    RewardCampaign,
    RewardClaim,
    Shop,
    ShopHour,
    ShopStatus,
)
from app.models.user import RefreshSession, User, UserRole
from app.schemas.admin import (
    AdminCreate,
    AdminPasswordChange,
    AdminPasswordReset,
    AdminStatusAction,
    CampaignAdminCreate,
    CampaignAdminUpdate,
    CategoryAdminUpdate,
    ClaimAction,
    DeleteConfirmation,
    LifecycleAction,
    MarketplaceSettings,
    MediaCompleteRequest,
    MediaPresignRequest,
    OrderAdminAction,
    PaymentAdminAction,
    ProductAdminCreate,
    ProductAdminUpdate,
    PromotionCreate,
    PromotionUpdate,
    ShopAdminUpdate,
    UserAdminUpdate,
)
from app.schemas.marketplace import AddressCreate, CategoryCreate, NotificationCompose
from app.schemas.otp_admin import OTPProviderStatus
from app.services.auth_service import AuthService
from app.services.media_service import MediaService
from app.services.marketplace_service import MarketplaceService

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
settings = get_settings()


def snapshot(item: Any) -> dict[str, Any]:
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


async def page(db: AsyncSession, query, limit: int, offset: int) -> dict[str, Any]:
    total = int(
        (await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))) or 0
    )
    items = list((await db.scalars(query.limit(limit).offset(offset))).all())
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def request_meta(request: Request) -> dict[str, str | None]:
    return {
        "request_id": request.headers.get("X-Request-ID"),
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent", "")[:500] or None,
    }


async def audit(
    db: AsyncSession,
    admin: User,
    request: Request,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None,
    *,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> None:
    await MarketplaceService(db).audit(
        admin,
        action,
        resource_type,
        resource_id,
        before,
        after,
        reason=reason,
        **request_meta(request),
    )


def ensure_fresh(item: Any, expected: datetime | None) -> None:
    if expected and item.updated_at and item.updated_at != expected:
        raise ConflictException("Record changed since it was loaded. Refresh and try again.")


def verify_admin_password(admin: User, password: str) -> None:
    if not admin.hashed_password or not verify_password(password, admin.hashed_password):
        raise UnauthorizedException("Administrator password is incorrect")


def confirm_name(expected: str, supplied: str) -> None:
    if supplied.strip() != expected:
        raise AppException(f'Type "{expected}" exactly to confirm permanent deletion')


@router.get("/dashboard")
async def dashboard(
    _: CurrentAdmin,
    db: DB,
    date_from: date | None = None,
    date_to: date | None = None,
):
    end = datetime.combine(date_to or date.today(), datetime.max.time(), tzinfo=UTC)
    start = datetime.combine(
        date_from or (date.today() - timedelta(days=29)), datetime.min.time(), tzinfo=UTC
    )

    async def count(model, *where):
        return int((await db.scalar(select(func.count()).select_from(model).where(*where))) or 0)

    orders = list(
        (
            await db.scalars(
                select(Order).where(Order.created_at >= start, Order.created_at <= end)
            )
        ).all()
    )
    users = list(
        (
            await db.scalars(select(User).where(User.created_at >= start, User.created_at <= end))
        ).all()
    )
    days = [
        (start + timedelta(days=index)).date()
        for index in range((end.date() - start.date()).days + 1)
    ]
    trend = []
    for day in days:
        day_orders = [item for item in orders if item.created_at.date() == day]
        trend.append(
            {
                "date": day.isoformat(),
                "orders": len(day_orders),
                "revenue_paise": sum(item.total_paise for item in day_orders),
                "new_users": sum(item.created_at.date() == day for item in users),
            }
        )
    status_rows = (
        await db.execute(select(Order.status, func.count()).group_by(Order.status))
    ).all()
    return {
        "customers": await count(User, User.role == UserRole.CUSTOMER),
        "shopkeepers": await count(User, User.role == UserRole.SHOPKEEPER),
        "active_shops": await count(Shop, Shop.status == ShopStatus.ACTIVE),
        "pending_shops": await count(Shop, Shop.status == ShopStatus.PENDING_REVIEW),
        "orders": await count(Order),
        "gross_order_value_paise": int(
            (await db.scalar(select(func.coalesce(func.sum(Order.total_paise), 0)))) or 0
        ),
        "active_campaigns": await count(RewardCampaign, RewardCampaign.status == "active"),
        "payment_failures": await count(Payment, Payment.status == PaymentStatus.FAILED),
        "outstanding_rewards": await count(RewardClaim, RewardClaim.status == "claimed"),
        "trend": trend,
        "order_statuses": {str(key.value): value for key, value in status_rows},
    }


@router.get("/users")
async def users(
    _: CurrentAdmin,
    db: DB,
    role: UserRole | None = None,
    active: bool | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if active is not None:
        query = query.where(User.is_active == active)
    if q:
        query = query.where(
            or_(User.name.ilike(f"%{q}%"), User.phone.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"))
        )
    return await page(db, query.order_by(User.created_at.desc()), limit, offset)


@router.get("/users/{user_id}")
async def user_detail(user_id: UUID, _: CurrentAdmin, db: DB):
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundException("User")
    addresses = list((await db.scalars(select(Address).where(Address.user_id == user.id))).all())
    favorites = list((await db.scalars(select(Favorite).where(Favorite.user_id == user.id))).all())
    carts = list((await db.scalars(select(Cart).where(Cart.user_id == user.id))).all())
    cart_ids = [item.id for item in carts]
    cart_items = (
        list((await db.scalars(select(CartItem).where(CartItem.cart_id.in_(cart_ids)))).all())
        if cart_ids
        else []
    )
    orders = list(
        (
            await db.scalars(
                select(Order)
                .where(Order.customer_id == user.id)
                .order_by(Order.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    claims = list(
        (
            await db.scalars(
                select(RewardClaim)
                .where(RewardClaim.user_id == user.id)
                .order_by(RewardClaim.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    notifications = list(
        (
            await db.scalars(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    sessions = list(
        (
            await db.scalars(
                select(RefreshSession).where(
                    RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)
                )
            )
        ).all()
    )
    return {
        "user": user,
        "addresses": addresses,
        "favorites": favorites,
        "carts": carts,
        "cart_items": cart_items,
        "orders": orders,
        "reward_claims": claims,
        "notifications": notifications,
        "sessions": sessions,
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID, data: UserAdminUpdate, admin: CurrentAdmin, request: Request, db: DB
):
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundException("User")
    ensure_fresh(user, data.expected_updated_at)
    before = snapshot(user)
    for key, value in data.model_dump(
        exclude={"reason", "expected_updated_at"}, exclude_unset=True
    ).items():
        setattr(user, key, value)
    await audit(
        db,
        admin,
        request,
        "user.updated",
        "user",
        user.id,
        before=before,
        after=snapshot(user),
        reason=data.reason,
    )
    return user


@router.post("/users/{user_id}/addresses", status_code=status.HTTP_201_CREATED)
async def create_user_address(
    user_id: UUID, data: AddressCreate, admin: CurrentAdmin, request: Request, db: DB
):
    if not await db.get(User, user_id):
        raise NotFoundException("User")
    address = Address(user_id=user_id, **data.model_dump())
    db.add(address)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "address.created",
        "address",
        address.id,
        after=snapshot(address),
        reason="Admin support action",
    )
    return address


@router.put("/users/{user_id}/addresses/{address_id}")
async def update_user_address(
    user_id: UUID,
    address_id: UUID,
    data: AddressCreate,
    admin: CurrentAdmin,
    request: Request,
    db: DB,
):
    address = await db.get(Address, address_id)
    if not address or address.user_id != user_id:
        raise NotFoundException("Address")
    before = snapshot(address)
    for key, value in data.model_dump().items():
        setattr(address, key, value)
    await audit(
        db,
        admin,
        request,
        "address.updated",
        "address",
        address.id,
        before=before,
        after=snapshot(address),
        reason="Admin support action",
    )
    return address


@router.delete("/users/{user_id}/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_address(
    user_id: UUID, address_id: UUID, admin: CurrentAdmin, request: Request, db: DB
):
    address = await db.get(Address, address_id)
    if not address or address.user_id != user_id:
        raise NotFoundException("Address")
    if await db.scalar(
        select(func.count()).select_from(Order).where(Order.address_id == address.id)
    ):
        raise ConflictException("Address is referenced by order history")
    await audit(
        db,
        admin,
        request,
        "address.deleted",
        "address",
        address.id,
        before=snapshot(address),
        reason="Admin support action",
    )
    await db.delete(address)


@router.post("/users/{user_id}/favorites/{shop_id}")
async def add_user_favorite(
    user_id: UUID, shop_id: UUID, admin: CurrentAdmin, request: Request, db: DB
):
    existing = (
        await db.execute(
            select(Favorite).where(Favorite.user_id == user_id, Favorite.shop_id == shop_id)
        )
    ).scalar_one_or_none()
    if not existing:
        existing = Favorite(user_id=user_id, shop_id=shop_id)
        db.add(existing)
        await db.flush()
    await audit(
        db, admin, request, "favorite.added", "favorite", existing.id, reason="Admin support action"
    )
    return existing


@router.delete("/users/{user_id}/favorites/{shop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_favorite(
    user_id: UUID, shop_id: UUID, admin: CurrentAdmin, request: Request, db: DB
):
    item = (
        await db.execute(
            select(Favorite).where(Favorite.user_id == user_id, Favorite.shop_id == shop_id)
        )
    ).scalar_one_or_none()
    if not item:
        raise NotFoundException("Favorite")
    await audit(
        db, admin, request, "favorite.deleted", "favorite", item.id, reason="Admin support action"
    )
    await db.delete(item)


@router.delete("/users/{user_id}/cart", status_code=status.HTTP_204_NO_CONTENT)
async def clear_user_cart(user_id: UUID, admin: CurrentAdmin, request: Request, db: DB):
    carts = list((await db.scalars(select(Cart).where(Cart.user_id == user_id))).all())
    for cart in carts:
        await db.delete(cart)
    await audit(
        db,
        admin,
        request,
        "cart.cleared",
        "user",
        user_id,
        after={"carts": len(carts)},
        reason="Admin support action",
    )


@router.post("/users/{user_id}/sessions/revoke")
async def revoke_user_sessions(user_id: UUID, admin: CurrentAdmin, request: Request, db: DB):
    sessions = list(
        (
            await db.scalars(
                select(RefreshSession).where(
                    RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
                )
            )
        ).all()
    )
    now = datetime.now(UTC)
    for item in sessions:
        item.revoked_at = now
    await audit(
        db,
        admin,
        request,
        "sessions.revoked",
        "user",
        user_id,
        after={"count": len(sessions)},
        reason="Administrator revoked sessions",
    )
    return {"revoked": len(sessions)}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID, data: DeleteConfirmation, admin: CurrentAdmin, request: Request, db: DB
):
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundException("User")
    if user.id == admin.id:
        raise ConflictException("You cannot permanently delete your own administrator account")
    verify_admin_password(admin, data.password)
    confirm_name(user.email or user.phone or user.name or str(user.id), data.confirmation)
    dependencies = {
        "orders": await db.scalar(
            select(func.count()).select_from(Order).where(Order.customer_id == user.id)
        ),
        "payments": await db.scalar(
            select(func.count()).select_from(Payment).where(Payment.user_id == user.id)
        ),
        "shops": await db.scalar(
            select(func.count()).select_from(Shop).where(Shop.owner_id == user.id)
        ),
        "audit logs": await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.actor_id == user.id)
        ),
    }
    blocked = [name for name, count in dependencies.items() if count]
    if blocked:
        raise ConflictException(
            f"Permanent deletion blocked by: {', '.join(blocked)}. Deactivate the user instead."
        )
    await audit(
        db,
        admin,
        request,
        "user.permanently_deleted",
        "user",
        user.id,
        before=snapshot(user),
        reason=data.reason,
    )
    await db.delete(user)


@router.get("/shops")
async def shops(
    _: CurrentAdmin,
    db: DB,
    status_filter: ShopStatus | None = Query(None, alias="status"),
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(Shop)
    if status_filter:
        query = query.where(Shop.status == status_filter)
    if q:
        query = query.where(
            or_(Shop.name.ilike(f"%{q}%"), Shop.city.ilike(f"%{q}%"), Shop.area.ilike(f"%{q}%"))
        )
    return await page(db, query.order_by(Shop.created_at.desc()), limit, offset)


@router.get("/shops/{shop_id}")
async def shop_detail(shop_id: UUID, _: CurrentAdmin, db: DB):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise NotFoundException("Shop")
    hours = list(
        (
            await db.scalars(
                select(ShopHour).where(ShopHour.shop_id == shop.id).order_by(ShopHour.weekday)
            )
        ).all()
    )
    products = list(
        (
            await db.scalars(
                select(Product)
                .where(Product.shop_id == shop.id, Product.is_deleted.is_(False))
                .limit(100)
            )
        ).all()
    )
    return {"shop": shop, "hours": hours, "products": products}


@router.patch("/shops/{shop_id}")
async def update_shop(
    shop_id: UUID, data: ShopAdminUpdate, admin: CurrentAdmin, request: Request, db: DB
):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise NotFoundException("Shop")
    ensure_fresh(shop, data.expected_updated_at)
    before = snapshot(shop)
    for key, value in data.model_dump(
        exclude={"reason", "expected_updated_at"}, exclude_unset=True
    ).items():
        setattr(shop, key, value)
    await audit(
        db,
        admin,
        request,
        "shop.updated",
        "shop",
        shop.id,
        before=before,
        after=snapshot(shop),
        reason=data.reason,
    )
    return shop


@router.post("/shops/{shop_id}/lifecycle")
async def shop_lifecycle(
    shop_id: UUID, data: LifecycleAction, admin: CurrentAdmin, request: Request, db: DB
):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise NotFoundException("Shop")
    before = snapshot(shop)
    shop.status = data.status
    shop.approved_at = datetime.now(UTC) if data.status == ShopStatus.ACTIVE else shop.approved_at
    shop.rejection_reason = data.reason if data.status == ShopStatus.REJECTED else None
    await audit(
        db,
        admin,
        request,
        f"shop.{data.status.value}",
        "shop",
        shop.id,
        before=before,
        after=snapshot(shop),
        reason=data.reason,
    )
    return shop


@router.delete("/shops/{shop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shop(
    shop_id: UUID, data: DeleteConfirmation, admin: CurrentAdmin, request: Request, db: DB
):
    shop = await db.get(Shop, shop_id)
    if not shop:
        raise NotFoundException("Shop")
    verify_admin_password(admin, data.password)
    confirm_name(shop.name, data.confirmation)
    checks = {
        "orders": await db.scalar(
            select(func.count()).select_from(Order).where(Order.shop_id == shop.id)
        ),
        "payments": await db.scalar(
            select(func.count()).select_from(Payment).where(Payment.shop_id == shop.id)
        ),
        "reward campaigns": await db.scalar(
            select(func.count())
            .select_from(RewardCampaign)
            .where(RewardCampaign.shop_id == shop.id)
        ),
    }
    blocked = [name for name, count in checks.items() if count]
    if blocked:
        raise ConflictException(
            f"Permanent deletion blocked by: {', '.join(blocked)}. Suspend the shop instead."
        )
    await audit(
        db,
        admin,
        request,
        "shop.permanently_deleted",
        "shop",
        shop.id,
        before=snapshot(shop),
        reason=data.reason,
    )
    await db.delete(shop)


@router.get("/categories")
async def categories(
    _: CurrentAdmin,
    db: DB,
    q: str | None = None,
    active: bool | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(Category)
    if q:
        query = query.where(Category.name.ilike(f"%{q}%"))
    if active is not None:
        query = query.where(Category.is_active == active)
    return await page(db, query.order_by(Category.sort_order, Category.name), limit, offset)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(data: CategoryCreate, admin: CurrentAdmin, request: Request, db: DB):
    item = Category(**data.model_dump())
    db.add(item)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "category.created",
        "category",
        item.id,
        after=snapshot(item),
        reason="Category created",
    )
    return item


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: UUID, data: CategoryAdminUpdate, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Category, category_id)
    if not item:
        raise NotFoundException("Category")
    ensure_fresh(item, data.expected_updated_at)
    before = snapshot(item)
    for key, value in data.model_dump(
        exclude={"reason", "expected_updated_at"}, exclude_unset=True
    ).items():
        setattr(item, key, value)
    await audit(
        db,
        admin,
        request,
        "category.updated",
        "category",
        item.id,
        before=before,
        after=snapshot(item),
        reason=data.reason,
    )
    return item


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID, data: DeleteConfirmation, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Category, category_id)
    if not item:
        raise NotFoundException("Category")
    verify_admin_password(admin, data.password)
    confirm_name(item.name, data.confirmation)
    if await db.scalar(
        select(func.count()).select_from(Product).where(Product.category_id == item.id)
    ):
        raise ConflictException(
            "Permanent deletion blocked by products. Deactivate the category instead."
        )
    if await db.scalar(
        select(func.count()).select_from(Category).where(Category.parent_id == item.id)
    ):
        raise ConflictException("Permanent deletion blocked by child categories")
    await audit(
        db,
        admin,
        request,
        "category.permanently_deleted",
        "category",
        item.id,
        before=snapshot(item),
        reason=data.reason,
    )
    await db.delete(item)


@router.get("/products")
async def products(
    _: CurrentAdmin,
    db: DB,
    shop_id: UUID | None = None,
    category_id: UUID | None = None,
    available: bool | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(Product)
    if shop_id:
        query = query.where(Product.shop_id == shop_id)
    if category_id:
        query = query.where(Product.category_id == category_id)
    if available is not None:
        query = query.where(Product.is_available == available)
    if q:
        query = query.where(Product.name.ilike(f"%{q}%"))
    return await page(db, query.order_by(Product.created_at.desc()), limit, offset)


@router.get("/products/{product_id}")
async def product_detail(product_id: UUID, _: CurrentAdmin, db: DB):
    item = await db.get(Product, product_id)
    if not item:
        raise NotFoundException("Product")
    return item


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductAdminCreate, admin: CurrentAdmin, request: Request, db: DB):
    if not await db.get(Shop, data.shop_id):
        raise NotFoundException("Shop")
    item = Product(**data.model_dump())
    db.add(item)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "product.created",
        "product",
        item.id,
        after=snapshot(item),
        reason="Product created",
    )
    return item


@router.patch("/products/{product_id}")
async def update_product(
    product_id: UUID, data: ProductAdminUpdate, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Product, product_id)
    if not item:
        raise NotFoundException("Product")
    ensure_fresh(item, data.expected_updated_at)
    before = snapshot(item)
    for key, value in data.model_dump(
        exclude={"reason", "expected_updated_at"}, exclude_unset=True
    ).items():
        setattr(item, key, value)
    await audit(
        db,
        admin,
        request,
        "product.updated",
        "product",
        item.id,
        before=before,
        after=snapshot(item),
        reason=data.reason,
    )
    return item


@router.post("/products/{product_id}/archive")
async def archive_product(
    product_id: UUID,
    admin: CurrentAdmin,
    request: Request,
    db: DB,
    restore: bool = False,
    reason: str = Query(..., min_length=3, max_length=500),
):
    item = await db.get(Product, product_id)
    if not item:
        raise NotFoundException("Product")
    before = snapshot(item)
    item.is_deleted = not restore
    item.is_available = restore
    await audit(
        db,
        admin,
        request,
        "product.restored" if restore else "product.archived",
        "product",
        item.id,
        before=before,
        after=snapshot(item),
        reason=reason,
    )
    return item


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: UUID, data: DeleteConfirmation, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Product, product_id)
    if not item:
        raise NotFoundException("Product")
    verify_admin_password(admin, data.password)
    confirm_name(item.name, data.confirmation)
    if await db.scalar(
        select(func.count()).select_from(OrderItem).where(OrderItem.product_id == item.id)
    ):
        raise ConflictException(
            "Permanent deletion blocked by order history. Archive the product instead."
        )
    if await db.scalar(
        select(func.count()).select_from(CartItem).where(CartItem.product_id == item.id)
    ):
        raise ConflictException("Permanent deletion blocked by active carts")
    await audit(
        db,
        admin,
        request,
        "product.permanently_deleted",
        "product",
        item.id,
        before=snapshot(item),
        reason=data.reason,
    )
    await db.delete(item)


@router.get("/orders")
async def orders(
    _: CurrentAdmin,
    db: DB,
    status_filter: OrderStatus | None = Query(None, alias="status"),
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(Order)
    if status_filter:
        query = query.where(Order.status == status_filter)
    if q:
        query = query.where(Order.order_number.ilike(f"%{q}%"))
    return await page(db, query.order_by(Order.created_at.desc()), limit, offset)


@router.get("/orders/{order_id}")
async def order_detail(order_id: UUID, _: CurrentAdmin, db: DB):
    item = await db.get(Order, order_id)
    if not item:
        raise NotFoundException("Order")
    order_items = list(
        (await db.scalars(select(OrderItem).where(OrderItem.order_id == item.id))).all()
    )
    payments = list((await db.scalars(select(Payment).where(Payment.order_id == item.id))).all())
    return {"order": item, "items": order_items, "payments": payments}


@router.post("/orders/{order_id}/action")
async def order_action(
    order_id: UUID, data: OrderAdminAction, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Order, order_id)
    if not item:
        raise NotFoundException("Order")
    allowed = {
        OrderStatus.PENDING: {OrderStatus.ACCEPTED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
        OrderStatus.ACCEPTED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
        OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
        OrderStatus.READY: {
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.COMPLETED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    }
    if data.status not in allowed.get(item.status, set()):
        raise ConflictException(
            f"Cannot move order from {item.status.value} to {data.status.value}"
        )
    before = snapshot(item)
    item.status = data.status
    if data.status in {OrderStatus.CANCELLED, OrderStatus.REJECTED}:
        item.cancellation_reason = data.reason
    if data.status == OrderStatus.COMPLETED:
        item.completed_at = datetime.now(UTC)
    await audit(
        db,
        admin,
        request,
        f"order.{data.status.value}",
        "order",
        item.id,
        before=before,
        after=snapshot(item),
        reason=data.reason,
    )
    return item


@router.get("/payments")
async def payments(
    _: CurrentAdmin,
    db: DB,
    status_filter: PaymentStatus | None = Query(None, alias="status"),
    purpose: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(Payment)
    if status_filter:
        query = query.where(Payment.status == status_filter)
    if purpose:
        query = query.where(Payment.purpose == purpose)
    return await page(db, query.order_by(Payment.created_at.desc()), limit, offset)


@router.get("/payments/{payment_id}")
async def payment_detail(payment_id: UUID, _: CurrentAdmin, db: DB):
    item = await db.get(Payment, payment_id)
    if not item:
        raise NotFoundException("Payment")
    return item


@router.post("/payments/{payment_id}/action")
async def payment_action(
    payment_id: UUID, data: PaymentAdminAction, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Payment, payment_id)
    if not item:
        raise NotFoundException("Payment")
    if data.expected_status and item.status != data.expected_status:
        raise ConflictException("Payment status changed. Refresh and retry.")
    before = snapshot(item)
    if data.action == "refund":
        if item.status != PaymentStatus.CAPTURED:
            raise ConflictException("Only captured payments can be refunded")
        if settings.razorpay_key_id and settings.razorpay_key_secret and item.provider_payment_id:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"https://api.razorpay.com/v1/payments/{item.provider_payment_id}/refund",
                    auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
                    json={"amount": item.amount_paise, "notes": {"reason": data.reason}},
                )
                response.raise_for_status()
                item.metadata_json = {**item.metadata_json, "refund": response.json()}
        elif settings.environment != "development":
            raise AppException("Payment provider is unavailable", 503)
        item.status = PaymentStatus.REFUNDED
        if item.order_id:
            order = await db.get(Order, item.order_id)
            if order:
                order.status = OrderStatus.REFUNDED
    else:
        item.metadata_json = {
            **item.metadata_json,
            "last_reconciled_at": datetime.now(UTC).isoformat(),
        }
    await audit(
        db,
        admin,
        request,
        f"payment.{data.action}",
        "payment",
        item.id,
        before=before,
        after=snapshot(item),
        reason=data.reason,
    )
    return item


@router.get("/rewards")
async def rewards(
    _: CurrentAdmin,
    db: DB,
    q: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(RewardCampaign)
    if q:
        query = query.where(RewardCampaign.title.ilike(f"%{q}%"))
    if status_filter:
        query = query.where(RewardCampaign.status == status_filter)
    return await page(db, query.order_by(RewardCampaign.created_at.desc()), limit, offset)


@router.get("/rewards/{campaign_id}")
async def reward_detail(campaign_id: UUID, _: CurrentAdmin, db: DB):
    item = await db.get(RewardCampaign, campaign_id)
    if not item:
        raise NotFoundException("Campaign")
    claims = list(
        (
            await db.scalars(
                select(RewardClaim)
                .where(RewardClaim.campaign_id == item.id)
                .order_by(RewardClaim.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return {"campaign": item, "claims": claims}


@router.post("/rewards", status_code=status.HTTP_201_CREATED)
async def create_reward(data: CampaignAdminCreate, admin: CurrentAdmin, request: Request, db: DB):
    if not await db.get(Shop, data.shop_id):
        raise NotFoundException("Shop")
    item = RewardCampaign(**data.model_dump())
    db.add(item)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "campaign.created",
        "campaign",
        item.id,
        after=snapshot(item),
        reason="Reward campaign created",
    )
    return item


@router.patch("/rewards/{campaign_id}")
async def update_reward(
    campaign_id: UUID, data: CampaignAdminUpdate, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(RewardCampaign, campaign_id)
    if not item:
        raise NotFoundException("Campaign")
    ensure_fresh(item, data.expected_updated_at)
    before = snapshot(item)
    for key, value in data.model_dump(
        exclude={"reason", "expected_updated_at"}, exclude_unset=True
    ).items():
        setattr(item, key, value)
    await audit(
        db,
        admin,
        request,
        "campaign.updated",
        "campaign",
        item.id,
        before=before,
        after=snapshot(item),
        reason=data.reason,
    )
    return item


@router.post("/rewards/claims/{claim_id}/action")
async def claim_action(
    claim_id: UUID, data: ClaimAction, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(RewardClaim, claim_id)
    if not item:
        raise NotFoundException("Reward claim")
    before = snapshot(item)
    item.status = data.status
    item.redeemed_at = datetime.now(UTC) if data.status == "redeemed" else None
    await audit(
        db,
        admin,
        request,
        f"reward_claim.{data.status}",
        "reward_claim",
        item.id,
        before=before,
        after=snapshot(item),
        reason=data.reason,
    )
    return item


@router.delete("/rewards/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reward(
    campaign_id: UUID, data: DeleteConfirmation, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(RewardCampaign, campaign_id)
    if not item:
        raise NotFoundException("Campaign")
    verify_admin_password(admin, data.password)
    confirm_name(item.title, data.confirmation)
    if await db.scalar(
        select(func.count()).select_from(RewardClaim).where(RewardClaim.campaign_id == item.id)
    ):
        raise ConflictException(
            "Permanent deletion blocked by reward claims. Suspend the campaign instead."
        )
    await audit(
        db,
        admin,
        request,
        "campaign.permanently_deleted",
        "campaign",
        item.id,
        before=snapshot(item),
        reason=data.reason,
    )
    await db.delete(item)


@router.get("/promotions")
async def promotions(
    _: CurrentAdmin,
    db: DB,
    active: bool | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = select(Promotion)
    if active is not None:
        query = query.where(Promotion.is_active == active)
    if q:
        query = query.where(Promotion.title.ilike(f"%{q}%"))
    return await page(
        db, query.order_by(Promotion.sort_order, Promotion.created_at.desc()), limit, offset
    )


@router.post("/promotions", status_code=status.HTTP_201_CREATED)
async def create_promotion(data: PromotionCreate, admin: CurrentAdmin, request: Request, db: DB):
    item = Promotion(created_by=admin.id, **data.model_dump())
    db.add(item)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "promotion.created",
        "promotion",
        item.id,
        after=snapshot(item),
        reason="Promotion created",
    )
    return item


@router.patch("/promotions/{promotion_id}")
async def update_promotion(
    promotion_id: UUID, data: PromotionUpdate, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Promotion, promotion_id)
    if not item:
        raise NotFoundException("Promotion")
    ensure_fresh(item, data.expected_updated_at)
    before = snapshot(item)
    for key, value in data.model_dump(
        exclude={"reason", "expected_updated_at"}, exclude_unset=True
    ).items():
        setattr(item, key, value)
    await audit(
        db,
        admin,
        request,
        "promotion.updated",
        "promotion",
        item.id,
        before=before,
        after=snapshot(item),
        reason=data.reason,
    )
    return item


@router.delete("/promotions/{promotion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_promotion(
    promotion_id: UUID, data: DeleteConfirmation, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(Promotion, promotion_id)
    if not item:
        raise NotFoundException("Promotion")
    verify_admin_password(admin, data.password)
    confirm_name(item.title, data.confirmation)
    await audit(
        db,
        admin,
        request,
        "promotion.permanently_deleted",
        "promotion",
        item.id,
        before=snapshot(item),
        reason=data.reason,
    )
    await db.delete(item)


@router.get("/notifications")
async def notification_history(
    _: CurrentAdmin, db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
):
    return await page(
        db,
        select(NotificationBroadcast).order_by(NotificationBroadcast.created_at.desc()),
        limit,
        offset,
    )


@router.post("/notifications", status_code=status.HTTP_201_CREATED)
async def notify(data: NotificationCompose, admin: CurrentAdmin, request: Request, db: DB):
    query = select(User.id).where(User.is_active.is_(True))
    if data.role != "all":
        query = query.where(User.role == UserRole(data.role))
    ids = list((await db.scalars(query)).all())
    db.add_all(
        [
            Notification(user_id=user_id, title=data.title, body=data.body, data=data.data)
            for user_id in ids
        ]
    )
    broadcast = NotificationBroadcast(
        title=data.title,
        body=data.body,
        audience=data.role,
        data=data.data,
        recipient_count=len(ids),
        status="sent",
        created_by=admin.id,
        sent_at=datetime.now(UTC),
    )
    db.add(broadcast)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "notification.broadcast",
        "notification_broadcast",
        broadcast.id,
        after={"recipients": len(ids), "audience": data.role},
        reason="Notification broadcast",
    )
    return broadcast


@router.get("/audit-logs")
async def audit_logs(
    _: CurrentAdmin,
    db: DB,
    action: str | None = None,
    resource_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    return await page(db, query.order_by(AuditLog.created_at.desc()), limit, offset)


@router.get("/settings", response_model=MarketplaceSettings)
async def list_settings(_: CurrentAdmin, db: DB):
    item = await db.get(AppSetting, "marketplace_config")
    defaults = {
        "launch_city": settings.launch_city,
        "default_delivery_fee_paise": settings.default_delivery_fee_paise,
        "shop_activation_fee_paise": settings.shop_activation_fee_paise,
        "cancellation_window_minutes": 5,
        "support_email": None,
        "support_phone": None,
    }
    return MarketplaceSettings(**(item.value if item else defaults))


@router.put("/settings", response_model=MarketplaceSettings)
async def update_settings(data: MarketplaceSettings, admin: CurrentAdmin, request: Request, db: DB):
    item = await db.get(AppSetting, "marketplace_config")
    before = item.value if item else None
    if item:
        item.value = data.model_dump()
    else:
        item = AppSetting(
            key="marketplace_config",
            value=data.model_dump(),
            description="Validated marketplace operations configuration",
        )
        db.add(item)
    await audit(
        db,
        admin,
        request,
        "setting.updated",
        "setting",
        "marketplace_config",
        before=before,
        after=data.model_dump(),
        reason="Marketplace configuration updated",
    )
    return data


@router.get("/admins")
async def admins(
    _: CurrentAdmin, db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
):
    return await page(
        db,
        select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at.desc()),
        limit,
        offset,
    )


@router.post("/admins", status_code=status.HTTP_201_CREATED)
async def create_admin(data: AdminCreate, admin: CurrentAdmin, request: Request, db: DB):
    if await db.scalar(select(User.id).where(User.email == data.email.lower())):
        raise ConflictException("Email is already registered")
    item = User(
        email=data.email.lower(),
        hashed_password=hash_password(data.password),
        role=UserRole.ADMIN,
        name=data.name,
        is_profile_complete=True,
        is_phone_verified=True,
    )
    db.add(item)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "admin.created",
        "user",
        item.id,
        after={"email": item.email},
        reason="Administrator created",
    )
    return item


@router.get("/admins/{admin_id}")
async def admin_detail(admin_id: UUID, _: CurrentAdmin, db: DB):
    item = await db.get(User, admin_id)
    if not item or item.role != UserRole.ADMIN:
        raise NotFoundException("Administrator")
    sessions = list(
        (
            await db.scalars(
                select(RefreshSession)
                .where(RefreshSession.user_id == item.id)
                .order_by(RefreshSession.created_at.desc())
            )
        ).all()
    )
    return {"admin": item, "sessions": sessions}


@router.patch("/admins/{admin_id}/status")
async def admin_status(
    admin_id: UUID, data: AdminStatusAction, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(User, admin_id)
    if not item or item.role != UserRole.ADMIN:
        raise NotFoundException("Administrator")
    if item.id == admin.id and not data.is_active:
        raise ConflictException("You cannot deactivate your own account")
    if (
        not data.is_active
        and int(
            (
                await db.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
                )
            )
            or 0
        )
        <= 1
    ):
        raise ConflictException("The last active administrator cannot be deactivated")
    before = item.is_active
    item.is_active = data.is_active
    await audit(
        db,
        admin,
        request,
        "admin.status_changed",
        "user",
        item.id,
        before={"active": before},
        after={"active": data.is_active},
        reason=data.reason,
    )
    return item


@router.post("/admins/{admin_id}/reset-password")
async def reset_admin_password(
    admin_id: UUID, data: AdminPasswordReset, admin: CurrentAdmin, request: Request, db: DB
):
    verify_admin_password(admin, data.admin_password)
    item = await db.get(User, admin_id)
    if not item or item.role != UserRole.ADMIN:
        raise NotFoundException("Administrator")
    item.hashed_password = hash_password(data.new_password)
    sessions = list(
        (
            await db.scalars(
                select(RefreshSession).where(
                    RefreshSession.user_id == item.id, RefreshSession.revoked_at.is_(None)
                )
            )
        ).all()
    )
    for session in sessions:
        session.revoked_at = datetime.now(UTC)
    await audit(
        db,
        admin,
        request,
        "admin.password_reset",
        "user",
        item.id,
        after={"sessions_revoked": len(sessions)},
        reason=data.reason,
    )
    return {"reset": True, "sessions_revoked": len(sessions)}


@router.post("/admins/me/change-password")
async def change_admin_password(
    data: AdminPasswordChange, admin: CurrentAdmin, request: Request, db: DB
):
    verify_admin_password(admin, data.current_password)
    admin.hashed_password = hash_password(data.new_password)
    await AuthService(db).revoke_session(admin, all_sessions=True)
    await audit(
        db,
        admin,
        request,
        "admin.password_changed",
        "user",
        admin.id,
        reason="Self-service password change",
    )
    return {"changed": True}


@router.post("/media/presign", status_code=status.HTTP_201_CREATED)
async def media_presign(data: MediaPresignRequest, admin: CurrentAdmin, request: Request, db: DB):
    service = MediaService()
    service.validate_size(data.size_bytes)
    key = service.object_key(data.kind, data.filename)
    item = MediaAsset(
        object_key=key,
        bucket=settings.s3_bucket,
        content_type=data.content_type,
        size_bytes=data.size_bytes,
        status="pending",
        uploaded_by=admin.id,
    )
    db.add(item)
    await db.flush()
    await audit(
        db,
        admin,
        request,
        "media.presigned",
        "media_asset",
        item.id,
        after={"object_key": key, "content_type": data.content_type},
    )
    return {
        "asset_id": item.id,
        "upload_url": service.presign(key, data.content_type),
        "object_key": key,
        "expires_in": settings.media_presign_expire_seconds,
    }


@router.post("/media/{asset_id}/complete")
async def media_complete(
    asset_id: UUID, data: MediaCompleteRequest, admin: CurrentAdmin, request: Request, db: DB
):
    item = await db.get(MediaAsset, asset_id)
    if not item:
        raise NotFoundException("Media asset")
    MediaService().validate_size(data.size_bytes)
    if data.size_bytes != item.size_bytes:
        raise ConflictException("Uploaded size does not match the presigned request")
    item.status = "ready"
    item.public_url = MediaService().public_url(item.object_key)
    await audit(
        db,
        admin,
        request,
        "media.completed",
        "media_asset",
        item.id,
        after={"public_url": item.public_url},
    )
    return item


@router.delete("/media/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def media_delete(asset_id: UUID, admin: CurrentAdmin, request: Request, db: DB):
    item = await db.get(MediaAsset, asset_id)
    if not item:
        raise NotFoundException("Media asset")
    MediaService().delete(item.object_key)
    await audit(
        db,
        admin,
        request,
        "media.deleted",
        "media_asset",
        item.id,
        before=snapshot(item),
        reason="Unused media removed",
    )
    await db.delete(item)


@router.get("/reports/{report_name}.csv")
async def report_csv(report_name: str, _: CurrentAdmin, db: DB):
    definitions = {
        "users": (User, ["id", "name", "phone", "email", "role", "is_active", "created_at"]),
        "shops": (Shop, ["id", "name", "business_type", "city", "area", "status", "created_at"]),
        "products": (
            Product,
            [
                "id",
                "shop_id",
                "name",
                "price_paise",
                "stock_quantity",
                "is_available",
                "created_at",
            ],
        ),
        "orders": (
            Order,
            ["id", "order_number", "customer_id", "shop_id", "status", "total_paise", "created_at"],
        ),
        "payments": (
            Payment,
            [
                "id",
                "purpose",
                "provider",
                "provider_order_id",
                "amount_paise",
                "status",
                "created_at",
            ],
        ),
        "rewards": (
            RewardCampaign,
            ["id", "shop_id", "title", "city", "claimed_count", "total_inventory", "status"],
        ),
        "audit": (
            AuditLog,
            ["id", "actor_id", "action", "resource_type", "resource_id", "reason", "created_at"],
        ),
    }
    if report_name not in definitions:
        raise NotFoundException("Report")
    model, columns = definitions[report_name]
    items = list((await db.scalars(select(model).order_by(model.created_at.desc()))).all())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for item in items:
        writer.writerow([getattr(item, column) for column in columns])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="aranye-{report_name}.csv"'},
    )


@router.get("/otp/status", response_model=OTPProviderStatus)
async def otp_status(_: CurrentAdmin):
    return OTPProviderStatus(
        provider=settings.sms_provider,
        configured=bool(
            (settings.twilio_api_key and settings.twilio_api_key_secret)
            or (settings.twilio_account_sid and settings.twilio_auth_token)
        ),
        service_configured=bool(settings.twilio_verify_service_sid),
        environment=settings.environment,
    )


@router.get("/otp/delivery-events")
async def otp_delivery_events(
    _: CurrentAdmin,
    db: DB,
    provider_request_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(OTPDeliveryEvent)
    if provider_request_id:
        query = query.where(OTPDeliveryEvent.provider_request_id == provider_request_id)
    return await page(db, query.order_by(OTPDeliveryEvent.created_at.desc()), limit, offset)
