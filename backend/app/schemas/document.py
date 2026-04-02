"""Document schemas — aligned with spec and updated model."""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Any, Literal


# ── Upload Response ────────────────────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    """
    Response from POST /api/v1/documents/upload.

    - **document_id**: UUID of the newly created document record
    - **s3_key**: S3 object key where the file is stored
    - **message**: Confirmation message

    After upload, poll GET /documents/{id}/status until status='completed'.
    """
    document_id: UUID = Field(..., description="UUID of the newly created document record.")
    message: str = Field(
        default="Document uploaded. Processing started in background.",
        description="Confirmation message.",
    )
    s3_key: str = Field(..., description="S3 object key where the file is stored.")


# ── Heading Tree (spec format: chapters/sections/subsections) ─────────────────

class SubsectionSchema(BaseModel):
    """Subsection within a section."""
    section_id: str
    title: str


class SectionSchema(BaseModel):
    """Section within a chapter."""
    section_id: str
    title: str
    subsections: list[SubsectionSchema] = []


class ChapterSchema(BaseModel):
    """Chapter in the heading tree."""
    chapter_id: str
    title: str
    sections: list[SectionSchema] = []


class HeadingTree(BaseModel):
    """Document heading tree per spec format."""
    chapters: list[ChapterSchema] = []


# ── Document Responses ────────────────────────────────────────────────────────

class DocumentListItem(BaseModel):
    """
    Document summary in list view.

    - **id**: Document UUID
    - **title**: Document title (derived from filename without extension)
    - **file_name**: Alias for original_filename (FE compatibility)
    - **status**: Alias for processing_status (FE compatibility)
    - **processing_status**: One of 'pending', 'processing', 'completed', 'failed'
    - **total_chapters**: Number of chapters detected in the document
    - **total_pages_or_slides**: Total pages (PDF/DOCX) or slides (PPTX)
    - **total_chunks**: Number of text chunks stored in Pinecone
    """
    id: str = Field(..., description="Document UUID.")
    title: str = Field(..., description="Document title derived from filename.")
    original_filename: str = Field(..., description="Original uploaded filename.")
    file_name: str = Field(..., description="Alias for original_filename (FE compatibility).")
    file_type: str = Field(..., description="File type: 'pdf', 'docx', or 'pptx'.")
    file_size: int = Field(default=0, description="File size in bytes.")
    processing_status: str = Field(
        ...,
        description="Processing status: 'pending', 'processing', 'completed', or 'failed'.",
    )
    status: str = Field(
        ...,
        description="Alias for processing_status (FE compatibility).",
    )
    course_id: str | None = Field(None, description="Associated course ID (FE compatibility).")
    version: int = Field(default=1, description="Document version number (FE compatibility).")
    chapter_count: int | None = Field(None, description="Number of chapters (FE compatibility).")
    updated_at: datetime | None = Field(None, description="Last update timestamp (FE compatibility).")
    curriculum_tree: list = Field(
        default_factory=list,
        description="CurriculumNode[] list (FE compatibility). Populated from heading_tree.",
    )
    total_chapters: int | None = Field(
        None,
        description="Number of chapters detected in the heading_tree.",
    )
    total_pages_or_slides: int = Field(
        default=0,
        description="Total pages (PDF/DOCX) or slides (PPTX).",
    )
    total_chunks: int = Field(
        default=0,
        description="Number of text chunks indexed in Pinecone.",
    )
    uploaded_at: datetime


class DocumentDetail(BaseModel):
    """
    Full document detail including heading_tree.

    - **heading_tree**: Hierarchical structure of chapters, sections, and subsections
      detected from the document. Used for scope selection during exam generation.
    - **s3_key**: Internal S3 object key (not a public URL)
    """
    id: str = Field(..., description="Document UUID.")
    title: str = Field(..., description="Document title derived from filename.")
    original_filename: str = Field(..., description="Original uploaded filename.")
    file_type: str = Field(..., description="File type: 'pdf', 'docx', or 'pptx'.")
    file_size: int = Field(default=0, description="File size in bytes.")
    s3_key: str | None = Field(None, description="Internal S3 object key.")
    processing_status: str = Field(
        ...,
        description="Processing status: 'pending', 'processing', 'completed', or 'failed'.",
    )
    parse_error_message: str | None = Field(
        None,
        description="Error message if processing failed.",
    )
    heading_tree: HeadingTree | None = Field(
        None,
        description="Hierarchical heading structure. Use this for scope selection.",
    )
    total_chapters: int | None = Field(
        None,
        description="Number of chapters in the heading_tree.",
    )
    total_pages_or_slides: int = Field(
        default=0,
        description="Total pages (PDF/DOCX) or slides (PPTX).",
    )
    total_chunks: int = Field(
        default=0,
        description="Number of text chunks indexed in Pinecone.",
    )
    uploaded_at: datetime
    updated_at: datetime | None = Field(None, description="Last update timestamp.")
    language: str | None = Field(
        None,
        description="Source document language (FE compatibility). Defaults to 'vi'.",
    )
    curriculum_tree: list = Field(
        default_factory=list,
        description="Alias for heading_tree chapters (FE compatibility).",
    )


class DocumentResponse(BaseModel):
    """
    Document response schema — alias of DocumentDetail matching the frontend Document interface.
    """
    id: str = Field(..., description="Document UUID.")
    title: str = Field(..., description="Document title derived from filename.")
    original_filename: str = Field(..., description="Original uploaded filename.")
    file_type: str = Field(..., description="File type: 'pdf', 'docx', or 'pptx'.")
    file_size: int = Field(default=0, description="File size in bytes.")
    processing_status: str = Field(..., description="Processing status.")
    total_chapters: int | None = Field(None, description="Number of chapters.")
    total_pages_or_slides: int = Field(default=0, description="Total pages or slides.")
    total_chunks: int = Field(default=0, description="Number of Pinecone chunks.")
    uploaded_at: datetime = Field(..., description="Upload timestamp (UTC).")
    heading_tree: HeadingTree | None = Field(
        None,
        description="Hierarchical heading structure for scope selection.",
    )


class DocumentListResponse(BaseModel):
    """
    Paginated document list response.

    - **items**: List of DocumentListItem for the current page
    - **total**: Total number of documents across all pages
    - **page**: Current page number (1-indexed)
    - **limit**: Items per page
    """
    items: list[DocumentListItem]
    total: int = Field(..., description="Total number of documents across all pages.")
    page: int = Field(default=1, description="Current page number (1-indexed).")
    limit: int = Field(default=20, description="Number of items per page.")


# ── Processing Status ─────────────────────────────────────────────────────────

class DocumentStatus(BaseModel):
    """
    Document processing status returned by GET /documents/{id}/status.

    - **processing_status**: Current state: 'pending', 'processing', 'completed', 'failed'
    """
    id: str = Field(..., description="Document UUID.")
    processing_status: str = Field(
        ...,
        description="Processing status: 'pending', 'processing', 'completed', or 'failed'.",
    )
    parse_error_message: str | None = Field(None, description="Error message if failed.")
    total_pages_or_slides: int = Field(default=0, description="Total pages or slides.")
    total_chunks: int = Field(default=0, description="Number of Pinecone chunks.")
    uploaded_at: datetime | None = Field(None, description="Upload timestamp (UTC).")


# ── Scope / Flattened Tree ────────────────────────────────────────────────────

class ScopeUnit(BaseModel):
    """Flattened scope unit for scope selection."""
    id: str = Field(..., description="Unique identifier for this scope unit.")
    title: str = Field(..., description="Display title.")
    level: int = Field(..., description="Scope level: 1=chapter, 2=section, 3=subsection.")
    chapter_id: str = Field(..., description="Parent chapter ID.")
    path: str = Field(..., description="Human-readable path: 'Chapter > Section > Subsection'.")


# ── Refresh URL Response ───────────────────────────────────────────────────────

class RefreshUrlResponse(BaseModel):
    """Response from GET /documents/{id}/refresh-url (G20)."""
    presigned_url: str = Field(
        ...,
        description="Fresh presigned S3 URL. Valid for 3600 seconds (1 hour).",
    )
    expires_in: int = Field(default=3600, description="URL validity in seconds.")
