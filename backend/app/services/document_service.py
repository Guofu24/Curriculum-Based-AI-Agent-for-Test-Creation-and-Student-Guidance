"""Document service: handles document upload, processing, and management."""

import uuid
import hashlib
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.core.redis_client import RedisClient
from app.utils.storage import get_storage, StorageError
from app.rag.parser import parse_document
from app.rag.structure import detect_heading_tree, flatten_heading_tree
from app.rag.chunker import semantic_chunk
from app.rag.embedder import embed_chunks
from app.rag.vector_store import get_vector_store


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
                processing_status="completed",
            )
        )
        await self.db.commit()

    async def delete_document(self, document_id: UUID, user_id: UUID) -> bool:
        """Delete a document and its vectors."""
        document = await self.get_document(document_id, user_id)
        if not document:
            return False

        # Delete from storage backend (MinIO or S3)
        try:
            await get_storage().delete_file(document.s3_key)
        except Exception:
            pass

        # Delete from Pinecone — all chapters
        if document.heading_tree:
            chapters = [ch["chapter_id"] for ch in document.heading_tree.get("chapters", [])]
        else:
            chapters = []
        try:
            await self.vector_store.delete_document_vectors(str(document_id), chapters)
        except Exception:
            pass

        # Delete from DB
        await self.db.delete(document)
        await self.db.commit()

        return True

    async def process_document(self, document_id: UUID) -> dict:
        """Run the full RAG pipeline: parse -> chunk -> (embed+Pinecone optional)."""
        import logging
        _log = logging.getLogger("document.process")
        try:
            await self.update_status(document_id, "processing")
            result = await self.db.execute(select(Document).where(Document.id == document_id))
            document = result.scalar_one_or_none()
            if not document:
                raise DocumentServiceError("Document not found")

            from app.utils.storage import get_storage
            file_bytes = await get_storage().download_file(document.s3_key)

            parse_result = await parse_document(file_bytes, document.file_type)
            markdown_content = parse_result["content"]
            total_pages = parse_result.get("page_count", 0)
            _log.info("Parsed %s: %d pages, %d chars", document_id, total_pages, len(markdown_content))

            heading_tree = detect_heading_tree(markdown_content)
            total_chapters = len(heading_tree.get("chapters", []))
            chunks = semantic_chunk(markdown_content, heading_tree)
            doc_id_str = str(document_id)
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
                enriched = await embed_chunks(chunks, doc_id_str, redis)
                chapter_groups: dict[str, list[dict]] = {}
                for chunk in enriched:
                    chapter_groups.setdefault(chunk.get("chapter_id", "unknown"), []).append(chunk)
                for chapter_id, chapter_chunks in chapter_groups.items():
                    await self.vector_store.upsert_chunks(
                        document_id=doc_id_str, chapter_id=chapter_id, chunks=chapter_chunks,
                    )
                await self.update_status(document_id, "indexed")
                _log.info("Indexed %s: %d vectors", document_id, len(enriched))
                return {"document_id": doc_id_str, "chunks_created": len(enriched),
                        "total_pages": total_pages, "processing_status": "indexed"}
            except Exception as embed_err:
                _log.warning("Embed skipped for %s (parse OK): %s", document_id, embed_err)
                return {"document_id": doc_id_str, "chunks_created": len(chunks),
                        "total_pages": total_pages, "processing_status": "processed",
                        "embed_error": str(embed_err)}

        except Exception as e:
            _log.exception("process_document failed %s: %s", document_id, e)
            await self.update_status(document_id, "failed", error_message=str(e))
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

