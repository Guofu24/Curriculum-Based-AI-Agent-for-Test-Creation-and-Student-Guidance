"""
Security Utilities â€” JWT & Password Management

Module chá»©a táº¥t cáº£ logic báº£o máº­t cho há»‡ thá»‘ng authentication:
- Password hashing vá»›i bcrypt (one-way hash, chá»‘ng rainbow table)
- JWT token creation/validation vá»›i JTI (JWT ID) cho tá»«ng token
- Token blacklist checking (há»— trá»£ logout server-side)
- FastAPI dependency `get_current_user` Ä‘á»ƒ báº£o vá»‡ cÃ¡c endpoint

NguyÃªn táº¯c báº£o máº­t:
1. Má»i máº­t kháº©u Ä‘Æ°á»£c hash báº±ng bcrypt trÆ°á»›c khi lÆ°u DB
2. JWT chá»©a JTI duy nháº¥t â€” khi logout, JTI Ä‘Æ°á»£c thÃªm vÃ o blacklist
3. Access token ngáº¯n háº¡n (15 phÃºt), refresh token dÃ i háº¡n (7 ngÃ y)
4. KhÃ´ng bao giá» tráº£ lá»—i chi tiáº¿t cho client (chá»‘ng enumeration attack)
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

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.token_blacklist import TokenBlacklist

logger = logging.getLogger(__name__)

# â”€â”€â”€ Password Hashing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# bcrypt: thuáº­t toÃ¡n hash má»™t chiá»u, tá»± Ä‘á»™ng táº¡o salt, chá»‘ng brute-force
# báº±ng cost factor (máº·c Ä‘á»‹nh rounds=12)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash máº­t kháº©u báº±ng bcrypt. KhÃ´ng bao giá» lÆ°u plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """So sÃ¡nh máº­t kháº©u plaintext vá»›i hash Ä‘Ã£ lÆ°u trong DB."""
    return pwd_context.verify(plain_password, hashed_password)


# â”€â”€â”€ JWT Token Creation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def create_access_token(user_id: str, email: str) -> tuple[str, str]:
    """
    Táº¡o JWT access token (ngáº¯n háº¡n).

    Returns:
        tuple: (token_string, jti) â€” tráº£ vá» cáº£ JTI Ä‘á»ƒ cÃ³ thá»ƒ blacklist
    
    Payload chá»©a:
        - sub: user ID
        - email: email user
        - jti: JWT ID duy nháº¥t (UUID) â€” dÃ¹ng cho blacklist khi logout
        - type: "access" â€” phÃ¢n biá»‡t vá»›i refresh token
        - exp: thá»i Ä‘iá»ƒm háº¿t háº¡n
        - iat: thá»i Ä‘iá»ƒm táº¡o
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
    Táº¡o JWT refresh token (dÃ i háº¡n â€” 7 ngÃ y máº·c Ä‘á»‹nh).

    Returns:
        tuple: (token_string, jti)
    
    Refresh token dÃ¹ng Ä‘á»ƒ xin access token má»›i khi access token háº¿t háº¡n,
    mÃ  khÃ´ng cáº§n user nháº­p láº¡i máº­t kháº©u.
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
    Táº¡o JWT token cho xÃ¡c thá»±c email (24 giá» máº·c Ä‘á»‹nh).
    Token nÃ y Ä‘Æ°á»£c gá»­i qua email cho user, khi user click link â†’ verify email.
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


# â”€â”€â”€ JWT Token Decoding â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def decode_token(token: str) -> Optional[dict]:
    """
    Decode vÃ  validate JWT token.
    
    Returns:
        dict payload náº¿u token há»£p lá»‡, None náº¿u token khÃ´ng há»£p lá»‡/háº¿t háº¡n.
    
    Báº£o máº­t: DÃ¹ng cÃ¹ng SECRET_KEY vÃ  ALGORITHM Ä‘Ã£ dÃ¹ng khi táº¡o token.
    python-jose tá»± Ä‘á»™ng kiá»ƒm tra chá»¯ kÃ½ vÃ  thá»i háº¡n (exp).
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except ExpiredSignatureError:
        logger.warning("Token Ä‘Ã£ háº¿t háº¡n")
        return None
    except JWTError as e:
        logger.warning(f"Token khÃ´ng há»£p lá»‡: {e}")
        return None


# â”€â”€â”€ Token Blacklist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def is_token_blacklisted(jti: str, db: AsyncSession) -> bool:
    """
    Kiá»ƒm tra token (theo JTI) cÃ³ náº±m trong blacklist khÃ´ng.
    ÄÆ°á»£c gá»i má»—i khi validate token â€” náº¿u Ä‘Ã£ blacklist thÃ¬ tá»« chá»‘i.
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
    ThÃªm token vÃ o blacklist (gá»i khi user logout).
    
    Args:
        jti: JWT ID cá»§a token cáº§n há»§y
        token_type: "access" hoáº·c "refresh"
        user_id: ID user sá»Ÿ há»¯u token
        expires_at: thá»i Ä‘iá»ƒm token háº¿t háº¡n tá»± nhiÃªn (Ä‘á»ƒ cleanup sau)
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


# â”€â”€â”€ FastAPI Dependency: Get Current User â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# HTTPBearer scheme â€” trÃ­ch xuáº¥t token tá»« header "Authorization: Bearer <token>"
security_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency â€” xÃ¡c thá»±c user tá»« JWT access token.
    
    Flow:
    1. TrÃ­ch xuáº¥t token tá»« Authorization header (Bearer scheme)
    2. Decode vÃ  validate JWT
    3. Kiá»ƒm tra token type pháº£i lÃ  "access"
    4. Kiá»ƒm tra token khÃ´ng náº±m trong blacklist
    5. TÃ¬m user trong DB, kiá»ƒm tra is_active
    6. Tráº£ vá» User object

    Báº£o máº­t: LuÃ´n tráº£ lá»—i chung "Could not validate credentials"
    (khÃ´ng tiáº¿t lá»™ lÃ½ do cá»¥ thá»ƒ cho attacker).
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

    # Chá»‰ cháº¥p nháº­n access token (khÃ´ng cháº¥p nháº­n refresh token)
    if payload.get("type") != "access":
        raise credentials_exception

    user_id: str = payload.get("sub")
    jti: str = payload.get("jti")
    if user_id is None or jti is None:
        raise credentials_exception

    # Kiá»ƒm tra token Ä‘Ã£ bá»‹ blacklist chÆ°a (user Ä‘Ã£ logout)
    if await is_token_blacklisted(jti, db):
        logger.warning(f"Blacklisted token used: jti={jti}, user_id={user_id}")
        raise credentials_exception

    # TÃ¬m user trong database
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

