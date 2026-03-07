from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TextbookResponse(BaseModel):
    id: str
    title: str
    file_name: str
    file_type: str
    file_size: int
    status: str
    version: int
    total_chunks: int
    created_at: datetime
    chapters: list["ChapterResponse"] = []

    model_config = {"from_attributes": True}


class ChapterResponse(BaseModel):
    id: str
    chapter_number: int
    title: str
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    summary: Optional[str] = None
    key_concepts: Optional[str] = None

    model_config = {"from_attributes": True}


class TextbookListResponse(BaseModel):
    id: str
    title: str
    file_name: str
    file_type: str
    file_size: int
    status: str
    version: int
    total_chunks: int
    chapter_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
