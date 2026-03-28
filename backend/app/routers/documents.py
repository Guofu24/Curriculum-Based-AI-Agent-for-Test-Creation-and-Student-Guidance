"""Document router: upload, list, status, curriculum-tree, delete - aligned with frontend API."""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID
from typing import Annotated

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.services.document_service import DocumentService, DocumentServiceError
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentListItem,
    DocumentDetail,
    DocumentStatus,
    ScopeUnitPayload,
    DocumentUpdateTreeRequest,
    CurriculumNode,
)
from app.dependencies import get_current_user
from app.models.user import User
from app.models.document import Document
from app.tasks.document_task import process_document_task

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])


def _doc_to_list_item(doc: Document) -> DocumentListItem:
    """Convert Document model to DocumentListItem schema."""
    curriculum_tree = doc.curriculum_tree or []
    chapter_count = len([n for n in curriculum_tree if isinstance(n, dict) and n.get("level") == 1])
    return DocumentListItem(
        id=str(doc.id),
        course_id=str(doc.course_id) if doc.course_id else None,
        title=doc.title or doc.file_name,
        file_name=doc.file_name,
        file_type=doc.file_type,
        file_size=doc.file_size or 0,
        status=doc.status or "pending",
        version=doc.version or 1,
        total_pages_or_slides=doc.total_pages_or_slides or 0,
        total_chunks=doc.total_chunks or 0,
        chapter_count=chapter_count,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _doc_to_detail(doc: Document) -> DocumentDetail:
    """Convert Document model to DocumentDetail schema."""
    tree = doc.curriculum_tree or []
    curriculum_nodes = [_dict_to_curriculum_node(n) for n in tree]
    return DocumentDetail(
        id=str(doc.id),
        course_id=str(doc.course_id) if doc.course_id else None,
        title=doc.title or doc.file_name,
        file_name=doc.file_name,
        file_type=doc.file_type,
        file_size=doc.file_size or 0,
        file_hash=doc.file_hash,
        file_storage_url=doc.file_storage_url,
        language=doc.language or "vi",
        status=doc.status or "pending",
        version=doc.version or 1,
        total_pages_or_slides=doc.total_pages_or_slides or 0,
        total_chunks=doc.total_chunks or 0,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        curriculum_tree=curriculum_nodes,
    )


def _dict_to_curriculum_node(d: dict) -> CurriculumNode:
    """Convert a dict to CurriculumNode, handling nested children recursively."""
    children = []
    for child in d.get("children", []):
        children.append(_dict_to_curriculum_node(child))
    return CurriculumNode(
        id=d.get("id"),
        title=d.get("title", ""),
        section_type="topic",
        section_order=0,
        chapter_number=d.get("level", 1),
        page_from=d.get("page_number"),
        page_to=None,
        scope_label=None,
        summary=d.get("content_preview"),
        metadata=None,
        children=children,
    )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    course_id: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Upload a document for processing. Triggers the RAG pipeline in background."""
    allowed_types = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ]
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

    course_uuid = UUID(course_id) if course_id else None

    service = DocumentService(db, redis)
    try:
        document = await service.upload_document(
            user_id=current_user.id,
            file_content=content,
            filename=file.filename or "document",
            course_id=course_uuid,
        )
    except DocumentServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    process_document_task.delay(str(document.id))

    return DocumentUploadResponse(
        document_id=document.id,
        message="Document uploaded. Processing started in background.",
        s3_key=document.file_storage_url or "",
    )


@router.get("", response_model=list[DocumentListItem])
async def list_documents(
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """List all documents for the current user."""
    service = DocumentService(db, redis)
    documents, _ = await service.list_documents(
        user_id=current_user.id,
        page=page,
        limit=limit,
    )
    return [_doc_to_list_item(d) for d in documents]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get document details including curriculum tree."""
    service = DocumentService(db, redis)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return _doc_to_detail(document)


@router.get("/{document_id}/status", response_model=DocumentStatus)
async def get_document_status(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get document processing status."""
    service = DocumentService(db, redis)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return DocumentStatus(
        id=str(document.id),
        course_id=str(document.course_id) if document.course_id else None,
        status=document.status or "pending",
        parse_error_message=document.parse_error_message,
        total_pages_or_slides=document.total_pages_or_slides or 0,
        total_chunks=document.total_chunks or 0,
        updated_at=document.updated_at,
    )


@router.get("/{document_id}/curriculum-tree")
async def get_curriculum_tree(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get the curriculum tree for scope selection."""
    service = DocumentService(db, redis)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    ready_statuses = {"processed", "structured", "indexed"}
    if document.status not in ready_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document is not ready. Status: {document.status}",
        )

    tree = document.curriculum_tree or []
    nodes = [_dict_to_curriculum_node(n) for n in tree]

    return {
        "document_id": str(document.id),
        "curriculum_tree": nodes,
        "flattened_scope": _flatten_to_scope_payload(document),
    }


def _flatten_to_scope_payload(document: Document) -> list[ScopeUnitPayload]:
    """Convert curriculum tree to frontend's ScopeUnitPayload format."""
    if not document.curriculum_tree:
        return []

    scope_units = []

    def traverse(node: dict, chapter_num: int = 0):
        level = node.get("level", 1)
        title = node.get("title", "")

        if level == 1:
            chapter_num = len(scope_units) + 1

        if level >= 1 and level <= 3:
            scope_units.append(ScopeUnitPayload(
                scope_id=node.get("id"),
                section_id=None,
                scope_type="chapter" if level == 1 else "section" if level == 2 else "subsection",
                title=title,
                chapter_number=chapter_num,
                page_from=node.get("page_number"),
                page_to=None,
                tags=[],
            ))

        for child in node.get("children", []):
            traverse(child, chapter_num)

    for root_node in document.curriculum_tree:
        traverse(root_node)

    return scope_units


@router.patch("/{document_id}/curriculum-tree")
async def update_curriculum_tree(
    document_id: UUID,
    request: DocumentUpdateTreeRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Update the curriculum tree structure."""
    service = DocumentService(db, redis)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Convert CurriculumNode to dict
    tree_dict = [_curriculum_node_to_dict(n) for n in request.curriculum_tree]

    from sqlalchemy import update
    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            curriculum_tree=tree_dict,
            status="structured",
        )
    )
    await db.commit()

    return {"message": "Curriculum tree updated", "document_id": str(document_id)}


def _curriculum_node_to_dict(node: CurriculumNode) -> dict:
    """Convert CurriculumNode to dict for DB storage."""
    return {
        "id": node.id,
        "title": node.title,
        "level": node.chapter_number,
        "page_number": node.page_from,
        "children": [_curriculum_node_to_dict(c) for c in (node.children or [])],
        "content_preview": node.summary or "",
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Delete a document and all its vectors."""
    service = DocumentService(db, redis)
    deleted = await service.delete_document(document_id, current_user.id)

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return {"message": "Document deleted successfully"}
