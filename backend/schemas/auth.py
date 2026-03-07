from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    department: Optional[str] = None
    university: Optional[str] = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    department: Optional[str] = None
    university: Optional[str] = None
