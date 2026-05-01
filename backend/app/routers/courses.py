"""Courses router — placeholder stubs.

Backlog: full course management.
Currently no course model exists; documents are uploaded independently.
These stubs prevent FE from throwing 404 errors on course-related calls.
"""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/courses", tags=["Courses"])


@router.get("/", response_model=list[dict])
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List courses for current user. Placeholder — returns empty list until course model is implemented."""
    _ = db
    return []


@router.get("/{course_id}", response_model=dict)
async def get_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get course detail. Placeholder."""
    _ = db
    _ = current_user
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Courses not yet implemented. Upload documents directly.",
    )


@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_course(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a course. Placeholder."""
    _ = db
    _ = current_user
    _ = data
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Courses not yet implemented.",
    )


@router.get("/{course_id}/documents")
async def list_course_documents(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List documents in a course."""
    from app.services.document_service import DocumentService
    service = DocumentService(db)
    docs, _ = await service.list_documents(
        user_id=current_user.id,
        page=1,
        limit=100,
        course_id=str(course_id),
    )
    return [_doc_to_list_item(d) for d in docs]


@router.post("/{course_id}/documents/upload", status_code=status.HTTP_201_CREATED)
async def upload_document_to_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload document to a course. Note: course_id is stored as metadata only."""
    _ = course_id
    _ = db
    _ = current_user
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Document upload to course not yet implemented. Upload directly via /documents/upload.",
    )


def _doc_to_list_item(doc) -> dict:
    """Convert a Document model to a plain dict matching the FE's DocumentListItem."""
    return {
        "id": str(doc.id),
        "course_id": str(doc.course_id) if doc.course_id else None,
        "title": doc.original_filename.rsplit(".", 1)[0] if doc.original_filename else "",
        "original_filename": doc.original_filename,
        "file_name": doc.original_filename,
        "file_type": doc.file_type or "",
        "file_size": 0,
        "status": doc.processing_status or "pending",
        "processing_status": doc.processing_status or "pending",
        "version": 1,
        "total_pages_or_slides": doc.total_pages_or_slides or 0,
        "total_chunks": doc.total_chunks or 0,
        "created_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "updated_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
    }
