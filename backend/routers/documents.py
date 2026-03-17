from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.user import User
from routers.auth import get_current_user
from schemas.document import (
    CurriculumNodeResponse,
    CurriculumTreePatchRequest,
    DocumentResponse,
    DocumentStatusResponse,
)
from services.document_service import DocumentService
from utils.security import require_roles
from models.user import UserRole

router = APIRouter(tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt"}


def _build_curriculum_nodes(tree: list[dict]) -> list[CurriculumNodeResponse]:
    nodes: list[CurriculumNodeResponse] = []
    for node in tree or []:
        nodes.append(
            CurriculumNodeResponse(
                id=node.get("id"),
                title=node.get("title", "Untitled Section"),
                section_type=node.get("section_type", "topic"),
                section_order=int(node.get("section_order", 0) or 0),
                chapter_number=int(node.get("chapter_number", 0) or 0),
                page_from=node.get("page_from"),
                page_to=node.get("page_to"),
                scope_label=node.get("scope_label"),
                summary=node.get("summary"),
                metadata=node.get("metadata"),
                children=_build_curriculum_nodes(node.get("children") or []),
            )
        )
    return nodes


def _format_document(document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        course_id=document.course_id,
        title=document.title,
        file_name=document.file_name,
        file_type=document.file_type,
        file_size=document.file_size,
        file_hash=document.file_hash,
        file_storage_url=document.file_storage_url,
        language=document.language,
        status=document.status.value,
        version=document.version,
        total_pages_or_slides=document.total_pages_or_slides,
        total_chunks=document.total_chunks,
        created_at=document.created_at,
        updated_at=document.updated_at,
        curriculum_tree=_build_curriculum_nodes(document.curriculum_tree_json or []),
    )


@router.post("/courses/{course_id}/documents/upload", response_model=DocumentResponse)
async def upload_document(
    course_id: str,
    title: str = Form(...),
    file: UploadFile = File(...),
    language: str = Form("vi"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    file_ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum: {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    service = DocumentService(db)
    try:
        document = await service.upload_textbook(
            user_id=current_user.id,
            title=title,
            file_name=file.filename,
            file_content=content,
            file_type=file_ext.lstrip("."),
            course_id=course_id,
            language=language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _format_document(document)


@router.get("/courses/{course_id}/documents", response_model=list[DocumentResponse])
async def list_course_documents(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = DocumentService(db)
    documents = await service.get_textbooks(user_id=current_user.id, course_id=course_id)
    return [_format_document(document) for document in documents]


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = DocumentService(db)
    status_payload = await service.get_document_status(document_id, current_user.id)
    if not status_payload:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentStatusResponse(**status_payload)


@router.get("/documents/{document_id}/curriculum-tree", response_model=list[CurriculumNodeResponse])
async def get_curriculum_tree(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = DocumentService(db)
    tree = await service.get_curriculum_tree(document_id, current_user.id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _build_curriculum_nodes(tree)


@router.patch("/documents/{document_id}/curriculum-tree", response_model=list[CurriculumNodeResponse])
async def patch_curriculum_tree(
    document_id: str,
    request: CurriculumTreePatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    service = DocumentService(db)
    document = await service.update_curriculum_tree(
        document_id=document_id,
        user_id=current_user.id,
        curriculum_tree=[item.model_dump() for item in request.curriculum_tree],
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return _build_curriculum_nodes(document.curriculum_tree_json or [])
