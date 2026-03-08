"""
Authentication Schemas

Pydantic models cho request/response validation.
Sử dụng EmailStr để validate email format, và custom validator cho mật khẩu.

Bảo mật:
- Input validation tại tầng schema giúp chống injection attacks
- Password validation đảm bảo mật khẩu đủ mạnh
- EmailStr validate format email hợp lệ
"""
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional


# ─── Request Schemas ────────────────────────────────────────────────

class UserCreate(BaseModel):
    """Schema đăng ký tài khoản mới."""
    email: EmailStr                       # Validate format email tự động
    password: str
    full_name: str
    department: Optional[str] = None
    university: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Kiểm tra mật khẩu đủ mạnh:
        - Tối thiểu 8 ký tự
        - Ít nhất 1 chữ hoa
        - Ít nhất 1 chữ thường
        - Ít nhất 1 số
        """
        if len(v) < 8:
            raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
        if not any(c.isupper() for c in v):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ hoa")
        if not any(c.islower() for c in v):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ thường")
        if not any(c.isdigit() for c in v):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ số")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        """Tên không được rỗng hoặc chỉ có khoảng trắng."""
        if not v or not v.strip():
            raise ValueError("Tên không được để trống")
        return v.strip()


class LoginRequest(BaseModel):
    """Schema đăng nhập."""
    email: EmailStr
    password: str
    totp_code: Optional[str] = None       # Mã 2FA (nếu user đã bật)


class RefreshTokenRequest(BaseModel):
    """Schema yêu cầu cấp access token mới bằng refresh token."""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Schema đăng xuất — gửi refresh token để hủy cả cặp token."""
    refresh_token: str


# ─── Response Schemas ───────────────────────────────────────────────

class TokenResponse(BaseModel):
    """Response trả về khi login thành công."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int                        # Seconds until access token expires


class RefreshTokenResponse(BaseModel):
    """Response trả về khi refresh token thành công."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """Response thông tin user (không bao giờ trả về password)."""
    id: str
    email: str
    full_name: str
    department: Optional[str] = None
    university: Optional[str] = None
    is_email_verified: bool = False

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Response message chung cho các thao tác thành công."""
    message: str
    detail: Optional[str] = None
