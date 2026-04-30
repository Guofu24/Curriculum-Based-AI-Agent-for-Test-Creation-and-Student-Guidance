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
from app.core.redis_client import get_redis_client, RedisClient
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
    CurriculumNodeSchema,
    CurriculumTreeUpdateRequest,
    CurriculumTreeResponse,
)
from app.dependencies import get_current_user
from app.models.user import User
from app.models.document import Document
from app.rag.parser import parse_document
from app.rag.structure import detect_heading_tree_llm
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
        course_id=str(doc.course_id) if doc.course_id else None,
        version=getattr(doc, "version", 1) or 1,  # FE compatibility
        chapter_count=doc.total_chapters,
        total_chapters=doc.total_chapters,
        total_pages_or_slides=doc.total_pages_or_slides or 0,
        total_chunks=doc.total_chunks or 0,
        uploaded_at=doc.uploaded_at,
        created_at=doc.uploaded_at,
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
        created_at=doc.uploaded_at,
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
            course_id=UUID(course_id) if course_id else None,
        )
    except DocumentServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Process document in FastAPI background (no Celery worker required).
    # Uses a fresh DB session so the upload transaction is committed first.
    async def _process_in_background(doc_id: str) -> None:
        import uuid as _uuid
        import logging as _logging
        _log = _logging.getLogger("document.background")
        from app.core.database import async_session_maker
        try:
            _log.info("Background processing started for document %s", doc_id)
            async with async_session_maker() as bg_db:
                bg_service = DocumentService(bg_db)
                result = await bg_service.process_document(_uuid.UUID(doc_id))
                _log.info("Background processing result: %s", result)
        except Exception as exc:
            _log.exception("Background processing FAILED for document %s: %s", doc_id, exc)

    background_tasks.add_task(_process_in_background, str(document.id))

    # Notify connected WebSocket clients that processing has started
    try:
        from app.websocket.manager import get_document_upload_manager
        mgr = get_document_upload_manager()
        await mgr.broadcast(str(document.id), {
            "type": "processing_step",
            "document_id": str(document.id),
            "step": "queued",
            "message": "Đang chờ xử lý...",
            "percent": 0,
        })
    except Exception:
        pass

    return DocumentUploadResponse(
        id=document.id,
        message="Document uploaded. Processing started in background.",
        s3_key=document.s3_key,
        processing_status="pending",
        uploaded_at=document.uploaded_at,
        created_at=document.uploaded_at,
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
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get document processing status with Redis-backed throttle (min 1s between DB queries)."""
    import json

    cache_key = f"doc_status:{document_id}"
    cached = await redis.get(cache_key)
    if cached:
        data = json.loads(cached)
        return DocumentStatus(
            id=data["id"],
            processing_status=data["processing_status"],
            parse_error_message=data.get("parse_error_message"),
            total_pages_or_slides=data.get("total_pages_or_slides", 0),
            total_chunks=data.get("total_chunks", 0),
            uploaded_at=data.get("uploaded_at"),
            created_at=data.get("created_at"),
        )

    service = DocumentService(db)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    response = DocumentStatus(
        id=str(document.id),
        processing_status=document.processing_status,
        parse_error_message=document.parse_error_message,
        total_pages_or_slides=document.total_pages_or_slides or 0,
        total_chunks=document.total_chunks or 0,
        uploaded_at=document.uploaded_at,
        created_at=document.uploaded_at,
    )

    await redis.set(
        cache_key,
        json.dumps({
            "id": response.id,
            "processing_status": response.processing_status,
            "parse_error_message": response.parse_error_message,
            "total_pages_or_slides": response.total_pages_or_slides,
            "total_chunks": response.total_chunks,
            "uploaded_at": response.uploaded_at.isoformat() if response.uploaded_at else None,
            "created_at": response.created_at.isoformat() if response.created_at else None,
        }),
        ttl=1,
    )

    return response


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
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Delete a document: removes from DB, S3, Pinecone vectors, and Redis cache."""
    service = DocumentService(db, redis=redis)
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


@router.get(
    "/{document_id}/curriculum-tree",
    response_model=CurriculumTreeResponse,
    summary="Get document curriculum tree",
    description="Returns the flattened curriculum tree (chapters, sections, subsections) "
                "extracted from the document's heading_tree. Returns an empty tree if "
                "the document has not been processed yet.",
    responses={
        200: {"description": "Curriculum tree as flat CurriculumNode list"},
        401: {"description": "Authentication required"},
        404: {"description": "Document not found"},
    },
    tags=["Documents"],
)
async def get_curriculum_tree(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the flattened curriculum tree for a document."""
    service = DocumentService(db)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    tree = service.get_curriculum_tree(document)
    return CurriculumTreeResponse(
        document_id=str(document_id),
        curriculum_tree=tree,
    )


@router.patch(
    "/{document_id}/curriculum-tree",
    response_model=CurriculumTreeResponse,
    summary="Update document curriculum tree",
    description="Updates the persisted curriculum tree for a document. "
                "Useful when the FE wants to override the auto-extracted tree.",
    responses={
        200: {"description": "Curriculum tree updated"},
        401: {"description": "Authentication required"},
        404: {"description": "Document not found"},
    },
    tags=["Documents"],
)
async def update_curriculum_tree(
    document_id: UUID,
    body: CurriculumTreeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the curriculum tree for a document."""
    service = DocumentService(db)
    updated = await service.update_curriculum_tree(document_id, current_user.id, body.curriculum_tree)

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return CurriculumTreeResponse(
        document_id=str(document_id),
        curriculum_tree=body.curriculum_tree,
    )


@router.post(
    "/{document_id}/rescan-structure",
    response_model=DocumentDetail,
    summary="Re-scan document structure",
    description="Re-parses the document and re-detects the heading tree using improved heuristics. "
                "Useful when the document had no detectable structure on first pass.",
    responses={
        200: {"description": "Document structure re-scanned"},
        401: {"description": "Authentication required"},
        404: {"description": "Document not found"},
        409: {"description": "Document is currently being processed"},
    },
    tags=["Documents"],
)
async def rescan_document_structure(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run structure detection on a document that has no heading tree."""
    service = DocumentService(db)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.processing_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is currently being processed. Please wait for it to finish.",
        )

    import logging
    _log = logging.getLogger("document.rescan")

    try:
        from app.utils.storage import get_storage
        file_bytes = await get_storage().download_file(document.s3_key)

        parse_result = await parse_document(file_bytes, document.file_type)
        markdown_content = parse_result["content"]
        heading_tree = await detect_heading_tree_llm(markdown_content)
        total_chapters = len(heading_tree.get("chapters", []))

        # Update heading_tree and total_chapters in DB
        from sqlalchemy import update
        await db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                heading_tree=heading_tree,
                total_chapters=total_chapters,
                processing_status="completed",
            )
        )
        await db.commit()
        _log.info("Rescan complete for %s: %d chapters detected", document_id, total_chapters)

        # Re-fetch updated document
        updated = await service.get_document(document_id, current_user.id)
        return _doc_to_detail(updated)

    except Exception as e:
        _log.exception("Rescan failed for %s: %s", document_id, e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentDetail,
    summary="Re-process document: re-chunk and re-upsert vectors to Pinecone",
)
async def reprocess_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Re-chunk a document and re-upsert all vectors to Pinecone.
    Deletes old vectors first, then re-processes using the current chunker
    (which now correctly uses canonical chapter_id from heading_tree).
    Use this after fixing chunk_id / chapter_id mapping bugs.
    """
    service = DocumentService(db)
    document = await service.get_document(document_id, current_user.id)

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.processing_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is currently being processed.",
        )

    import logging
    _log = logging.getLogger("document.reprocess")

    try:
        # 1. Delete old vectors from Pinecone
        if document.heading_tree:
            chapters = [ch["chapter_id"] for ch in document.heading_tree.get("chapters", [])]
        else:
            chapters = []
        try:
            from app.rag.vector_store import VectorStore
            vs = VectorStore()
            await vs.delete_document_vectors(str(document_id), chapters)
            _log.info("Deleted %d old namespaces for document %s", len(chapters), document_id)
        except Exception as e:
            _log.warning("Failed to delete old vectors (may not exist yet): %s", e)

        # 2. Download file from S3
        from app.utils.storage import get_storage
        file_bytes = await get_storage().download_file(document.s3_key)

        # 3. Re-parse
        parse_result = await parse_document(file_bytes, document.file_type)
        markdown_content = parse_result["content"]

        # 4. Re-detect heading tree from markdown (uses latest patterns including Roman numerals)
        from app.rag.structure import detect_heading_tree_llm as _detect_llm
        heading_tree = await _detect_llm(markdown_content)
        _log.info("Re-detected heading tree: %d chapters", len(heading_tree.get("chapters", [])))

        # 5. Re-chunk using the new heading tree
        from app.rag.chunker import semantic_chunk
        chunks = semantic_chunk(
            markdown=markdown_content,
            heading_tree=heading_tree,
        )
        _log.info("Re-chunked into %d chunks", len(chunks))

        # 6. Embed chunks (required before upserting to Pinecone)
        if chunks:
            from app.core.redis_client import get_redis_client
            from app.rag.embedder import embed_chunks
            redis = get_redis_client()
            chunks = await embed_chunks(chunks, str(document_id), redis)
            _log.info("Embedded %d chunks", len(chunks))

        # 7. Update heading_tree and total_chunks in DB
        from sqlalchemy import update as _sql_update
        await db.execute(
            _sql_update(Document)
            .where(Document.id == document_id)
            .values(heading_tree=heading_tree, total_chunks=len(chunks))
        )
        await db.commit()

        # 8. Re-upsert to Pinecone (after DB commit so heading_tree is persisted)
        vs = VectorStore()

        # Group chunks by chapter_id
        chapter_chunks: dict[str, list[dict]] = {}
        for chunk in chunks:
            ch_id = chunk.get("chapter_id", "ch_unknown")
            chapter_chunks.setdefault(ch_id, []).append(chunk)

        for chapter in heading_tree.get("chapters", []):
            ch_id = chapter.get("chapter_id", "")
            chunks_for_ch = chapter_chunks.get(ch_id, [])
            if chunks_for_ch:
                await vs.upsert_chunks(str(document_id), ch_id, chunks_for_ch)
                _log.info("Upserted %d chunks (chapter=%s) to document namespace", len(chunks_for_ch), ch_id)
            else:
                _log.info("No chunks for chapter %s (%s)", chapter.get("title", ""), ch_id)

        updated = await service.get_document(document_id, current_user.id)
        _log.info("Re-process complete for %s: %d chunks", document_id, len(chunks))
        return _doc_to_detail(updated)

    except Exception as e:
        _log.exception("Re-process failed for %s: %s", document_id, e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

