from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.models.user import User, UserRole
from app.services.auth_service import AuthService

security = HTTPBearer(auto_error=False)
settings = get_settings()
admin_email_password = OAuth2PasswordBearer(
    tokenUrl=f"{settings.public_base_url.rstrip('/')}/docs/token",
    scheme_name="AdminEmailPassword",
    description="Enter an active administrator email in the username field and its password.",
    auto_error=False,
)


async def get_auth_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthService:
    return AuthService(db)


async def get_current_user(
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    admin_access_token: Annotated[str | None, Depends(admin_email_password)],
) -> User:
    access_token = credentials.credentials if credentials else admin_access_token
    if not access_token:
        raise UnauthorizedException("Authentication required")
    return await auth_service.get_current_user(access_token)


def require_role(*allowed_roles: UserRole):
    """
    Role guard — use as a dependency on protected endpoints.
    Example: Depends(require_role(UserRole.CUSTOMER))
    """

    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenException(
                f"This action requires one of: {', '.join(r.value for r in allowed_roles)}"
            )
        return current_user

    return role_checker


# Shorthand dependencies for each role
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentCustomer = Annotated[User, Depends(require_role(UserRole.CUSTOMER))]
CurrentShopkeeper = Annotated[User, Depends(require_role(UserRole.SHOPKEEPER))]
CurrentAdmin = Annotated[User, Depends(require_role(UserRole.ADMIN))]
