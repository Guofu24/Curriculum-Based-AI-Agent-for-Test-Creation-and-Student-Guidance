"""Auth schemas for request/response validation."""

from pydantic import BaseModel, EmailStr, Field
from uuid import UUID


class UserCreate(BaseModel):
    """Schema for user registration - used by the API router."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)
    department: str | None = Field(None, max_length=255)
    university: str | None = Field(None, max_length=255)
    role: str = "teacher"


class RegisterRequest(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)
    department: str | None = Field(None, max_length=255)
    university: str | None = Field(None, max_length=255)


class LoginRequest(BaseModel):
    """Schema for user login - matches frontend's expected interface."""
    email: EmailStr
    password: str
    totp_code: str | None = None  # Optional 2FA code


class RefreshTokenRequest(BaseModel):
    """Schema for token refresh."""
    refresh_token: str


class TokenResponse(BaseModel):
    """Schema for authentication response - matches frontend's TokenResponse."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AuthResponse(BaseModel):
    """Schema for authentication response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshTokenResponse(BaseModel):
    """Schema for refresh token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshResponse(BaseModel):
    """Schema for refresh token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserResponse(BaseModel):
    """Schema for user information - matches frontend's User interface."""
    id: UUID
    email: str
    full_name: str | None = None
    department: str | None = None
    university: str | None = None
    role: str = "teacher"
    is_email_verified: bool = False

    class Config:
        from_attributes = True


class LogoutRequest(BaseModel):
    """Schema for logout request."""
    refresh_token: str


class LogoutResponse(BaseModel):
    """Schema for logout response."""
    message: str = "Logged out successfully"


class MessageResponse(BaseModel):
    """Schema for generic message response."""
    message: str


class ClarificationQuestion(BaseModel):
    """Schema for clarification questions from Orchestrator."""
    question_id: str
    question: str
    context: str | None = None


class ClarificationResponse(BaseModel):
    """Schema for clarification request response."""
    clarification_questions: list[ClarificationQuestion]


class RewriteRequirementsRequest(BaseModel):
    """Schema for requirement rewrite confirmation."""
    approved: bool
    modifications: str | None = None
