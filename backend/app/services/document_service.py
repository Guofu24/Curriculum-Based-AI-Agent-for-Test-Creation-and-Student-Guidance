"""Document service: handles document upload, processing, and management."""

import uuid
import hashlib
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.core.redis_client import RedisClient
from app.utils.s3 import (
    upload_file,
    delete_file,
    generate_fresh_url,
    S3Error,
)
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
    ) -> Document:
        """Upload a document to S3 and create DB record."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ["pdf", "docx", "pptx"]:
            raise DocumentServiceError(f"Unsupported file type: {ext}")

        file_hash = self._compute_file_hash(file_content)
        title = filename.rsplit(".", 1)[0] if "." in filename else filename

        try:
            s3_key = await upload_file(
                file_bytes=file_content,
                filename=filename,
                user_id=str(user_id),
                file_type=ext,
            )
        except S3Error as e:
            raise DocumentServiceError(f"Failed to upload file: {str(e)}")

        document = Document(
            user_id=user_id,
            original_filename=filename,
            file_type=ext,
            s3_key=s3_key,
            processing_status="pending",
        )
        # Store title in metadata via a default approach
        # (In a real scenario you'd add a title field to the model or use a separate metadata table)
        del title  # unused

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

        # Delete from S3
        try:
            await delete_file(document.s3_key)
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
        """
        Run the full RAG pipeline for a document. Called by Celery task.

        Steps per spec:
        1. Download from S3
        2. Parse (rag/parser.py) → markdown
        3. Structure detection (rag/structure.py) → heading_tree
        4. Chunking (rag/chunker.py) → chunks with metadata
        5. Embed + upsert Pinecone per chapter (G16 embedding cache)
        6. Update DB: processing_status = 'completed'
        """
        try:
            await self.update_status(document_id, "processing")

            result = await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            if not document:
                raise DocumentServiceError("Document not found")

            from app.utils.s3 import download_file
            file_bytes = await download_file(document.s3_key)

            # Step 1: Parse
            parse_result = await parse_document(file_bytes, document.file_type)
            markdown_content = parse_result["content"]
            total_pages = parse_result.get("page_count", 0)

            # Step 2: Structure detection
            heading_tree = detect_heading_tree(markdown_content)
            total_chapters = len(heading_tree.get("chapters", []))

            # Step 3: Chunking
            chunks = semantic_chunk(markdown_content, heading_tree)

            # Assign document_id to each chunk
            doc_id_str = str(document_id)
            for chunk in chunks:
                chunk["document_id"] = doc_id_str

            # Step 4: Embed + upsert per chapter (G16 — uses embedding cache)
            from app.core.redis_client import get_redis_client
            redis = get_redis_client()

            enriched = await embed_chunks(chunks, doc_id_str, redis)

            # Group by chapter and upsert per namespace
            chapter_groups: dict[str, list[dict]] = {}
            for chunk in enriched:
                ch_id = chunk.get("chapter_id", "unknown")
                if ch_id not in chapter_groups:
                    chapter_groups[ch_id] = []
                chapter_groups[ch_id].append(chunk)

            for chapter_id, chapter_chunks in chapter_groups.items():
                await self.vector_store.upsert_chunks(
                    document_id=doc_id_str,
                    chapter_id=chapter_id,
                    chunks=chapter_chunks,
                )

            # Step 5: Update DB
            await self.update_processing_result(
                document_id=document_id,
                heading_tree=heading_tree,
                total_chapters=total_chapters,
                total_pages_or_slides=total_pages,
                total_chunks=len(enriched),
            )

            return {
                "document_id": doc_id_str,
                "chunks_created": len(enriched),
                "total_pages": total_pages,
                "total_chapters": total_chapters,
                "processing_status": "completed",
            }

        except Exception as e:
            await self.update_status(document_id, "failed", error_message=str(e))
            return {
                "document_id": str(document_id),
                "processing_status": "failed",
                "error": str(e),
            }

    def get_presigned_url(self, document: Document) -> str:
        """Get a presigned URL for downloading the document (G20)."""
        return generate_fresh_url(document.s3_key)

    def get_flattened_scope(self, document: Document) -> list[dict]:
        """Get flattened scope list from heading tree."""
        if not document.heading_tree:
            return []
        return flatten_heading_tree(document.heading_tree)
