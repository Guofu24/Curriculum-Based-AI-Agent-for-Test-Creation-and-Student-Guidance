from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CurriculumNodeResponse(BaseModel):
    id: Optional[str] = None
    title: str
    section_type: str = "topic"
    section_order: int = 0
    chapter_number: int = 0
    page_from: Optional[int] = None
    page_to: Optional[int] = None
    scope_label: Optional[str] = None
    summary: Optional[str] = None
    metadata: Optional[dict] = None
    children: list["CurriculumNodeResponse"] = Field(default_factory=list)


class DocumentStatusResponse(BaseModel):
    id: str
    course_id: Optional[str] = None
    status: str
    parse_error_message: Optional[str] = None
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    updated_at: Optional[datetime] = None


class DocumentResponse(BaseModel):
    id: str
    course_id: Optional[str] = None
    title: str
    file_name: str
    file_type: str
    file_size: int
    file_hash: Optional[str] = None
    file_storage_url: Optional[str] = None
    language: Optional[str] = None
    status: str
    version: int
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    curriculum_tree: list[CurriculumNodeResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CurriculumTreePatchRequest(BaseModel):
    curriculum_tree: list[CurriculumNodeResponse] = Field(default_factory=list)


CurriculumNodeResponse.model_rebuild()
