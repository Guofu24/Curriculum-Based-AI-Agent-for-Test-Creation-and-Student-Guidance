"""Auth router with JWT + bcrypt + refresh token rotation."""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.services.auth_service import AuthService
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshTokenRequest,
    AuthResponse,
    RefreshResponse,
    UserResponse,
    LogoutResponse,
)
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new teacher account",
    description="Create a new teacher account with email, password, and full name. "
                 "Password is hashed with bcrypt before storage.",
    responses={
        201: {"description": "Teacher account created successfully"},
        400: {"description": "Invalid request data or email already registered"},
        422: {"description": "Validation error in request body"},
    },
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
):
    """Register a new teacher account."""
    service = AuthService(db, redis)
    user = await service.register(
        email=request.email,
        password=request.password,
        full_name=request.full_name,
    )
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login and receive JWT tokens",
    description="Authenticate with email and password. Returns JWT access token "
                 "(15 min TTL) and refresh token (7 day TTL). Refresh token is "
                 "rotated on each use for security.",
    responses={
        200: {"description": "Login successful, tokens returned"},
        401: {"description": "Invalid credentials"},
        422: {"description": "Validation error in request body"},
    },
    example={
        "email": "teacher@school.edu.vn",
        "password": "SecurePassword123!",
    },
)
async def login(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
):
    """Login and receive JWT access + refresh tokens."""
    service = AuthService(db, redis)
    ip_address = get_client_ip(http_request)
    return await service.login(
        email=request.email,
        password=request.password,
        ip_address=ip_address,
    )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access token. "
                 "Uses refresh token rotation — the old refresh token is revoked "
                 "and a new one is issued. Refresh token TTL: 7 days.",
    responses={
        200: {"description": "Access token refreshed successfully"},
        401: {"description": "Refresh token expired or revoked"},
        422: {"description": "Validation error"},
    },
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
):
    """Refresh access token using refresh token rotation."""
    service = AuthService(db, redis)
    return await service.refresh(request.refresh_token)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout and revoke refresh token",
    description="Logout by revoking the provided refresh token. "
                 "The access token remains valid until its TTL expires.",
    responses={
        200: {"description": "Logout successful, refresh token revoked"},
        401: {"description": "Refresh token not found or already revoked"},
        422: {"description": "Validation error"},
    },
)
async def logout(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
):
    """Logout by revoking refresh token."""
    service = AuthService(db, redis)
    await service.logout(request.refresh_token)
    return LogoutResponse()


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
    description="Returns the authenticated user's profile information. "
                 "Requires a valid access token in the Authorization header.",
    responses={
        200: {"description": "Current user profile"},
        401: {"description": "Missing or invalid access token"},
    },
)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user information."""
    return UserResponse.model_validate(current_user)
