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


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
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


@router.post("/login", response_model=AuthResponse)
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


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
):
    """Refresh access token using refresh token rotation."""
    service = AuthService(db, redis)
    return await service.refresh(request.refresh_token)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
):
    """Logout by revoking refresh token."""
    service = AuthService(db, redis)
    await service.logout(request.refresh_token)
    return LogoutResponse()


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user information."""
    return UserResponse.model_validate(current_user)
