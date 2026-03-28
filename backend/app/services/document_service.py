"""Document service: handles document upload, processing, and management."""

import uuid
import hashlib
from typing import Any
from uuid import UUID
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.core.redis_client import RedisClient
from app.utils.s3 import (
    upload_file_to_s3,
    delete_file_from_s3,
    generate_presigned_url,
    generate_upload_presigned_url,
    get_file_content_type,
)
from app.rag.parser import parse_document
from app.rag.structure import detect_heading_tree, flatten_heading_tree
from app.rag.chunker import semantic_chunk, Chunk
from app.rag.embedder import EmbeddingService
from app.rag.vector_store import get_vector_store
from app.utils.s3 import S3Error


class DocumentServiceError(Exception):
    """Raised when document operation fails."""
    pass


class DocumentService:
    """Service for document management and RAG pipeline."""

    def __init__(self, db: AsyncSession, redis: RedisClient | None = None):
        self.db = db
        self.embedder = EmbeddingService(redis)
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

        content_type = get_file_content_type(filename)
        file_hash = self._compute_file_hash(file_content)
        title = filename.rsplit(".", 1)[0] if "." in filename else filename

        try:
            s3_key = await upload_file_to_s3(
                file_content=file_content,
                original_filename=filename,
                user_id=str(user_id),
                content_type=content_type,
            )
        except S3Error as e:
            raise DocumentServiceError(f"Failed to upload file: {str(e)}")

        document = Document(
            user_id=user_id,
            course_id=course_id,
            title=title,
            file_name=filename,
            file_type=ext,
            file_size=len(file_content),
            file_hash=file_hash,
            file_storage_url=s3_key,
            status="pending",
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
        course_id: UUID | None = None,
    ) -> tuple[list[Document], int]:
        """List documents for a user with pagination."""
        offset = (page - 1) * limit

        base_query = select(Document).where(Document.user_id == user_id)
        if course_id:
            base_query = base_query.where(Document.course_id == course_id)

        # Get total count
        count_result = await self.db.execute(
            select(func.count(Document.id)).where(Document.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            base_query
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        documents = list(result.scalars().all())

        return documents, total

    async def update_status(
        self,
        document_id: UUID,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update document processing status."""
        await self.db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                status=status,
                parse_error_message=error_message,
            )
        )
        await self.db.commit()

    async def update_curriculum_tree(
        self,
        document_id: UUID,
        curriculum_tree: list[dict],
        total_chunks: int,
        total_pages: int = 0,
    ) -> None:
        """Update document curriculum tree after RAG processing."""
        chapter_count = len([n for n in curriculum_tree if n.get("level", 1) == 1])
        await self.db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                curriculum_tree=curriculum_tree,
                total_chunks=total_chunks,
                total_pages_or_slides=total_pages,
                status="processed",
            )
        )
        await self.db.commit()

    async def mark_indexed(self, document_id: UUID) -> None:
        """Mark document as fully indexed."""
        await self.db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status="indexed")
        )
        await self.db.commit()

    async def delete_document(self, document_id: UUID, user_id: UUID) -> bool:
        """Delete a document and its vectors."""
        document = await self.get_document(document_id, user_id)
        if not document:
            return False

        # Delete from S3
        try:
            await delete_file_from_s3(document.file_storage_url)
        except Exception:
            pass

        # Delete from Pinecone
        try:
            await self.vector_store.delete_document_vectors(str(document_id))
        except Exception:
            pass

        # Delete from DB
        await self.db.delete(document)
        await self.db.commit()

        return True

    async def process_document(self, document_id: UUID) -> dict:
        """Run the full RAG pipeline for a document. Called by Celery task."""
        try:
            await self.update_status(document_id, "processing")

            result = await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            if not document:
                raise DocumentServiceError("Document not found")

            from app.utils.s3 import download_file_from_s3
            file_bytes = await download_file_from_s3(document.file_storage_url)

            # Parse
            parse_result = await parse_document(file_bytes, document.file_type)
            markdown_content = parse_result["content"]
            total_pages = parse_result.get("page_count", 0)

            # Heading tree
            heading_tree = detect_heading_tree(markdown_content)
            flattened = flatten_heading_tree(heading_tree)

            # Chunking
            chunks = semantic_chunk(markdown_content, heading_tree)

            # Embeddings
            chunk_texts = [c.content for c in chunks]
            embeddings = await self.embedder.embed_texts(chunk_texts)

            # Upsert to Pinecone
            await self.vector_store.upsert_chunks(
                document_id=str(document_id),
                chunks=chunks,
                embeddings=embeddings,
            )

            # Update DB
            await self.update_curriculum_tree(
                document_id=document_id,
                curriculum_tree=heading_tree,
                total_chunks=len(chunks),
                total_pages=total_pages,
            )

            return {
                "document_id": str(document_id),
                "chunks_created": len(chunks),
                "total_pages": total_pages,
                "status": "processed",
            }

        except Exception as e:
            await self.update_status(document_id, "failed", error_message=str(e))
            return {
                "document_id": str(document_id),
                "status": "failed",
                "error": str(e),
            }

    def get_presigned_url(self, document: Document) -> str:
        """Get a presigned URL for downloading the document."""
        return generate_presigned_url(document.file_storage_url)

    def get_flattened_scope(self, document: Document) -> list[dict]:
        """Get flattened scope list from curriculum tree."""
        if not document.curriculum_tree:
            return []
        return flatten_heading_tree(document.curriculum_tree)
