"""Document service: handles document upload, processing, and management."""

import uuid
import hashlib
from uuid import UUID
from typing import Callable

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.core.redis_client import RedisClient
from app.utils.storage import get_storage, StorageError
from app.rag.parser import parse_document
from app.rag.structure import detect_heading_tree_llm, flatten_heading_tree
from app.rag.chunker import semantic_chunk
from app.rag.embedder import embed_chunks
from app.rag.vector_store import get_vector_store
from app.rag.cleaner import clean_markdown


class DocumentServiceError(Exception):
    """Raised when document operation fails."""
    pass


class DocumentService:
    """Service for document management and RAG pipeline."""

    def __init__(self, db: AsyncSession, redis: RedisClient | None = None):
        self.db = db
        self.redis = redis
        self.vector_store = get_vector_store()

    def _compute_file_hash(self, content: bytes) -> str:
        """Compute SHA256 hash for deduplication."""
        return hashlib.sha256(content).hexdigest()

    async def upload_document(
        self,
        user_id: UUID,
        file_content: bytes,
        filename: str,
        course_id: UUID | None = None,
    ) -> Document:
        """Upload a document to S3 and create DB record."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ["pdf", "docx", "pptx"]:
            raise DocumentServiceError(f"Unsupported file type: {ext}")

        file_hash = self._compute_file_hash(file_content)
        del file_hash  # unused for now

        try:
            storage = get_storage()
            s3_key = await storage.upload_file(
                file_bytes=file_content,
                filename=filename,
                user_id=str(user_id),
                file_type=ext,
            )
        except StorageError as e:
            raise DocumentServiceError(f"Failed to upload file: {str(e)}")

        document = Document(
            user_id=user_id,
            course_id=course_id,
            original_filename=filename,
            file_type=ext,
            s3_key=s3_key,
            processing_status="pending",
            file_size=len(file_content),
        )

        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)

        return document

    async def get_document(self, document_id: UUID, user_id: UUID) -> Document | None:
        """Get a document by ID, ensuring user owns it."""
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
        course_id: str | None = None,
    ) -> tuple[list[Document], int]:
        """List documents for a user with pagination. Optionally filter by course_id."""
        offset = (page - 1) * limit

        stmt = select(Document).where(Document.user_id == user_id)
        count_stmt = select(func.count(Document.id)).where(Document.user_id == user_id)

        if course_id:
            stmt = stmt.where(Document.course_id == UUID(course_id))
            count_stmt = count_stmt.where(Document.course_id == UUID(course_id))

        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        result = await self.db.execute(
            stmt.order_by(Document.uploaded_at.desc())
            .offset(offset)
            .limit(limit)
        )
        documents = list(result.scalars().all())

        return documents, total

    async def update_status(
        self,
        document_id: UUID,
        processing_status: str,
        error_message: str | None = None,
    ) -> None:
        """Update document processing status."""
        values: dict = {"processing_status": processing_status}
        if error_message is not None:
            values["parse_error_message"] = error_message

        await self.db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(**values)
        )
        await self.db.commit()

    async def update_processing_result(
        self,
        document_id: UUID,
        heading_tree: dict,
        total_chapters: int,
        total_pages_or_slides: int,
        total_chunks: int,
    ) -> None:
        """Update document with processing result after RAG pipeline."""
        await self.db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                heading_tree=heading_tree,
                total_chapters=total_chapters,
                total_pages_or_slides=total_pages_or_slides,
                total_chunks=total_chunks,
                processing_status="processing",
            )
        )
        await self.db.commit()

    async def delete_document(self, document_id: UUID, user_id: UUID) -> bool:
        """Delete a document and its vectors (DB + S3 + Pinecone)."""
        import logging
        _log = logging.getLogger("document.delete")

        document = await self.get_document(document_id, user_id)
        if not document:
            return False

        doc_id_str = str(document_id)

        # Delete from storage backend (MinIO or S3)
        try:
            await get_storage().delete_file(document.s3_key)
        except Exception as e:
            _log.warning("S3 delete failed for %s: %s", doc_id_str, e)

        # Delete from Pinecone — delete ALL namespaces for this doc (safer than per-chapter)
        # Also handles ch_unknown and any extra namespaces that aren't in heading_tree
        try:
            success = await self.vector_store.delete_all_document_vectors(doc_id_str)
            if success:
                _log.info("Deleted all Pinecone vectors for doc %s", doc_id_str)
            else:
                # Fallback: try per-chapter delete from heading_tree
                if document.heading_tree:
                    chapters = [ch["chapter_id"] for ch in document.heading_tree.get("chapters", [])]
                else:
                    chapters = []
                await self.vector_store.delete_document_vectors(doc_id_str, chapters)
                _log.warning("delete_all_document_vectors returned False — used per-chapter delete for %s", doc_id_str)
        except Exception as e:
            _log.error("Pinecone delete failed for %s: %s — document DB record will still be deleted", doc_id_str, e)

        # Delete Redis embedding cache for this document (embed:{doc_id}:* keys)
        try:
            if self.redis:
                pattern = f"embed:{doc_id_str}:*"
                deleted_count = 0
                async for key in self.redis.client.scan_iter(pattern):
                    await self.redis.client.delete(key)
                    deleted_count += 1
                # Also clear doc_status cache
                await self.redis.client.delete(f"doc_status:{doc_id_str}")
                _log.info("Deleted %d Redis cache keys for doc %s", deleted_count, doc_id_str)
        except Exception as e:
            _log.warning("Redis cache cleanup failed for %s: %s", doc_id_str, e)

        # Delete from DB
        await self.db.delete(document)
        await self.db.commit()
        _log.info("Deleted document record %s from database", doc_id_str)

        return True

    @staticmethod
    def _make_parse_progress_emit(
        doc_id: str,
        mgr,
    ) -> Callable[[str, str, int], None] | None:
        """
        Build a progress callback that emits WebSocket events during document parsing.
        Each completed Gemini chunk → one processing_step event.
        Uses ensure_future so it doesn't block the async parse loop.
        """
        def emit(step: str, message: str, percent: int) -> None:
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.call_soon(
                    lambda: asyncio.ensure_future(
                        mgr.broadcast(doc_id, {
                            "type": "processing_step",
                            "document_id": doc_id,
                            "step": step,
                            "message": message,
                            "percent": percent,
                        })
                    )
                )
            except Exception:
                pass
        return emit

    async def process_document(self, document_id: UUID) -> dict:
        """Run the full RAG pipeline: parse -> chunk -> (embed+Pinecone optional)."""
        import logging
        _log = logging.getLogger("document.process")
        try:
            await self.update_status(document_id, "processing")
            doc_id_str = str(document_id)

            # Emit: processing started
            try:
                from app.websocket.manager import get_document_upload_manager
                mgr = get_document_upload_manager()
                await mgr.broadcast(doc_id_str, {
                    "type": "processing_step",
                    "document_id": doc_id_str,
                    "step": "download",
                    "message": "Đang tải tài liệu...",
                    "percent": 0,
                })
            except Exception:
                pass

            result = await self.db.execute(select(Document).where(Document.id == document_id))
            document = result.scalar_one_or_none()
            if not document:
                raise DocumentServiceError("Document not found")

            from app.utils.storage import get_storage
            file_bytes = await get_storage().download_file(document.s3_key)

            try:
                mgr = get_document_upload_manager()
                await mgr.broadcast(doc_id_str, {
                    "type": "processing_step",
                    "document_id": doc_id_str,
                    "step": "parse",
                    "message": "Đang phân tích nội dung tài liệu...",
                    "percent": 20,
                })
            except Exception:
                pass

            parse_result = await parse_document(
                file_bytes,
                document.file_type,
                progress_callback=self._make_parse_progress_emit(doc_id_str, mgr),
            )
            markdown_content = parse_result["content"]
            total_pages = parse_result.get("page_count", 0)
            _log.info("Parsed %s: %d pages, %d chars", document_id, total_pages, len(markdown_content))

            try:
                mgr = get_document_upload_manager()
                await mgr.broadcast(doc_id_str, {
                    "type": "processing_step",
                    "document_id": doc_id_str,
                    "step": "clean",
                    "message": "Đang làm sạch và chuẩn hóa nội dung...",
                    "percent": 50,
                })
            except Exception:
                pass

            # Step 2: Clean markdown (normalize headings, remove noise)
            cleaned_result = clean_markdown(markdown_content)
            markdown_content = cleaned_result.cleaned
            _log.info(
                "Cleaned %s: removed_noise=%d, promoted_parts=%d, fixed_levels=%d, "
                "removed_duplicates=%d",
                document_id,
                cleaned_result.stats["removed_noise"],
                cleaned_result.stats["promoted_parts"],
                cleaned_result.stats["fixed_levels"],
                cleaned_result.stats["removed_duplicates"],
            )

            try:
                mgr = get_document_upload_manager()
                await mgr.broadcast(doc_id_str, {
                    "type": "processing_step",
                    "document_id": doc_id_str,
                    "step": "structure",
                    "message": "Đang phát hiện cấu trúc chương...",
                    "percent": 65,
                })
            except Exception:
                pass

            heading_tree = await detect_heading_tree_llm(markdown_content)
            total_chapters = len(heading_tree.get("chapters", []))

            try:
                mgr = get_document_upload_manager()
                await mgr.broadcast(doc_id_str, {
                    "type": "processing_step",
                    "document_id": doc_id_str,
                    "step": "chunk",
                    "message": f"Đang chia nhỏ nội dung ({total_chapters} chương)...",
                    "percent": 75,
                })
            except Exception:
                pass

            chunks = semantic_chunk(markdown_content, heading_tree)
            for chunk in chunks:
                chunk["document_id"] = doc_id_str
            _log.info("Chunked %s: %d chunks, %d chapters", document_id, len(chunks), total_chapters)

            # Save parse results immediately — visible even if embed step fails
            await self.update_processing_result(
                document_id=document_id,
                heading_tree=heading_tree,
                total_chapters=total_chapters,
                total_pages_or_slides=total_pages,
                total_chunks=len(chunks),
            )

            # Embed + Pinecone — graceful degradation if OpenAI key invalid
            try:
                from app.core.redis_client import get_redis_client
                redis = get_redis_client()
                try:
                    mgr = get_document_upload_manager()
                    await mgr.broadcast(doc_id_str, {
                        "type": "processing_step",
                        "document_id": doc_id_str,
                        "step": "embed",
                        "message": "Đang tạo vector embeddings...",
                        "percent": 88,
                    })
                except Exception:
                    pass

                # Progress callback: map embed batch progress to 88-99% range
                async def _embed_progress(completed: int, total: int) -> None:
                    try:
                        # Map [0, total] → [88, 99]
                        pct = 88 + int((completed / max(total, 1)) * 11)
                        pct = min(pct, 99)
                        await mgr.broadcast(doc_id_str, {
                            "type": "processing_step",
                            "document_id": doc_id_str,
                            "step": "embed",
                            "message": f"Đang tạo vector embeddings ({completed}/{total})...",
                            "percent": pct,
                        })
                    except Exception:
                        pass

                enriched = await embed_chunks(chunks, doc_id_str, redis, progress_callback=_embed_progress)
                chapter_groups: dict[str, list[dict]] = {}
                for chunk in enriched:
                    chapter_groups.setdefault(chunk.get("chapter_id", "unknown"), []).append(chunk)
                for chapter_id, chapter_chunks in chapter_groups.items():
                    await self.vector_store.upsert_chunks(
                        document_id=doc_id_str, chapter_id=chapter_id, chunks=chapter_chunks,
                    )
                await self.update_status(document_id, "indexed")
                _log.info("Indexed %s: %d vectors", document_id, len(enriched))

                try:
                    mgr = get_document_upload_manager()
                    await mgr.broadcast(doc_id_str, {
                        "type": "processing_step",
                        "document_id": doc_id_str,
                        "step": "done",
                        "message": "Xử lý hoàn tất!",
                        "percent": 100,
                    })
                except Exception:
                    pass

                return {"document_id": doc_id_str, "chunks_created": len(enriched),
                        "total_pages": total_pages, "processing_status": "indexed"}
            except Exception as embed_err:
                _log.warning("Embed failed for %s: %s", document_id, embed_err)
                await self.update_status(document_id, "processed", error_message=str(embed_err))

                try:
                    mgr = get_document_upload_manager()
                    await mgr.broadcast(doc_id_str, {
                        "type": "processing_step",
                        "document_id": doc_id_str,
                        "step": "done_no_embed",
                        "message": "Xử lý xong (không indexing được vector — vẫn dùng được)",
                        "percent": 100,
                    })
                except Exception:
                    pass

                return {"document_id": doc_id_str, "chunks_created": len(chunks),
                        "total_pages": total_pages, "processing_status": "processed",
                        "embed_error": str(embed_err)}

        except Exception as e:
            _log.exception("process_document failed %s: %s", document_id, e)
            await self.update_status(document_id, "failed", error_message=str(e))
            try:
                from app.websocket.manager import get_document_upload_manager
                doc_id_str = str(document_id)
                mgr = get_document_upload_manager()
                await mgr.broadcast(doc_id_str, {
                    "type": "processing_failed",
                    "document_id": doc_id_str,
                    "error": str(e),
                })
            except Exception:
                pass
            return {"document_id": str(document_id), "processing_status": "failed", "error": str(e)}

    def get_presigned_url(self, document: Document) -> str:
        """Get a presigned URL for downloading the document (G20)."""
        return get_storage().generate_presigned_url(document.s3_key)

    def get_flattened_scope(self, document: Document) -> list[dict]:
        """Get flattened scope list from heading tree."""
        if not document.heading_tree:
            return []
        return flatten_heading_tree(document.heading_tree)

    def get_curriculum_tree(self, document: Document) -> list[dict]:
        """
        Convert heading_tree (nested chapters/sections/subsections) into
        the flat CurriculumNode[] format the FE expects.
        """
        if not document.heading_tree:
            return []
        chapters = document.heading_tree.get("chapters", [])
        nodes: list[dict] = []
        for ch_idx, chapter in enumerate(chapters):
            ch_id = chapter.get("chapter_id")
            nodes.append({
                "id": ch_id,
                "title": chapter.get("title", ""),
                "level": 1,
                "parent_id": None,
                "chapter_id": ch_id,
                "section_type": "chapter",
                "section_order": ch_idx,
                "chapter_number": ch_idx + 1,
                "page_from": None,
                "page_to": None,
                "scope_label": None,
                "summary": None,
                "metadata": None,
                "children": [],
            })
            for sec in chapter.get("sections", []):
                sec_id = sec.get("section_id")
                nodes.append({
                    "id": sec_id,
                    "title": sec.get("title", ""),
                    "level": 2,
                    "parent_id": ch_id,
                    "chapter_id": ch_id,
                    "section_type": "section",
                    "section_order": len(nodes),
                    "chapter_number": ch_idx + 1,
                    "page_from": None,
                    "page_to": None,
                    "scope_label": None,
                    "summary": None,
                    "metadata": None,
                    "children": [],
                })
                for sub in sec.get("subsections", []):
                    sub_id = sub.get("section_id")
                    nodes.append({
                        "id": sub_id,
                        "title": sub.get("title", ""),
                        "level": 3,
                        "parent_id": sec_id,
                        "chapter_id": ch_id,
                        "section_type": "subsection",
                        "section_order": len(nodes),
                        "chapter_number": ch_idx + 1,
                        "page_from": None,
                        "page_to": None,
                        "scope_label": None,
                        "summary": None,
                        "metadata": None,
                        "children": [],
                    })
        return nodes

    async def update_curriculum_tree(
        self,
        document_id: UUID,
        user_id: UUID,
        curriculum_tree: list[dict],
    ) -> bool:
        """
        Persist a curriculum tree (from FE editing) back to the document.
        Also re-builds heading_tree from the flat nodes for downstream use.
        """
        document = await self.get_document(document_id, user_id)
        if not document:
            return False

        heading_tree = self._build_heading_tree_from_flat(curriculum_tree)

        await self.db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(heading_tree=heading_tree)
        )
        await self.db.commit()
        return True

    def _build_heading_tree_from_flat(self, flat_tree: list[dict]) -> dict:
        """Rebuild nested heading_tree from flat CurriculumNode[] list."""
        chapters: list[dict] = []
        current_chapter: dict | None = None
        current_section: dict | None = None

        def _get_stype(node: dict) -> str:
            """Get section_type, falling back to level if not present."""
            stype = node.get("section_type")
            if stype:
                return stype
            level = node.get("level")
            if level == 1:
                return "chapter"
            elif level == 2:
                return "section"
            elif level == 3:
                return "subsection"
            return "chapter"

        for node in flat_tree:
            stype = _get_stype(node)
            if stype == "chapter":
                current_chapter = {
                    "chapter_id": node.get("id", ""),
                    "title": node.get("title", ""),
                    "sections": [],
                }
                chapters.append(current_chapter)
                current_section = None

            elif stype == "section":
                if current_chapter is None:
                    current_chapter = {"chapter_id": "ch_auto", "title": "", "sections": []}
                    chapters.append(current_chapter)
                current_section = {
                    "section_id": node.get("id", ""),
                    "title": node.get("title", ""),
                    "subsections": [],
                }
                current_chapter["sections"].append(current_section)

            elif stype == "subsection":
                if current_section is None:
                    if current_chapter is None:
                        current_chapter = {"chapter_id": "ch_auto", "title": "", "sections": []}
                        chapters.append(current_chapter)
                    current_section = {"section_id": "", "title": "", "subsections": []}
                    current_chapter["sections"].append(current_section)
                current_section["subsections"].append({
                    "section_id": node.get("id", ""),
                    "title": node.get("title", ""),
                })

        return {"chapters": chapters}

