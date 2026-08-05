from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUser, get_auth_service
from app.core.config import get_settings
from app.schemas.auth import (
    LogoutRequest,
    OTPResendRequest,
    OTPSendRequest,
    OTPSendResponse,
    OTPVerifyRequest,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse
from app.schemas.user import ProfileCompleteRequest, ProfileUpdateRequest, UserResponse
from app.services.auth_service import AuthService

router = APIRouter()
customer_router = APIRouter()
shopkeeper_router = APIRouter()
shared_router = APIRouter()
settings = get_settings()


@customer_router.post(
    "/customer/send-otp",
    response_model=OTPSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Customer — Send OTP",
    description="Step 1 of customer login. User enters phone on 'Welcome Back' screen.",
)
async def customer_send_otp(
    request: OTPSendRequest,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    from app.models.user import UserRole

    _, expires_in, cooldown, debug_otp, provider_request_id = await auth_service.send_otp(
        request.identifier, UserRole.CUSTOMER
    )
    is_twilio = settings.sms_provider == "twilio"
    if not is_twilio:
        response.status_code = status.HTTP_200_OK
    return OTPSendResponse(
        message="OTP request accepted by Twilio"
        if is_twilio
        else "Development OTP generated; no SMS was sent",
        identifier=request.identifier,
        provider=settings.sms_provider,
        sms_sent=is_twilio,
        provider_status="pending" if is_twilio else "generated",
        otp_expires_in_seconds=expires_in,
        resend_available_in_seconds=cooldown,
        provider_request_id=provider_request_id,
        debug_otp=debug_otp,
    )


@customer_router.post(
    "/customer/verify-otp",
    response_model=TokenResponse,
    summary="Customer — Verify OTP & Login",
    description="Step 2. Returns JWT tokens. is_new_user=true means show 'Add Your Detail' screen.",
)
async def customer_verify_otp(
    request: OTPVerifyRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    from app.models.user import UserRole

    return await auth_service.verify_otp(request.identifier, request.otp, UserRole.CUSTOMER)


@customer_router.post(
    "/customer/resend-otp",
    response_model=OTPSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Customer — Resend OTP",
)
async def customer_resend_otp(
    request: OTPResendRequest,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    expires_in, cooldown, debug_otp, provider_request_id = await auth_service.resend_otp(
        request.identifier, "customer"
    )
    is_twilio = settings.sms_provider == "twilio"
    if not is_twilio:
        response.status_code = status.HTTP_200_OK
    return OTPSendResponse(
        message="OTP resend accepted by Twilio"
        if is_twilio
        else "Development OTP regenerated; no SMS was sent",
        identifier=request.identifier,
        provider=settings.sms_provider,
        sms_sent=is_twilio,
        provider_status="pending" if is_twilio else "generated",
        otp_expires_in_seconds=expires_in,
        resend_available_in_seconds=cooldown,
        provider_request_id=provider_request_id,
        debug_otp=debug_otp,
    )


@shopkeeper_router.post(
    "/shopkeeper/send-otp",
    response_model=OTPSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Shopkeeper — Send OTP",
    description="Same OTP flow but role=shopkeeper. Separate endpoint for clear API docs.",
)
async def shopkeeper_send_otp(
    request: OTPSendRequest,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    from app.models.user import UserRole

    _, expires_in, cooldown, debug_otp, provider_request_id = await auth_service.send_otp(
        request.identifier, UserRole.SHOPKEEPER
    )
    is_twilio = settings.sms_provider == "twilio"
    if not is_twilio:
        response.status_code = status.HTTP_200_OK
    return OTPSendResponse(
        message="OTP request accepted by Twilio"
        if is_twilio
        else "Development OTP generated; no SMS was sent",
        identifier=request.identifier,
        provider=settings.sms_provider,
        sms_sent=is_twilio,
        provider_status="pending" if is_twilio else "generated",
        otp_expires_in_seconds=expires_in,
        resend_available_in_seconds=cooldown,
        provider_request_id=provider_request_id,
        debug_otp=debug_otp,
    )


@shopkeeper_router.post(
    "/shopkeeper/verify-otp",
    response_model=TokenResponse,
    summary="Shopkeeper — Verify OTP & Login",
)
async def shopkeeper_verify_otp(
    request: OTPVerifyRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    from app.models.user import UserRole

    return await auth_service.verify_otp(request.identifier, request.otp, UserRole.SHOPKEEPER)


@shopkeeper_router.post(
    "/shopkeeper/resend-otp",
    response_model=OTPSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Shopkeeper — Resend OTP",
)
async def shopkeeper_resend_otp(
    request: OTPResendRequest,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    expires_in, cooldown, debug_otp, provider_request_id = await auth_service.resend_otp(
        request.identifier, "shopkeeper"
    )
    is_twilio = settings.sms_provider == "twilio"
    if not is_twilio:
        response.status_code = status.HTTP_200_OK
    return OTPSendResponse(
        message="OTP resend accepted by Twilio"
        if is_twilio
        else "Development OTP regenerated; no SMS was sent",
        identifier=request.identifier,
        provider=settings.sms_provider,
        sms_sent=is_twilio,
        provider_status="pending" if is_twilio else "generated",
        otp_expires_in_seconds=expires_in,
        resend_available_in_seconds=cooldown,
        provider_request_id=provider_request_id,
        debug_otp=debug_otp,
    )


@shared_router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    request: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await auth_service.refresh_access_token(request.refresh_token)


@shared_router.post(
    "/profile/complete",
    response_model=UserResponse,
    summary="Complete profile (Add Your Detail screen)",
    description="Called after first login when is_new_user=true or is_profile_complete=false.",
)
async def complete_profile(
    request: ProfileCompleteRequest,
    current_user: CurrentUser,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await auth_service.complete_profile(current_user, request)


@shared_router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current logged-in user",
)
async def get_me(current_user: CurrentUser):
    return UserResponse.model_validate(current_user)


@shared_router.patch(
    "/profile",
    response_model=UserResponse,
    summary="Update editable profile fields",
)
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: CurrentUser,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    return await auth_service.update_profile(current_user, request)


@shared_router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout",
    description="Revokes the supplied refresh-token session. Client must then delete both tokens.",
)
async def logout(
    request: LogoutRequest,
    current_user: CurrentUser,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    await auth_service.revoke_session(current_user, token=request.refresh_token)
    return MessageResponse(message="Logged out successfully")


@shared_router.post("/logout-all", response_model=MessageResponse, summary="Logout all sessions")
async def logout_all(
    current_user: CurrentUser,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    await auth_service.revoke_session(current_user, all_sessions=True)
    return MessageResponse(message="Logged out from all devices")


router.include_router(customer_router, tags=["Customer Authentication"])
router.include_router(shopkeeper_router, tags=["Shopkeeper Authentication"])
router.include_router(shared_router, tags=["Shared Authentication"])
