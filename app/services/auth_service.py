import hashlib
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, ForbiddenException, UnauthorizedException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import RefreshSession, User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.auth import AdminLoginRequest, TokenResponse
from app.schemas.user import ProfileCompleteRequest, ProfileUpdateRequest, UserResponse
from app.services.otp_service import OTPService

settings = get_settings()
PHONE_REGEX = re.compile(r"^\+?[1-9]\d{9,14}$")


class AuthService:
    """
    Business logic layer — orchestrates repositories, OTP, and JWT.
    API routes should NEVER contain business logic; they call this service.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.otp_service = OTPService()

    def _is_phone(self, identifier: str) -> bool:
        return bool(PHONE_REGEX.match(identifier))

    def _role_enum(self, role: str) -> UserRole:
        return UserRole(role)

    async def send_otp(
        self, identifier: str, role: UserRole
    ) -> tuple[str, int, int, str | None, str | None]:

        if not self._is_phone(identifier):
            raise AppException("OTP login currently supports phone numbers only.")

        user = await self.user_repo.get_by_phone_and_role(identifier, role)
        if user and not user.is_active:
            raise ForbiddenException("Your account has been deactivated. Contact support.")

        otp, expires_in, cooldown, debug_otp, provider_request_id = await self._send_otp_internal(
            identifier, role.value
        )
        return otp, expires_in, cooldown, debug_otp, provider_request_id

    async def _send_otp_internal(
        self, identifier: str, role: str
    ) -> tuple[str, int, int, str | None, str | None]:
        otp, expires_in, cooldown, provider_request_id = await self.otp_service.send_otp(
            identifier, role
        )
        debug_otp = (
            otp
            if settings.environment == "development" and settings.sms_provider == "console"
            else None
        )
        return otp, expires_in, cooldown, debug_otp, provider_request_id

    async def verify_otp(self, identifier: str, otp: str, role: UserRole) -> TokenResponse:
        await self.otp_service.verify_otp(identifier, role.value, otp)

        user = await self.user_repo.get_by_phone_and_role(identifier, role)
        is_new_user = False

        if not user:
            user = User(
                phone=identifier,
                role=role,
                is_phone_verified=True,
                is_profile_complete=False,
            )
            user = await self.user_repo.create(user)
            is_new_user = True
        else:
            user.is_phone_verified = True
            user = await self.user_repo.update(user)

        return await self._build_token_response(user, is_new_user)

    async def resend_otp(
        self, identifier: str, role: str
    ) -> tuple[int, int, str | None, str | None]:
        otp, expires_in, cooldown, provider_request_id = await self.otp_service.resend_otp(
            identifier, role
        )
        debug_otp = (
            otp
            if settings.environment == "development" and settings.sms_provider == "console"
            else None
        )
        return expires_in, cooldown, debug_otp, provider_request_id

    async def admin_login(self, request: AdminLoginRequest) -> TokenResponse:
        user = await self.user_repo.get_by_email(request.email)

        if not user or user.role != UserRole.ADMIN:
            raise UnauthorizedException("Invalid email or password")

        if not user.hashed_password or not verify_password(request.password, user.hashed_password):
            raise UnauthorizedException("Invalid email or password")

        if not user.is_active:
            raise ForbiddenException("Admin account is deactivated")

        return await self._build_token_response(user, is_new_user=False)

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise UnauthorizedException("Invalid refresh token")

        user = await self.user_repo.get_by_id(UUID(payload["sub"]))
        if not user or not user.is_active:
            raise UnauthorizedException("User not found or inactive")
        session = await self.db.get(
            RefreshSession, UUID(payload.get("sid", "00000000-0000-0000-0000-000000000000"))
        )
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        if not session or session.revoked_at or session.expires_at <= datetime.now(UTC):
            raise UnauthorizedException("Refresh session expired or revoked")
        if not __import__("hmac").compare_digest(session.token_hash, token_hash):
            session.revoked_at = datetime.now(UTC)
            raise UnauthorizedException("Refresh token reuse detected")
        session.revoked_at = datetime.now(UTC)
        return await self._build_token_response(user, is_new_user=False)

    async def complete_profile(self, user: User, request: ProfileCompleteRequest) -> UserResponse:
        from app.models.user import Gender

        user.gender = Gender(request.gender)
        user.date_of_birth = request.date_of_birth
        user.whatsapp_number = request.whatsapp_number
        if request.name:
            user.name = request.name
        user.is_profile_complete = True

        user = await self.user_repo.update(user)
        return UserResponse.model_validate(user)

    async def update_profile(self, user: User, request: ProfileUpdateRequest) -> UserResponse:
        for field, value in request.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        user = await self.user_repo.update(user)
        return UserResponse.model_validate(user)

    async def get_current_user(self, token: str) -> User:
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            raise UnauthorizedException("Invalid or expired token")

        user = await self.user_repo.get_by_id(UUID(payload["sub"]))
        if not user or not user.is_active:
            raise UnauthorizedException("User not found or inactive")

        return user

    async def _build_token_response(self, user: User, is_new_user: bool) -> TokenResponse:
        access_token = create_access_token(user.id, user.role.value)
        session = RefreshSession(
            user_id=user.id,
            token_hash="pending",
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        )
        self.db.add(session)
        await self.db.flush()
        refresh_token = create_refresh_token(user.id, user.role.value, session.id)
        session.token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
            user=UserResponse.model_validate(user),
            is_new_user=is_new_user,
        )

    async def revoke_session(
        self, user: User, token: str | None = None, all_sessions: bool = False
    ) -> None:
        from sqlalchemy import select

        query = select(RefreshSession).where(
            RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)
        )
        sessions = (await self.db.scalars(query)).all()
        now = datetime.now(UTC)
        if all_sessions:
            for session in sessions:
                session.revoked_at = now
            return
        if token:
            payload = decode_token(token)
            if (
                not payload
                or payload.get("type") != "refresh"
                or payload.get("sub") != str(user.id)
            ):
                raise UnauthorizedException("Invalid refresh token")
            sid = payload.get("sid")
            for session in sessions:
                if str(session.id) == sid:
                    session.revoked_at = now
                    break

    @staticmethod
    async def create_admin_user(
        db: AsyncSession,
        email: str,
        password: str,
        name: str = "Admin",
    ) -> User:
        """Utility to seed the first admin user."""
        repo = UserRepository(db)
        existing = await repo.get_by_email(email)
        if existing:
            return existing

        admin = User(
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.ADMIN,
            name=name,
            is_profile_complete=True,
            is_phone_verified=True,
        )
        return await repo.create(admin)
