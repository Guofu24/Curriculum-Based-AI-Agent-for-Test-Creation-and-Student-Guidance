"""Auth service with JWT + bcrypt + refresh token rotation."""

from datetime import datetime, timedelta
from uuid import UUID
import hashlib

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.dependencies import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.redis_client import RedisClient
from app.core.config import get_settings

settings = get_settings()

# Rate limit: max login attempts per IP per minute
MAX_LOGIN_ATTEMPTS = 5


class AuthService:
    """Authentication service handling all auth operations."""

    def __init__(self, db: AsyncSession, redis: RedisClient):
        self.db = db
        self.redis = redis

    async def register(
        self,
        email: str,
        password: str,
        full_name: str | None = None,
    ) -> User:
        """Register a new user."""
        # Check if email already exists
        existing = await self.db.execute(
            select(User).where(User.email == email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Create user
        user = User(
            email=email,
            password_hash=get_password_hash(password),
            full_name=full_name,
            role="teacher",
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def login(self, email: str, password: str, ip_address: str) -> dict:
        """Login user and return tokens with refresh token rotation."""
        # Rate limiting
        rate_limit_key = f"ratelimit:login:{ip_address}"
        attempts = await self.redis.incr_rate_limit(rate_limit_key, 60)
        if attempts > MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please wait a minute.",
            )

        # Find user
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Generate tokens
        access_token = create_access_token(data={"sub": str(user.id)})
        refresh_token = create_refresh_token(str(user.id))

        # Store refresh token (hash)
        expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        db_refresh_token = RefreshToken(
            user_id=user.id,
            token_hash=RefreshToken.hash_token(refresh_token),
            expires_at=expires_at,
        )
        self.db.add(db_refresh_token)
        await self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def refresh(self, refresh_token: str) -> dict:
        """Refresh access token with refresh token rotation."""
        payload = decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        user_id = payload.get("sub")
        token_hash = RefreshToken.hash_token(refresh_token)

        # Verify refresh token in DB
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == UUID(user_id),
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,
                RefreshToken.expires_at > datetime.utcnow(),
            )
        )
        db_token = result.scalar_one_or_none()

        if not db_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        # Revoke old token (rotation)
        db_token.revoked = True

        # Generate new tokens
        access_token = create_access_token(data={"sub": user_id})
        new_refresh_token = create_refresh_token(user_id)

        # Store new refresh token
        expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        new_db_token = RefreshToken(
            user_id=UUID(user_id),
            token_hash=RefreshToken.hash_token(new_refresh_token),
            expires_at=expires_at,
        )
        self.db.add(new_db_token)
        await self.db.commit()

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def logout(self, refresh_token: str) -> bool:
        """Logout by revoking the refresh token."""
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        token_hash = RefreshToken.hash_token(refresh_token)

        # Revoke the token
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        db_token = result.scalar_one_or_none()

        if db_token:
            db_token.revoked = True
            await self.db.commit()

        return True

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
