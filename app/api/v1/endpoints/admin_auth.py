from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentAdmin, get_auth_service
from app.schemas.auth import AdminLoginRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Admin panel login (email + password)",
)
async def admin_login(
    request: AdminLoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await auth_service.admin_login(request)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current admin user",
)
async def admin_me(current_admin: CurrentAdmin):
    return UserResponse.model_validate(current_admin)
