"""
Authentication Router

Handles login, token generation, and user management.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt
from passlib.context import CryptContext

from config import settings
from database import get_db
from models.user import User
from schemas.auth import LoginRequest, TokenResponse, UserResponse, UserCreate

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    # In production, extract token from Authorization header
) -> User:
    """Dependency: Get current authenticated user."""
    # Simplified for MVP — in production use JWT from header
    # For now, return first user or raise
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT token."""
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token)


@router.post("/register", response_model=UserResponse)
async def register(request: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    # Check if email exists
    existing = await db.execute(
        select(User).where(User.email == request.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),
        full_name=request.full_name,
        department=request.department,
        university=request.university,
    )
    db.add(user)
    await db.flush()
    return user


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user profile."""
    return current_user
