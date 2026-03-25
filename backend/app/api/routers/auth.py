"""
Authentication Router â€” Complete Auth System

Endpoints:
- POST /register         â†’ ÄÄƒng kÃ½ tÃ i khoáº£n má»›i
- POST /login            â†’ ÄÄƒng nháº­p, tráº£ vá» access + refresh token
- POST /logout           â†’ ÄÄƒng xuáº¥t, blacklist token
- POST /refresh-token    â†’ Cáº¥p access token má»›i báº±ng refresh token
- GET  /me               â†’ Láº¥y thÃ´ng tin user hiá»‡n táº¡i
- GET  /verify-email     â†’ XÃ¡c thá»±c email qua link

Báº£o máº­t:
- Máº­t kháº©u hash báº±ng bcrypt
- JWT access token (15 phÃºt) + refresh token (7 ngÃ y)
- Token blacklist server-side khi logout
- Rate limiting chá»‘ng brute-force
- Input validation chá»‘ng injection
- Error messages chung (khÃ´ng tiáº¿t lá»™ chi tiáº¿t)
- Security event logging
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.token_blacklist import TokenBlacklist
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshTokenResponse,
    UserResponse,
    UserCreate,
    RefreshTokenRequest,
    LogoutRequest,
    MessageResponse,
)
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    is_token_blacklisted,
    blacklist_token,
    get_current_user,
    security_scheme,
)
from app.utils.email import send_verification_email
from app.utils.rate_limit import check_login_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# POST /register â€” ÄÄƒng kÃ½ tÃ i khoáº£n má»›i
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
#
# Request:
#   POST /api/v1/auth/register
#   {
#     "email": "teacher@example.com",
#     "password": "MySecure1Pass",
#     "full_name": "Nguyá»…n VÄƒn A",
#     "department": "Khoa CNTT",
#     "university": "ÄH BÃ¡ch Khoa"
#   }
#
# Response (201):
#   {
#     "id": "uuid-here",
#     "email": "teacher@example.com",
#     "full_name": "Nguyá»…n VÄƒn A",
#     "department": "Khoa CNTT",
#     "university": "ÄH BÃ¡ch Khoa",
#     "is_email_verified": false
#   }
#
# Error (400): { "detail": "Email Ä‘Ã£ Ä‘Æ°á»£c Ä‘Äƒng kÃ½" }
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="ÄÄƒng kÃ½ tÃ i khoáº£n má»›i",
)
async def register(request: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    ÄÄƒng kÃ½ tÃ i khoáº£n má»›i.
    
    Flow:
    1. Validate input (Pydantic schema tá»± Ä‘á»™ng kiá»ƒm tra email format, password strength)
    2. Kiá»ƒm tra email chÆ°a tá»“n táº¡i trong DB
    3. Hash máº­t kháº©u báº±ng bcrypt
    4. Táº¡o user má»›i (is_email_verified = False)
    5. Gá»­i email xÃ¡c thá»±c (hoáº·c log link trong dev mode)
    6. Tráº£ vá» thÃ´ng tin user (KHÃ”NG tráº£ vá» password)
    """
    # BÆ°á»›c 2: Kiá»ƒm tra email Ä‘Ã£ tá»“n táº¡i chÆ°a
    existing = await db.execute(
        select(User).where(User.email == request.email)
    )
    if existing.scalar_one_or_none():
        # Báº£o máº­t: ThÃ´ng bÃ¡o chung, nhÆ°ng á»Ÿ Ä‘Ã¢y cho UX tá»‘t
        # váº«n bÃ¡o email Ä‘Ã£ tá»“n táº¡i (trade-off giá»¯a UX vÃ  privacy)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email Ä‘Ã£ Ä‘Æ°á»£c Ä‘Äƒng kÃ½",
        )

    # BÆ°á»›c 3 + 4: Hash máº­t kháº©u & táº¡o user
    # Development mode: tá»± Ä‘á»™ng verify email (khÃ´ng cáº§n SMTP)
    # Production mode: yÃªu cáº§u verify qua email tháº­t
    auto_verify = settings.APP_ENV == "development"

    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),  # bcrypt hash
        full_name=request.full_name,
        role=UserRole(request.role),
        department=request.department,
        university=request.university,
        is_email_verified=auto_verify,
    )
    db.add(user)
    await db.flush()  # Flush Ä‘á»ƒ cÃ³ user.id

    # BÆ°á»›c 5: Gá»­i email xÃ¡c thá»±c (chá»‰ trong production)
    if not auto_verify:
        await send_verification_email(user.id, user.email)
    else:
        logger.info(f"[DEV MODE] Auto-verified email for {user.email}")

    logger.info(f"[REGISTER] New user registered: email={user.email}, id={user.id}")
    return user


# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# POST /login â€” ÄÄƒng nháº­p
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
#
# Request:
#   POST /api/v1/auth/login
#   {
#     "email": "teacher@example.com",
#     "password": "MySecure1Pass",
#     "totp_code": "123456"          â† optional, chá»‰ náº¿u báº­t 2FA
#   }
#
# Response (200):
#   {
#     "access_token": "eyJhbGci...",
#     "refresh_token": "eyJhbGci...",
#     "token_type": "bearer",
#     "expires_in": 900
#   }
#
# Error (401): { "detail": "Email hoáº·c máº­t kháº©u khÃ´ng Ä‘Ãºng" }
# Error (403): { "detail": "Email chÆ°a Ä‘Æ°á»£c xÃ¡c thá»±c..." }
# Error (429): { "detail": "QuÃ¡ nhiá»u láº§n thá»­ Ä‘Äƒng nháº­p..." }
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="ÄÄƒng nháº­p",
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(check_login_rate_limit),  # Rate limiting
):
    """
    ÄÄƒng nháº­p báº±ng email + máº­t kháº©u.
    
    Flow:
    1. Rate limit check (chá»‘ng brute-force, 5 láº§n/phÃºt)
    2. TÃ¬m user theo email
    3. Verify máº­t kháº©u báº±ng bcrypt
    4. Kiá»ƒm tra email Ä‘Ã£ xÃ¡c thá»±c
    5. Kiá»ƒm tra 2FA (náº¿u Ä‘Ã£ báº­t)
    6. Táº¡o access token (15 phÃºt) + refresh token (7 ngÃ y)
    7. Reset failed login attempts
    8. Tráº£ vá» tokens

    Báº£o máº­t:
    - LuÃ´n tráº£ lá»—i chung "Email hoáº·c máº­t kháº©u khÃ´ng Ä‘Ãºng"
    - KHÃ”NG tiáº¿t lá»™ email cÃ³ tá»“n táº¡i hay khÃ´ng
    - Rate limiting per IP
    """
    # Lá»—i chung cho má»i trÆ°á»ng há»£p login tháº¥t báº¡i
    # (chá»‘ng user/email enumeration attack)
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email hoáº·c máº­t kháº©u khÃ´ng Ä‘Ãºng",
    )

    # BÆ°á»›c 2: TÃ¬m user
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()

    if not user:
        # Báº£o máº­t: váº«n tráº£ cÃ¹ng lá»—i, khÃ´ng tiáº¿t lá»™ email khÃ´ng tá»“n táº¡i
        logger.warning(f"[LOGIN FAILED] Unknown email attempt: {request.email}")
        raise invalid_credentials

    # BÆ°á»›c 3: Verify máº­t kháº©u
    if not verify_password(request.password, user.hashed_password):
        # Tracking brute-force: tÄƒng failed_login_attempts
        user.failed_login_attempts += 1
        user.last_failed_login = datetime.utcnow()
        await db.flush()
        logger.warning(
            f"[LOGIN FAILED] Wrong password: email={user.email}, "
            f"attempt #{user.failed_login_attempts}"
        )
        raise invalid_credentials

    # BÆ°á»›c 4: Kiá»ƒm tra email Ä‘Ã£ verify chÆ°a
    if not user.is_email_verified:
        logger.info(f"[LOGIN BLOCKED] Unverified email: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email chÆ°a Ä‘Æ°á»£c xÃ¡c thá»±c. Vui lÃ²ng kiá»ƒm tra há»™p thÆ° Ä‘á»ƒ xÃ¡c thá»±c tÃ i khoáº£n.",
        )

    # BÆ°á»›c 5: Kiá»ƒm tra tÃ i khoáº£n cÃ²n active
    if not user.is_active:
        logger.warning(f"[LOGIN BLOCKED] Inactive account: {user.email}")
        raise invalid_credentials

    # BÆ°á»›c 5b: Kiá»ƒm tra 2FA (náº¿u user Ä‘Ã£ báº­t)
    if user.totp_secret:
        if not request.totp_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="YÃªu cáº§u mÃ£ xÃ¡c thá»±c 2FA (TOTP code)",
            )
        # Verify TOTP code
        try:
            import pyotp
            totp = pyotp.TOTP(user.totp_secret)
            if not totp.verify(request.totp_code, valid_window=1):
                logger.warning(f"[LOGIN FAILED] Invalid 2FA code: {user.email}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="MÃ£ xÃ¡c thá»±c 2FA khÃ´ng há»£p lá»‡",
                )
        except ImportError:
            logger.error("pyotp not installed â€” 2FA verification skipped")

    # BÆ°á»›c 6: Táº¡o access token + refresh token
    access_token, access_jti = create_access_token(user.id, user.email)
    refresh_token, refresh_jti = create_refresh_token(user.id, user.email)

    # BÆ°á»›c 7: Reset failed login attempts (login thÃ nh cÃ´ng)
    user.failed_login_attempts = 0
    user.last_failed_login = None
    await db.flush()

    logger.info(f"[LOGIN SUCCESS] email={user.email}, id={user.id}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
    )


# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# POST /logout â€” ÄÄƒng xuáº¥t
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
#
# Request:
#   POST /api/v1/auth/logout
#   Headers: Authorization: Bearer <access_token>
#   Body: { "refresh_token": "eyJhbGci..." }
#
# Response (200):
#   { "message": "ÄÄƒng xuáº¥t thÃ nh cÃ´ng" }
#
# Error (401): { "detail": "Could not validate credentials" }
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="ÄÄƒng xuáº¥t",
)
async def logout(
    request: LogoutRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    ÄÄƒng xuáº¥t â€” há»§y cáº£ access token vÃ  refresh token.
    
    Flow:
    1. XÃ¡c thá»±c user qua access token (get_current_user dependency)
    2. Decode refresh token Ä‘á»ƒ láº¥y JTI
    3. Blacklist cáº£ access token JTI vÃ  refresh token JTI
    4. Tráº£ vá» success message
    
    Client-side: Sau khi nháº­n response, client pháº£i:
    - XÃ³a access token khá»i localStorage/memory
    - XÃ³a refresh token khá»i cookie/localStorage
    """
    # Decode and blacklist current access token
    access_payload = decode_token(credentials.credentials)
    if (
        access_payload
        and access_payload.get("type") == "access"
        and access_payload.get("jti")
        and access_payload.get("exp")
    ):
        await blacklist_token(
            jti=access_payload["jti"],
            token_type="access",
            user_id=current_user.id,
            expires_at=datetime.utcfromtimestamp(access_payload["exp"]),
            db=db,
        )

    # Decode refresh token Ä‘á»ƒ láº¥y JTI
    refresh_payload = decode_token(request.refresh_token)
    if refresh_payload and refresh_payload.get("type") == "refresh":
        # Blacklist refresh token
        await blacklist_token(
            jti=refresh_payload["jti"],
            token_type="refresh",
            user_id=current_user.id,
            expires_at=datetime.utcfromtimestamp(refresh_payload["exp"]),
            db=db,
        )

    logger.info(f"[LOGOUT] user={current_user.email}, id={current_user.id}")

    return MessageResponse(message="ÄÄƒng xuáº¥t thÃ nh cÃ´ng")


# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# POST /refresh-token â€” Cáº¥p access token má»›i
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
#
# Request:
#   POST /api/v1/auth/refresh-token
#   { "refresh_token": "eyJhbGci..." }
#
# Response (200):
#   {
#     "access_token": "eyJhbGci...(new)",
#     "token_type": "bearer",
#     "expires_in": 900
#   }
#
# Error (401): { "detail": "Refresh token khÃ´ng há»£p lá»‡ hoáº·c Ä‘Ã£ háº¿t háº¡n" }
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

@router.post(
    "/refresh-token",
    response_model=RefreshTokenResponse,
    summary="Cáº¥p access token má»›i",
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Cáº¥p access token má»›i báº±ng refresh token há»£p lá»‡.
    
    Flow:
    1. Decode refresh token â†’ validate chá»¯ kÃ½ + thá»i háº¡n
    2. Kiá»ƒm tra token type pháº£i lÃ  "refresh"
    3. Kiá»ƒm tra token chÆ°a bá»‹ blacklist (user chÆ°a logout)
    4. Kiá»ƒm tra user váº«n active
    5. Táº¡o access token má»›i
    6. Tráº£ vá» access token má»›i

    Báº£o máº­t: Refresh token KHÃ”NG bá»‹ thay Ä‘á»•i (rotation cÃ³ thá»ƒ thÃªm sau).
    """
    invalid_token = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token khÃ´ng há»£p lá»‡ hoáº·c Ä‘Ã£ háº¿t háº¡n",
    )

    # BÆ°á»›c 1: Decode
    payload = decode_token(request.refresh_token)
    if payload is None:
        raise invalid_token

    # BÆ°á»›c 2: Kiá»ƒm tra type
    if payload.get("type") != "refresh":
        raise invalid_token

    user_id = payload.get("sub")
    jti = payload.get("jti")
    email = payload.get("email")

    if not user_id or not jti or not email:
        raise invalid_token

    # BÆ°á»›c 3: Kiá»ƒm tra blacklist
    if await is_token_blacklisted(jti, db):
        logger.warning(f"[REFRESH DENIED] Blacklisted refresh token: jti={jti}")
        raise invalid_token

    # BÆ°á»›c 4: Kiá»ƒm tra user váº«n active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise invalid_token

    # BÆ°á»›c 5: Táº¡o access token má»›i
    new_access_token, _ = create_access_token(user.id, user.email)

    logger.info(f"[REFRESH] New access token issued: user={user.email}")

    return RefreshTokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# GET /verify-email â€” XÃ¡c thá»±c email
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
#
# Request:
#   GET /api/v1/auth/verify-email?token=eyJhbGci...
#
# Response (200):
#   { "message": "Email Ä‘Ã£ Ä‘Æ°á»£c xÃ¡c thá»±c thÃ nh cÃ´ng" }
#
# Error (400): { "detail": "Token xÃ¡c thá»±c khÃ´ng há»£p lá»‡ hoáº·c Ä‘Ã£ háº¿t háº¡n" }
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

@router.get(
    "/verify-email",
    response_model=MessageResponse,
    summary="XÃ¡c thá»±c email",
)
async def verify_email(
    token: str = Query(..., description="Token xÃ¡c thá»±c tá»« email"),
    db: AsyncSession = Depends(get_db),
):
    """
    XÃ¡c thá»±c email qua link Ä‘Æ°á»£c gá»­i khi Ä‘Äƒng kÃ½.
    
    Flow:
    1. Decode verification token
    2. Kiá»ƒm tra type = "email_verification"
    3. TÃ¬m user trong DB
    4. ÄÃ¡nh dáº¥u is_email_verified = True
    """
    invalid_token = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Token xÃ¡c thá»±c khÃ´ng há»£p lá»‡ hoáº·c Ä‘Ã£ háº¿t háº¡n",
    )

    payload = decode_token(token)
    if payload is None:
        raise invalid_token

    if payload.get("type") != "email_verification":
        raise invalid_token

    user_id = payload.get("sub")
    if not user_id:
        raise invalid_token

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise invalid_token

    if user.is_email_verified:
        return MessageResponse(
            message="Email Ä‘Ã£ Ä‘Æ°á»£c xÃ¡c thá»±c trÆ°á»›c Ä‘Ã³",
        )

    user.is_email_verified = True
    await db.flush()

    logger.info(f"[VERIFY EMAIL] email={user.email}, id={user.id}")

    return MessageResponse(message="Email Ä‘Ã£ Ä‘Æ°á»£c xÃ¡c thá»±c thÃ nh cÃ´ng")


# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
# GET /me â€” Láº¥y thÃ´ng tin user hiá»‡n táº¡i
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
#
# Request:
#   GET /api/v1/auth/me
#   Headers: Authorization: Bearer <access_token>
#
# Response (200):
#   {
#     "id": "uuid-here",
#     "email": "teacher@example.com",
#     "full_name": "Nguyá»…n VÄƒn A",
#     "department": "Khoa CNTT",
#     "university": "ÄH BÃ¡ch Khoa",
#     "is_email_verified": true
#   }
# â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Láº¥y thÃ´ng tin user hiá»‡n táº¡i",
)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Láº¥y thÃ´ng tin profile user hiá»‡n táº¡i.
    YÃªu cáº§u: Access token há»£p lá»‡ trong header Authorization.
    """
    return current_user

