from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.mvp import normalize_physics_subject


class CourseCreateRequest(BaseModel):
    course_name: str
    subject: str
    academic_level: Optional[str] = None
    description: Optional[str] = None

    @field_validator("course_name", "subject")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("field cannot be empty")
        return cleaned

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        return normalize_physics_subject(value)


class CourseMembershipResponse(BaseModel):
    user_id: str
    role: str
    full_name: Optional[str] = None
    email: Optional[str] = None


class CourseResponse(BaseModel):
    id: str
    owner_user_id: str
    course_name: str
    subject: str
    academic_level: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    membership_count: int = 0
    document_count: int = 0
    memberships: list[CourseMembershipResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
