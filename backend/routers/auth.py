"""
Authentication Router — Complete Auth System

Endpoints:
- POST /register         → Đăng ký tài khoản mới
- POST /login            → Đăng nhập, trả về access + refresh token
- POST /logout           → Đăng xuất, blacklist token
- POST /refresh-token    → Cấp access token mới bằng refresh token
- GET  /me               → Lấy thông tin user hiện tại
- GET  /verify-email     → Xác thực email qua link

Bảo mật:
- Mật khẩu hash bằng bcrypt
- JWT access token (15 phút) + refresh token (7 ngày)
- Token blacklist server-side khi logout
- Rate limiting chống brute-force
- Input validation chống injection
- Error messages chung (không tiết lộ chi tiết)
- Security event logging
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.user import User
from models.token_blacklist import TokenBlacklist
from schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshTokenResponse,
    UserResponse,
    UserCreate,
    RefreshTokenRequest,
    LogoutRequest,
    MessageResponse,
)
from utils.security import (
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
from utils.email import send_verification_email
from utils.rate_limit import check_login_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /register — Đăng ký tài khoản mới
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Request:
#   POST /api/v1/auth/register
#   {
#     "email": "teacher@example.com",
#     "password": "MySecure1Pass",
#     "full_name": "Nguyễn Văn A",
#     "department": "Khoa CNTT",
#     "university": "ĐH Bách Khoa"
#   }
#
# Response (201):
#   {
#     "id": "uuid-here",
#     "email": "teacher@example.com",
#     "full_name": "Nguyễn Văn A",
#     "department": "Khoa CNTT",
#     "university": "ĐH Bách Khoa",
#     "is_email_verified": false
#   }
#
# Error (400): { "detail": "Email đã được đăng ký" }
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ký tài khoản mới",
)
async def register(request: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Đăng ký tài khoản mới.
    
    Flow:
    1. Validate input (Pydantic schema tự động kiểm tra email format, password strength)
    2. Kiểm tra email chưa tồn tại trong DB
    3. Hash mật khẩu bằng bcrypt
    4. Tạo user mới (is_email_verified = False)
    5. Gửi email xác thực (hoặc log link trong dev mode)
    6. Trả về thông tin user (KHÔNG trả về password)
    """
    # Bước 2: Kiểm tra email đã tồn tại chưa
    existing = await db.execute(
        select(User).where(User.email == request.email)
    )
    if existing.scalar_one_or_none():
        # Bảo mật: Thông báo chung, nhưng ở đây cho UX tốt
        # vẫn báo email đã tồn tại (trade-off giữa UX và privacy)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email đã được đăng ký",
        )

    # Bước 3 + 4: Hash mật khẩu & tạo user
    # Development mode: tự động verify email (không cần SMTP)
    # Production mode: yêu cầu verify qua email thật
    auto_verify = settings.APP_ENV == "development"

    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),  # bcrypt hash
        full_name=request.full_name,
        department=request.department,
        university=request.university,
        is_email_verified=auto_verify,
    )
    db.add(user)
    await db.flush()  # Flush để có user.id

    # Bước 5: Gửi email xác thực (chỉ trong production)
    if not auto_verify:
        await send_verification_email(user.id, user.email)
    else:
        logger.info(f"[DEV MODE] Auto-verified email for {user.email}")

    logger.info(f"[REGISTER] New user registered: email={user.email}, id={user.id}")
    return user


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /login — Đăng nhập
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Request:
#   POST /api/v1/auth/login
#   {
#     "email": "teacher@example.com",
#     "password": "MySecure1Pass",
#     "totp_code": "123456"          ← optional, chỉ nếu bật 2FA
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
# Error (401): { "detail": "Email hoặc mật khẩu không đúng" }
# Error (403): { "detail": "Email chưa được xác thực..." }
# Error (429): { "detail": "Quá nhiều lần thử đăng nhập..." }
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Đăng nhập",
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(check_login_rate_limit),  # Rate limiting
):
    """
    Đăng nhập bằng email + mật khẩu.
    
    Flow:
    1. Rate limit check (chống brute-force, 5 lần/phút)
    2. Tìm user theo email
    3. Verify mật khẩu bằng bcrypt
    4. Kiểm tra email đã xác thực
    5. Kiểm tra 2FA (nếu đã bật)
    6. Tạo access token (15 phút) + refresh token (7 ngày)
    7. Reset failed login attempts
    8. Trả về tokens

    Bảo mật:
    - Luôn trả lỗi chung "Email hoặc mật khẩu không đúng"
    - KHÔNG tiết lộ email có tồn tại hay không
    - Rate limiting per IP
    """
    # Lỗi chung cho mọi trường hợp login thất bại
    # (chống user/email enumeration attack)
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email hoặc mật khẩu không đúng",
    )

    # Bước 2: Tìm user
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()

    if not user:
        # Bảo mật: vẫn trả cùng lỗi, không tiết lộ email không tồn tại
        logger.warning(f"[LOGIN FAILED] Unknown email attempt: {request.email}")
        raise invalid_credentials

    # Bước 3: Verify mật khẩu
    if not verify_password(request.password, user.hashed_password):
        # Tracking brute-force: tăng failed_login_attempts
        user.failed_login_attempts += 1
        user.last_failed_login = datetime.utcnow()
        await db.flush()
        logger.warning(
            f"[LOGIN FAILED] Wrong password: email={user.email}, "
            f"attempt #{user.failed_login_attempts}"
        )
        raise invalid_credentials

    # Bước 4: Kiểm tra email đã verify chưa
    if not user.is_email_verified:
        logger.info(f"[LOGIN BLOCKED] Unverified email: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email chưa được xác thực. Vui lòng kiểm tra hộp thư để xác thực tài khoản.",
        )

    # Bước 5: Kiểm tra tài khoản còn active
    if not user.is_active:
        logger.warning(f"[LOGIN BLOCKED] Inactive account: {user.email}")
        raise invalid_credentials

    # Bước 5b: Kiểm tra 2FA (nếu user đã bật)
    if user.totp_secret:
        if not request.totp_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Yêu cầu mã xác thực 2FA (TOTP code)",
            )
        # Verify TOTP code
        try:
            import pyotp
            totp = pyotp.TOTP(user.totp_secret)
            if not totp.verify(request.totp_code, valid_window=1):
                logger.warning(f"[LOGIN FAILED] Invalid 2FA code: {user.email}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Mã xác thực 2FA không hợp lệ",
                )
        except ImportError:
            logger.error("pyotp not installed — 2FA verification skipped")

    # Bước 6: Tạo access token + refresh token
    access_token, access_jti = create_access_token(user.id, user.email)
    refresh_token, refresh_jti = create_refresh_token(user.id, user.email)

    # Bước 7: Reset failed login attempts (login thành công)
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /logout — Đăng xuất
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Request:
#   POST /api/v1/auth/logout
#   Headers: Authorization: Bearer <access_token>
#   Body: { "refresh_token": "eyJhbGci..." }
#
# Response (200):
#   { "message": "Đăng xuất thành công" }
#
# Error (401): { "detail": "Could not validate credentials" }
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Đăng xuất",
)
async def logout(
    request: LogoutRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Đăng xuất — hủy cả access token và refresh token.
    
    Flow:
    1. Xác thực user qua access token (get_current_user dependency)
    2. Decode refresh token để lấy JTI
    3. Blacklist cả access token JTI và refresh token JTI
    4. Trả về success message
    
    Client-side: Sau khi nhận response, client phải:
    - Xóa access token khỏi localStorage/memory
    - Xóa refresh token khỏi cookie/localStorage
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

    # Decode refresh token để lấy JTI
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

    return MessageResponse(message="Đăng xuất thành công")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /refresh-token — Cấp access token mới
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
# Error (401): { "detail": "Refresh token không hợp lệ hoặc đã hết hạn" }
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post(
    "/refresh-token",
    response_model=RefreshTokenResponse,
    summary="Cấp access token mới",
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Cấp access token mới bằng refresh token hợp lệ.
    
    Flow:
    1. Decode refresh token → validate chữ ký + thời hạn
    2. Kiểm tra token type phải là "refresh"
    3. Kiểm tra token chưa bị blacklist (user chưa logout)
    4. Kiểm tra user vẫn active
    5. Tạo access token mới
    6. Trả về access token mới

    Bảo mật: Refresh token KHÔNG bị thay đổi (rotation có thể thêm sau).
    """
    invalid_token = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token không hợp lệ hoặc đã hết hạn",
    )

    # Bước 1: Decode
    payload = decode_token(request.refresh_token)
    if payload is None:
        raise invalid_token

    # Bước 2: Kiểm tra type
    if payload.get("type") != "refresh":
        raise invalid_token

    user_id = payload.get("sub")
    jti = payload.get("jti")
    email = payload.get("email")

    if not user_id or not jti or not email:
        raise invalid_token

    # Bước 3: Kiểm tra blacklist
    if await is_token_blacklisted(jti, db):
        logger.warning(f"[REFRESH DENIED] Blacklisted refresh token: jti={jti}")
        raise invalid_token

    # Bước 4: Kiểm tra user vẫn active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise invalid_token

    # Bước 5: Tạo access token mới
    new_access_token, _ = create_access_token(user.id, user.email)

    logger.info(f"[REFRESH] New access token issued: user={user.email}")

    return RefreshTokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /verify-email — Xác thực email
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Request:
#   GET /api/v1/auth/verify-email?token=eyJhbGci...
#
# Response (200):
#   { "message": "Email đã được xác thực thành công" }
#
# Error (400): { "detail": "Token xác thực không hợp lệ hoặc đã hết hạn" }
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get(
    "/verify-email",
    response_model=MessageResponse,
    summary="Xác thực email",
)
async def verify_email(
    token: str = Query(..., description="Token xác thực từ email"),
    db: AsyncSession = Depends(get_db),
):
    """
    Xác thực email qua link được gửi khi đăng ký.
    
    Flow:
    1. Decode verification token
    2. Kiểm tra type = "email_verification"
    3. Tìm user trong DB
    4. Đánh dấu is_email_verified = True
    """
    invalid_token = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Token xác thực không hợp lệ hoặc đã hết hạn",
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
            message="Email đã được xác thực trước đó",
        )

    user.is_email_verified = True
    await db.flush()

    logger.info(f"[VERIFY EMAIL] email={user.email}, id={user.id}")

    return MessageResponse(message="Email đã được xác thực thành công")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /me — Lấy thông tin user hiện tại
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Request:
#   GET /api/v1/auth/me
#   Headers: Authorization: Bearer <access_token>
#
# Response (200):
#   {
#     "id": "uuid-here",
#     "email": "teacher@example.com",
#     "full_name": "Nguyễn Văn A",
#     "department": "Khoa CNTT",
#     "university": "ĐH Bách Khoa",
#     "is_email_verified": true
#   }
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Lấy thông tin user hiện tại",
)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Lấy thông tin profile user hiện tại.
    Yêu cầu: Access token hợp lệ trong header Authorization.
    """
    return current_user
