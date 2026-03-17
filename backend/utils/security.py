"""
Security Utilities — JWT & Password Management

Module chứa tất cả logic bảo mật cho hệ thống authentication:
- Password hashing với bcrypt (one-way hash, chống rainbow table)
- JWT token creation/validation với JTI (JWT ID) cho từng token
- Token blacklist checking (hỗ trợ logout server-side)
- FastAPI dependency `get_current_user` để bảo vệ các endpoint

Nguyên tắc bảo mật:
1. Mọi mật khẩu được hash bằng bcrypt trước khi lưu DB
2. JWT chứa JTI duy nhất — khi logout, JTI được thêm vào blacklist
3. Access token ngắn hạn (15 phút), refresh token dài hạn (7 ngày)
4. Không bao giờ trả lỗi chi tiết cho client (chống enumeration attack)
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError, ExpiredSignatureError
from passlib.context import CryptContext

from config import settings
from database import get_db
from models.user import User, UserRole
from models.token_blacklist import TokenBlacklist

logger = logging.getLogger(__name__)

# ─── Password Hashing ──────────────────────────────────────────────

# bcrypt: thuật toán hash một chiều, tự động tạo salt, chống brute-force
# bằng cost factor (mặc định rounds=12)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash mật khẩu bằng bcrypt. Không bao giờ lưu plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """So sánh mật khẩu plaintext với hash đã lưu trong DB."""
    return pwd_context.verify(plain_password, hashed_password)


# ─── JWT Token Creation ────────────────────────────────────────────

def create_access_token(user_id: str, email: str) -> tuple[str, str]:
    """
    Tạo JWT access token (ngắn hạn).

    Returns:
        tuple: (token_string, jti) — trả về cả JTI để có thể blacklist
    
    Payload chứa:
        - sub: user ID
        - email: email user
        - jti: JWT ID duy nhất (UUID) — dùng cho blacklist khi logout
        - type: "access" — phân biệt với refresh token
        - exp: thời điểm hết hạn
        - iat: thời điểm tạo
    """
    jti = str(uuid.uuid4())
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def create_refresh_token(user_id: str, email: str) -> tuple[str, str]:
    """
    Tạo JWT refresh token (dài hạn — 7 ngày mặc định).

    Returns:
        tuple: (token_string, jti)
    
    Refresh token dùng để xin access token mới khi access token hết hạn,
    mà không cần user nhập lại mật khẩu.
    """
    jti = str(uuid.uuid4())
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def create_email_verification_token(user_id: str, email: str) -> str:
    """
    Tạo JWT token cho xác thực email (24 giờ mặc định).
    Token này được gửi qua email cho user, khi user click link → verify email.
    """
    expire = datetime.utcnow() + timedelta(
        hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS
    )
    payload = {
        "sub": user_id,
        "email": email,
        "type": "email_verification",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ─── JWT Token Decoding ────────────────────────────────────────────

def decode_token(token: str) -> Optional[dict]:
    """
    Decode và validate JWT token.
    
    Returns:
        dict payload nếu token hợp lệ, None nếu token không hợp lệ/hết hạn.
    
    Bảo mật: Dùng cùng SECRET_KEY và ALGORITHM đã dùng khi tạo token.
    python-jose tự động kiểm tra chữ ký và thời hạn (exp).
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except ExpiredSignatureError:
        logger.warning("Token đã hết hạn")
        return None
    except JWTError as e:
        logger.warning(f"Token không hợp lệ: {e}")
        return None


# ─── Token Blacklist ───────────────────────────────────────────────

async def is_token_blacklisted(jti: str, db: AsyncSession) -> bool:
    """
    Kiểm tra token (theo JTI) có nằm trong blacklist không.
    Được gọi mỗi khi validate token — nếu đã blacklist thì từ chối.
    """
    result = await db.execute(
        select(TokenBlacklist).where(TokenBlacklist.jti == jti)
    )
    return result.scalar_one_or_none() is not None


async def blacklist_token(
    jti: str, token_type: str, user_id: str,
    expires_at: datetime, db: AsyncSession
) -> None:
    """
    Thêm token vào blacklist (gọi khi user logout).
    
    Args:
        jti: JWT ID của token cần hủy
        token_type: "access" hoặc "refresh"
        user_id: ID user sở hữu token
        expires_at: thời điểm token hết hạn tự nhiên (để cleanup sau)
    """
    blacklisted = TokenBlacklist(
        jti=jti,
        token_type=token_type,
        user_id=user_id,
        expires_at=expires_at,
    )
    db.add(blacklisted)
    await db.flush()
    logger.info(f"Token blacklisted: type={token_type}, user_id={user_id}")


# ─── FastAPI Dependency: Get Current User ──────────────────────────

# HTTPBearer scheme — trích xuất token từ header "Authorization: Bearer <token>"
security_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency — xác thực user từ JWT access token.
    
    Flow:
    1. Trích xuất token từ Authorization header (Bearer scheme)
    2. Decode và validate JWT
    3. Kiểm tra token type phải là "access"
    4. Kiểm tra token không nằm trong blacklist
    5. Tìm user trong DB, kiểm tra is_active
    6. Trả về User object

    Bảo mật: Luôn trả lỗi chung "Could not validate credentials"
    (không tiết lộ lý do cụ thể cho attacker).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    # Chỉ chấp nhận access token (không chấp nhận refresh token)
    if payload.get("type") != "access":
        raise credentials_exception

    user_id: str = payload.get("sub")
    jti: str = payload.get("jti")
    if user_id is None or jti is None:
        raise credentials_exception

    # Kiểm tra token đã bị blacklist chưa (user đã logout)
    if await is_token_blacklisted(jti, db):
        logger.warning(f"Blacklisted token used: jti={jti}, user_id={user_id}")
        raise credentials_exception

    # Tìm user trong database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_exception

    return user


def require_roles(*allowed_roles: UserRole):
    allowed = {role.value if isinstance(role, UserRole) else str(role) for role in allowed_roles}

    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        user_role = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)
        if user_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency
