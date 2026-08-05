from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from secrets import compare_digest
from typing import Annotated

from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
import structlog

from app.api.v1.router import api_router
from app.api.deps import get_auth_service
from app.core.config import get_settings
from app.schemas.auth import AdminLoginRequest
from app.services.auth_service import AuthService

settings = get_settings()
logger = structlog.get_logger()
EXPECTED_SCHEMA_REVISION = "010"
docs_security = HTTPBasic(auto_error=False)

OPENAPI_TAGS = [
    {
        "name": "Customer Authentication",
        "description": "Customer OTP login, verification, and resend operations.",
    },
    {
        "name": "Shopkeeper Authentication",
        "description": "Shopkeeper OTP login, verification, and resend operations.",
    },
    {
        "name": "Shared Authentication",
        "description": "Authenticated profile, session refresh, and logout operations shared by mobile apps.",
    },
    {
        "name": "Customer APIs",
        "description": "Customer discovery, addresses, favorites, cart, orders, notifications, and rewards.",
    },
    {
        "name": "Shopkeeper APIs",
        "description": "Shop onboarding, catalog, orders, earnings, banking, and reward campaigns.",
    },
    {
        "name": "Customer Scratch Cards",
        "description": "Assigned scratch-card discovery, view tracking, and reward reveal.",
    },
    {
        "name": "Shopkeeper Scratch Cards",
        "description": "Shop-scoped scratch-card verification and redemption.",
    },
    {
        "name": "Customer Reels",
        "description": "Categorized advertising feed, saved reels, likes, views, shares, and CTA engagement.",
    },
    {
        "name": "Shopkeeper Reels",
        "description": "Reel media uploads, publishing lifecycle, management, and engagement analytics.",
    },
    {
        "name": "Payment APIs",
        "description": "Order and shop-activation payment operations.",
    },
    {
        "name": "Admin Authentication",
        "description": "Administrator login and current-admin identity.",
    },
    {
        "name": "Admin APIs",
        "description": "Dashboard, moderation, payments, notifications, settings, and audit operations.",
    },
    {
        "name": "Admin Scratch Cards",
        "description": "Scratch-card lifecycle, distribution, assignments, and analytics.",
    },
    {"name": "Health", "description": "Service health and dependency readiness checks."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != EXPECTED_SCHEMA_REVISION:
            logger.warning(
                "database.schema_revision_mismatch",
                expected=EXPECTED_SCHEMA_REVISION,
                actual=revision,
            )
    except Exception:
        logger.exception("database.startup_check_failed")
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Aranye — Customer & Shopkeeper marketplace API",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def require_docs_auth(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(docs_security)],
) -> str:
    configured_password = (
        settings.api_docs_password.get_secret_value() if settings.api_docs_password else ""
    )
    valid_username = bool(credentials) and compare_digest(
        credentials.username.encode("utf-8"),
        (settings.api_docs_username or "").encode("utf-8"),
    )
    valid_password = bool(credentials) and compare_digest(
        credentials.password.encode("utf-8"),
        configured_password.encode("utf-8"),
    )
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Documentation authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Aranye API documentation"'},
        )
    return credentials.username


def build_public_docs_openapi() -> dict:
    schema = deepcopy(app.openapi())
    schema["paths"] = {
        (path.removeprefix("/api/v1") or "/"): definition
        for path, definition in schema["paths"].items()
    }
    schema["servers"] = [
        {
            "url": settings.public_base_url.rstrip("/"),
            "description": f"{settings.environment.title()} API",
        }
    ]
    return schema


if settings.api_docs_enabled:

    @app.get("/docs", include_in_schema=False)
    async def swagger_docs(_: Annotated[str, Depends(require_docs_auth)]):
        return get_swagger_ui_html(
            openapi_url="./openapi.json",
            title=f"{settings.app_name} - Swagger UI",
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_docs(_: Annotated[str, Depends(require_docs_auth)]):
        return get_redoc_html(
            openapi_url="./openapi.json",
            title=f"{settings.app_name} - ReDoc",
        )

    @app.get("/openapi.json", include_in_schema=False)
    async def protected_openapi(_: Annotated[str, Depends(require_docs_auth)]):
        return JSONResponse(build_public_docs_openapi())

    @app.post("/docs/token", include_in_schema=False)
    async def swagger_admin_token(
        form: Annotated[OAuth2PasswordRequestForm, Depends()],
        _: Annotated[str, Depends(require_docs_auth)],
        auth_service: Annotated[AuthService, Depends(get_auth_service)],
    ):
        tokens = await auth_service.admin_login(
            AdminLoginRequest(email=form.username, password=form.password)
        )
        return {"access_token": tokens.access_token, "token_type": tokens.token_type}

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).resolve().parent.parent / "static"),
    name="static",
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))[:64]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/ready", tags=["Health"])
async def readiness():
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != EXPECTED_SCHEMA_REVISION:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "reason": "database_schema_outdated",
                    "expected_revision": EXPECTED_SCHEMA_REVISION,
                    "actual_revision": revision,
                },
            )
        return {"status": "ready", "database_revision": revision}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
