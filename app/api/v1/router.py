from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    admin_auth,
    admin_scratch_cards,
    auth,
    customer,
    customer_reels,
    customer_scratch_cards,
    payments,
    shopkeeper,
    shopkeeper_reels,
    shopkeeper_scratch_cards,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth")
api_router.include_router(admin_auth.router, prefix="/admin/auth", tags=["Admin Authentication"])
api_router.include_router(customer.router, prefix="/customer", tags=["Customer APIs"])
api_router.include_router(customer_reels.router, prefix="/customer", tags=["Customer Reels"])
api_router.include_router(
    customer_scratch_cards.router, prefix="/customer", tags=["Customer Scratch Cards"]
)
api_router.include_router(shopkeeper.router, prefix="/shopkeeper", tags=["Shopkeeper APIs"])
api_router.include_router(shopkeeper_reels.router, prefix="/shopkeeper", tags=["Shopkeeper Reels"])
api_router.include_router(
    shopkeeper_scratch_cards.router,
    prefix="/shopkeeper",
    tags=["Shopkeeper Scratch Cards"],
)
api_router.include_router(payments.router, prefix="/payments", tags=["Payment APIs"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin APIs"])
api_router.include_router(admin_scratch_cards.router, prefix="/admin", tags=["Admin Scratch Cards"])
