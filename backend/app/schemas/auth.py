"""
Authentication schemas.
"""
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


class UserCreate(BaseModel):
    """Register a new account."""

    email: EmailStr
    password: str
    full_name: str
    role: str = "lecturer"
    department: Optional[str] = None
    university: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
        if not any(char.isupper() for char in value):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ hoa")
        if not any(char.islower() for char in value):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ thường")
        if not any(char.isdigit() for char in value):
            raise ValueError("Mật khẩu phải có ít nhất 1 chữ số")
        return value

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Tên không được để trống")
        return value.strip()

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = (value or "lecturer").strip().lower()
        allowed = {"admin", "lecturer", "teaching_assistant", "student"}
        if normalized not in allowed:
            raise ValueError(f"role must be one of: {', '.join(sorted(allowed))}")
        return normalized


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    department: Optional[str] = None
    university: Optional[str] = None
    is_email_verified: bool = False

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None
