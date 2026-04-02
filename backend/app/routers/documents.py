"""Document router per spec — aligned with Phase 5 spec.

Endpoints:
- POST /api/v1/documents/upload — upload S3 → create DB record → trigger Celery task
- GET  /api/v1/documents — list user's documents
- GET  /api/v1/documents/{id} — detail + heading_tree
- GET  /api/v1/documents/{id}/status — processing status
- DELETE /api/v1/documents/{id} — delete DB + S3 + Pinecone vectors
- GET  /api/v1/documents/{id}/refresh-url — generate new presigned URL (G20)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.document_service import DocumentService, DocumentServiceError
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentListItem,
    DocumentDetail,
    DocumentStatus,
    DocumentListResponse,
    RefreshUrlResponse,
    HeadingTree,
    ChapterSchema,
    SectionSchema,
    SubsectionSchema,
)
from app.dependencies import get_current_user
from app.models.user import User
from app.tasks.document_task import process_document_task

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])

# ── Course-scoped document routes (FE-compatible) ─────────────────────────────

# NOTE: documents_by_course is in the documents router so it can reuse the
# existing document_service.list_documents() method.
# It is mounted here so the FE can call:
#   GET /api/v1/courses/{course_id}/documents  →  /api/v1/documents?course_id={course_id}
# The FE also expects:
#   POST /api/v1/courses/{course_id}/documents/upload  →  same as POST /api/v1/documents/upload
# Both are handled by documents_router directly (course_id is optional in the service).


def _doc_to_list_item(doc) -> DocumentListItem:
    """Convert Document model to DocumentListItem schema."""
    return DocumentListItem(
        id=str(doc.id),
        title=doc.original_filename.rsplit(".", 1)[0] if doc.original_filename else "",
        original_filename=doc.original_filename,
        file_name=doc.original_filename,  # FE compatibility alias
        file_type=doc.file_type,
        file_size=getattr(doc, "file_size", 0) or 0,
        processing_status=doc.processing_status,
        status=doc.processing_status,  # FE compatibility alias
        course_id=None,  # FE expects this field; set by course association if needed
        version=getattr(doc, "version", 1) or 1,  # FE compatibility
        total_chapters=doc.total_chapters,
        total_pages_or_slides=doc.total_pages_or_slides or 0,
        total_chunks=doc.total_chunks or 0,
        uploaded_at=doc.uploaded_at,
        updated_at=doc.uploaded_at,  # FE expects updated_at
        curriculum_tree=[],  # FE expects CurriculumNode[]; populated from heading_tree if available
    )


def _heading_tree_from_dict(data: dict | None) -> HeadingTree | None:
    """Convert heading_tree dict to HeadingTree schema."""
    if not data:
        return None
    try:
        chapters = []
        for ch in data.get("chapters", []):
            sections = []
            for sec in ch.get("sections", []):
                subsections = [
                    SubsectionSchema(section_id=sub["section_id"], title=sub["title"])
                    for sub in sec.get("subsections", [])
                ]
                sections.append(SectionSchema(
                    section_id=sec["section_id"],
                    title=sec["title"],
                    subsections=subsections,
                ))
            chapters.append(ChapterSchema(
                chapter_id=ch["chapter_id"],
                title=ch["title"],
                sections=sections,
            ))
        return HeadingTree(chapters=chapters)
    except Exception:
        return None


def _doc_to_detail(doc) -> DocumentDetail:
    """Convert Document model to DocumentDetail schema."""
    heading = _heading_tree_from_dict(doc.heading_tree)
    # Build curriculum_tree as plain list of chapter dicts for FE compatibility
    curriculum = []
    if heading:
        curriculum = [
            {
                "id": ch.chapter_id,
                "title": ch.title,
                "section_type": "chapter",
                "section_order": i,
                "chapter_number": i + 1,
                "page_from": None,
                "page_to": None,
                "scope_label": None,
                "summary": None,
                "metadata": None,
                "children": [],
            }
            for i, ch in enumerate(heading.chapters or [])
        ]

    return DocumentDetail(
        id=str(doc.id),
        title=doc.original_filename.rsplit(".", 1)[0] if doc.original_filename else "",
        original_filename=doc.original_filename,
        file_type=doc.file_type,
        file_size=getattr(doc, "file_size", 0) or 0,
        s3_key=doc.s3_key,
        processing_status=doc.processing_status,
        parse_error_message=doc.parse_error_message,
        heading_tree=heading,
        total_chapters=doc.total_chapters,
        total_pages_or_slides=doc.total_pages_or_slides or 0,
        total_chunks=doc.total_chunks or 0,
        uploaded_at=doc.uploaded_at,
        language=None,  # FE expects language; set via metadata or default 'vi'
        curriculum_tree=curriculum,  # FE compatibility: CurriculumNode[]
    )


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for RAG processing",
    description="Upload a PDF, DOCX, or PPTX file to S3 storage. Creates a DB record "
                 "and triggers the Celery document-processing pipeline in background. "
                 "Poll /documents/{id}/status to track processing progress.",
    responses={
        201: {"description": "Document uploaded and processing started"},
        400: {"description": "Unsupported file type or file too large (>100MB)"},
        401: {"description": "Authentication required"},
        422: {"description": "Validation error in request body"},
    },
    tags=["Documents"],
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = None,
    language: str | None = None,
    course_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a document for processing. Triggers the RAG pipeline in background.

    Optional query params (FE compatibility — align with frontend FormData fields):
    - title: display name for the document
    - language: source language code (default "vi")
    - course_id: optional course association
    """
    allowed_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Allowed: PDF, DOCX, PPTX",
        )

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 100MB.",
        )

    service = DocumentService(db)
    try:
        document = await service.upload_document(
            user_id=current_user.id,
            file_content=content,
            filename=file.filename or "document",
        )
    except DocumentServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Trigger Celery task for background RAG processing
    process_document_task.delay(str(document.id))

    return DocumentUploadResponse(
        document_id=document.id,
        message="Document uploaded. Processing started in background.",
        s3_key=document.s3_key,
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List all user documents",
    description="Returns a paginated list of all documents owned by the authenticated user. "
                 "Documents are sorted by upload date (newest first).",
    responses={
        200: {"description": "Paginated list of documents"},
        401: {"description": "Authentication required"},
    },
    tags=["Documents"],
)
async def list_documents(
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all documents for the current user."""
    service = DocumentService(db)
    documents, total = await service.list_documents(
        user_id=current_user.id,
        page=page,
        limit=limit,
    )
    return DocumentListResponse(
        items=[_doc_to_list_item(d) for d in documents],
        total=total,
        page=page,
        limit=limit,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetail,
    summary="Get document details",
    description="Returns full document metadata including heading_tree (chapters, sections, "
                 "subsections), processing status, chunk counts, and S3 key.",
    responses={
        200: {"description": "Document details with heading_tree"},
        401: {"description": "Authentication required"},
        404: {"description": "Document not found"},
    },
    tags=["Documents"],
)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get document details including heading_tree."""
    service = DocumentService(db)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return _doc_to_detail(document)


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatus,
    summary="Get document processing status",
    description="Returns the current processing status of a document: pending, processing, "
                 "completed, or failed. Use this to poll for completion after upload.",
    responses={
        200: {"description": "Current processing status"},
        401: {"description": "Authentication required"},
        404: {"description": "Document not found"},
    },
    tags=["Documents"],
)
async def get_document_status(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get document processing status."""
    service = DocumentService(db)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return DocumentStatus(
        id=str(document.id),
        processing_status=document.processing_status,
        parse_error_message=document.parse_error_message,
        total_pages_or_slides=document.total_pages_or_slides or 0,
        total_chunks=document.total_chunks or 0,
        uploaded_at=document.uploaded_at,
    )


@router.delete(
    "/{document_id}",
    summary="Delete a document",
    description="Permanently removes a document from the database, S3 storage, and "
                 "Pinecone vector store. This action cannot be undone.",
    responses={
        200: {"description": "Document deleted successfully"},
        401: {"description": "Authentication required"},
        404: {"description": "Document not found"},
    },
    tags=["Documents"],
)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document: removes from DB, S3, and Pinecone vectors."""
    service = DocumentService(db)
    deleted = await service.delete_document(document_id, current_user.id)

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return {"message": "Document deleted successfully"}


@router.get(
    "/{document_id}/refresh-url",
    response_model=RefreshUrlResponse,
    summary="Generate a new presigned download URL (G20)",
    description="Generates a fresh presigned S3 URL for downloading the document. "
                 "Use this when the previous URL has expired (default TTL: 1 hour). "
                 "Document must be in processing or completed state.",
    responses={
        200: {"description": "Fresh presigned URL generated"},
        400: {"description": "Document processing has not started yet"},
        401: {"description": "Authentication required"},
        404: {"description": "Document not found"},
    },
    tags=["Documents"],
)
async def refresh_document_url(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a fresh presigned URL for downloading the document (G20).
    Used when the previous presigned URL has expired.
    """
    service = DocumentService(db)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.processing_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document processing has not started yet.",
        )

    presigned_url = service.get_presigned_url(document)

    return RefreshUrlResponse(
        presigned_url=presigned_url,
        expires_in=3600,
    )
