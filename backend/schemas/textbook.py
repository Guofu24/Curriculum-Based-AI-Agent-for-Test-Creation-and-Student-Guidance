from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChapterResponse(BaseModel):
    id: str
    chapter_number: int
    title: str
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    summary: Optional[str] = None
    key_concepts: Optional[list] = None

    model_config = {"from_attributes": True}


class TextbookResponse(BaseModel):
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
    chapters: list[ChapterResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TextbookListResponse(BaseModel):
    id: str
    course_id: Optional[str] = None
    title: str
    file_name: str
    file_type: str
    file_size: int
    status: str
    version: int
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    chapter_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
