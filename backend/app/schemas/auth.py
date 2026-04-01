"""Auth schemas for request/response validation."""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID


class RegisterRequest(BaseModel):
    """
    Schema for user registration (Phase 3 spec).

    - **email**: Valid email address, must be unique per system
    - **password**: Minimum 8 characters; stored as bcrypt hash
    - **full_name**: Display name shown in the UI (optional)
    """
    email: EmailStr = Field(
        ...,
        description="Valid email address. Must be unique per system.",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password for the account. Minimum 8 characters. Will be hashed with bcrypt.",
    )
    full_name: str | None = Field(
        None,
        max_length=255,
        description="Display name of the teacher shown in the UI.",
    )


class LoginRequest(BaseModel):
    """
    Schema for user login.

    - **email**: Registered email address
    - **password**: Plain text password (verified against bcrypt hash)
    """
    email: EmailStr = Field(
        ...,
        description="Registered email address of the teacher account.",
    )
    password: str = Field(..., description="Plain text password for the account.")


class RefreshTokenRequest(BaseModel):
    """
    Schema for access token refresh.

    - **refresh_token**: Valid refresh token issued during login.
      Refresh tokens expire after 7 days and are rotated on each use.
    """
    refresh_token: str = Field(
        ...,
        description="JWT refresh token. Obtained from the login response.",
    )


class AuthResponse(BaseModel):
    """
    Authentication response returned after successful login.

    - **access_token**: JWT access token. Use in Authorization header as `Bearer <token>`.
      Valid for 15 minutes by default.
    - **refresh_token**: JWT refresh token. Use to obtain a new access token via POST /auth/refresh.
      Valid for 7 days. Rotated on each use.
    - **token_type**: Always 'bearer'.
    - **expires_in**: Access token lifetime in seconds.

    Example:
    ```json
    {
      "access_token": "eyJhbGciOiJIUzI1NiIs...",
      "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
      "token_type": "bearer",
      "expires_in": 900
    }
    ```
    """
    access_token: str = Field(..., description="JWT access token. Use as `Bearer <token>` in Authorization header.")
    refresh_token: str = Field(..., description="JWT refresh token. Use POST /auth/refresh to get a new access token.")
    token_type: str = Field(default="bearer", description="Token type. Always 'bearer'.")
    expires_in: int = Field(..., description="Access token lifetime in seconds. Default: 900 (15 minutes).")


class RefreshResponse(BaseModel):
    """
    Token refresh response.

    Returns a new access token after a valid refresh token is provided.
    The old refresh token is revoked and a new one is issued (rotation).
    """
    access_token: str = Field(..., description="New JWT access token.")
    token_type: str = Field(default="bearer", description="Token type. Always 'bearer'.")
    expires_in: int = Field(..., description="New access token lifetime in seconds.")


class UserResponse(BaseModel):
    """
    User profile response — returned by GET /auth/me and after registration.

    - **id**: UUID of the user account
    - **email**: User's email address (unique)
    - **full_name**: Display name shown in the UI (optional)
    - **role**: User role. Currently always 'teacher'
    - **created_at**: Account creation timestamp (UTC)
    """
    id: UUID
    email: str
    full_name: str | None = Field(
        None,
        description="Display name of the teacher shown in the UI.",
    )
    role: str = Field(default="teacher", description="User role. Currently always 'teacher'.")
    created_at: datetime

    model_config = {"from_attributes": True}


class LogoutResponse(BaseModel):
    """
    Logout response.

    The refresh token has been revoked server-side.
    The access token remains valid until its TTL expires (15 minutes).
    """
    message: str = Field(
        default="Logged out successfully.",
        description="Confirmation message.",
    )
