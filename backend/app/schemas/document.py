"""Document schemas - aligned with frontend's API expectations."""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Any, Literal


# ── Curriculum ─────────────────────────────────────────────────────────────────

class CurriculumNode(BaseModel):
    """Schema matching frontend's CurriculumNode interface."""
    id: str | None = None
    title: str
    section_type: str = "topic"
    section_order: int = 0
    chapter_number: int = 0
    page_from: int | None = None
    page_to: int | None = None
    scope_label: str | None = None
    summary: str | None = None
    metadata: dict | None = None
    children: list["CurriculumNode"] = []


class CurriculumNodeResponse(BaseModel):
    """Schema matching the response type for curriculum nodes."""
    id: str | None = None
    title: str
    section_type: str = "topic"
    section_order: int = 0
    chapter_number: int = 0
    page_from: int | None = None
    page_to: int | None = None
    scope_label: str | None = None
    summary: str | None = None
    metadata: dict | None = None
    children: list["CurriculumNodeResponse"] = []


class CurriculumTreePatchRequest(BaseModel):
    """Schema for patching curriculum tree."""
    curriculum_tree: list[CurriculumNodeResponse]


# ── Document Responses ─────────────────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    """Schema for document upload response."""
    document_id: UUID
    message: str = "Document uploaded successfully"
    s3_key: str


class DocumentListItem(BaseModel):
    """Schema matching frontend's DocumentListItem."""
    id: str
    course_id: str | None = None
    title: str
    file_name: str
    file_type: str
    file_size: int = 0
    status: str
    version: int = 1
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    chapter_count: int | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentListResponse(BaseModel):
    """Schema for document list response."""
    items: list[DocumentListItem]
    total: int
    page: int = 1
    limit: int = 20


class DocumentDetail(BaseModel):
    """Schema matching frontend's Document."""
    id: str
    course_id: str | None = None
    title: str
    file_name: str
    file_type: str
    file_size: int = 0
    file_hash: str | None = None
    file_storage_url: str | None = None
    language: str | None = "vi"
    status: str
    version: int = 1
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    created_at: datetime
    updated_at: datetime | None = None
    curriculum_tree: list[CurriculumNode] = []


class DocumentResponse(BaseModel):
    """Schema for document response matching frontend's Document interface."""
    id: str
    course_id: str | None = None
    title: str
    file_name: str
    file_type: str
    file_size: int = 0
    file_hash: str | None = None
    file_storage_url: str | None = None
    language: str | None = "vi"
    status: str
    version: int = 1
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    chapter_count: int | None = None
    created_at: datetime
    updated_at: datetime | None = None
    curriculum_tree: list[CurriculumNodeResponse] = []


class DocumentStatus(BaseModel):
    """Schema matching frontend's DocumentStatus."""
    id: str
    course_id: str | None = None
    status: str
    parse_error_message: str | None = None
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    updated_at: datetime | None = None


class DocumentStatusResponse(BaseModel):
    """Schema for document status response."""
    id: str
    course_id: str | None = None
    status: str
    parse_error_message: str | None = None
    total_pages_or_slides: int = 0
    total_chunks: int = 0
    updated_at: datetime | None = None


# ── Scope ──────────────────────────────────────────────────────────────────────

class ScopeUnitPayload(BaseModel):
    """Schema matching frontend's ScopeUnitPayload."""
    scope_id: str | None = None
    section_id: str | None = None
    scope_type: str = "topic"
    title: str | None = None
    chapter_number: int = 0
    page_from: int | None = None
    page_to: int | None = None
    tags: list[str] = []


class DocumentUpdateTreeRequest(BaseModel):
    """Schema for updating curriculum tree."""
    curriculum_tree: list[CurriculumNode]
