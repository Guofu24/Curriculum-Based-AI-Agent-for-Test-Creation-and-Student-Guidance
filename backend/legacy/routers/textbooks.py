"""
Textbooks Router

Handles textbook upload, listing, details, and deletion.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from core.mvp import normalize_mvp_language, require_pdf_extension
from database import get_db
from models.user import User
from routers.auth import get_current_user
from schemas.textbook import TextbookResponse, TextbookListResponse
from services.textbook_service import TextbookService
from config import settings
from utils.security import require_roles
from models.user import UserRole

router = APIRouter(prefix="/textbooks", tags=["textbooks"])


@router.post("/upload", response_model=TextbookResponse)
async def upload_textbook(
    title: str = Form(...),
    course_id: str | None = Form(None),
    language: str = Form("vi"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """Upload a textbook file for processing."""
    file_ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    try:
        file_ext = require_pdf_extension(file_ext)
        language = normalize_mvp_language(language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Validate file size
    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum: {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    service = TextbookService(db)
    textbook = await service.upload_textbook(
        user_id=current_user.id,
        title=title,
        file_name=file.filename,
        file_content=content,
        file_type=file_ext.lstrip("."),
        course_id=course_id,
        language=language,
    )

    return textbook


@router.get("/", response_model=list[TextbookListResponse])
async def list_textbooks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all textbooks for the current user."""
    service = TextbookService(db)
    textbooks = await service.get_textbooks(current_user.id)

    return [
        TextbookListResponse(
            id=tb.id,
            course_id=tb.course_id,
            title=tb.title,
            file_name=tb.file_name,
            file_type=tb.file_type,
            file_size=tb.file_size,
            status=tb.status.value,
            version=tb.version,
            total_pages_or_slides=tb.total_pages_or_slides,
            total_chunks=tb.total_chunks,
            chapter_count=len(tb.chapters),
            created_at=tb.created_at,
            updated_at=tb.updated_at,
        )
        for tb in textbooks
    ]


@router.get("/{textbook_id}", response_model=TextbookResponse)
async def get_textbook(
    textbook_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """Get textbook details with chapters."""
    service = TextbookService(db)
    textbook = await service.get_textbook(textbook_id, current_user.id)

    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    return textbook


@router.delete("/{textbook_id}")
async def delete_textbook(
    textbook_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a textbook and its vector data."""
    service = TextbookService(db)
    deleted = await service.delete_textbook(textbook_id, current_user.id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Textbook not found")

    return {"message": "Textbook deleted successfully"}
