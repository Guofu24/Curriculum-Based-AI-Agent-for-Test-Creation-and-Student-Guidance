"""
Textbook Service

Handles textbook CRUD operations, file upload, and triggers document processing.
"""
import os
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from models.textbook import Textbook, TextbookChapter, TextbookChunk, ProcessingStatus
from agents.document_processor import DocumentProcessorAgent
from services.rag_service import RAGService


class TextbookService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upload_textbook(
        self,
        user_id: str,
        title: str,
        file_name: str,
        file_content: bytes,
        file_type: str,
    ) -> Textbook:
        """Upload and process a textbook file."""
        # 1. Save file to disk
        textbook_id = str(uuid.uuid4())
        upload_dir = Path(settings.UPLOAD_DIR).resolve() / user_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        # Use only UUID + extension for the on-disk name to stay within
        # Windows MAX_PATH (260 chars). The original name is kept in the DB.
        ext = Path(file_name).suffix  # e.g. ".pdf"
        file_path = upload_dir / f"{textbook_id}{ext}"
        file_path.write_bytes(file_content)

        # 2. Create DB record
        textbook = Textbook(
            id=textbook_id,
            owner_id=user_id,
            title=title,
            file_name=file_name,
            file_path=str(file_path),
            file_type=file_type,
            file_size=len(file_content),
            status=ProcessingStatus.PROCESSING,
        )
        self.db.add(textbook)
        await self.db.flush()

        # 3. Process document (parse, chunk, embed)
        try:
            rag = RAGService.get_instance()
            vector_store = rag.get_vector_store(namespace=textbook_id)
            processor = DocumentProcessorAgent(
                vector_store=vector_store, db_session=self.db
            )

            result = await processor.process_document(
                file_path=str(file_path),
                textbook_id=textbook_id,
            )

            # 4. Save chapters
            for ch in result.get("chapters", []):
                chapter = TextbookChapter(
                    textbook_id=textbook_id,
                    chapter_number=ch["chapter_number"],
                    title=ch.get("title", f"Chapter {ch['chapter_number']}"),
                    start_page=ch.get("start_page"),
                    end_page=ch.get("end_page"),
                )
                self.db.add(chapter)

            # 5. Update textbook status
            textbook.status = ProcessingStatus.PROCESSED
            textbook.total_chunks = result.get("total_chunks", 0)

        except Exception as e:
            textbook.status = ProcessingStatus.FAILED
            raise e

        # Commit and re-fetch with chapters eagerly loaded to avoid lazy-load
        # outside async context when FastAPI serializes the response
        await self.db.commit()
        refreshed = await self.db.execute(
            select(Textbook)
            .where(Textbook.id == textbook_id)
            .options(selectinload(Textbook.chapters))
        )
        return refreshed.scalar_one()

    async def get_textbooks(self, user_id: str) -> list[Textbook]:
        """Get all textbooks for a user."""
        result = await self.db.execute(
            select(Textbook)
            .where(Textbook.owner_id == user_id)
            .options(selectinload(Textbook.chapters))
            .order_by(Textbook.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_textbook(self, textbook_id: str, user_id: str) -> Textbook | None:
        """Get a specific textbook with chapters."""
        result = await self.db.execute(
            select(Textbook)
            .where(Textbook.id == textbook_id, Textbook.owner_id == user_id)
            .options(selectinload(Textbook.chapters))
        )
        return result.scalar_one_or_none()

    async def delete_textbook(self, textbook_id: str, user_id: str) -> bool:
        """Delete a textbook and its vector data."""
        textbook = await self.get_textbook(textbook_id, user_id)
        if not textbook:
            return False

        # Delete vector chunks from Pinecone
        rag = RAGService.get_instance()
        rag.delete_textbook_chunks(textbook_id)

        # Delete chunk text rows from PostgreSQL
        chunk_result = await self.db.execute(
            select(TextbookChunk).where(TextbookChunk.textbook_id == textbook_id)
        )
        for chunk in chunk_result.scalars().all():
            await self.db.delete(chunk)

        # Delete file
        file_path = Path(textbook.file_path)
        if file_path.exists():
            file_path.unlink()

        # Delete DB record (cascades to chapters)
        await self.db.delete(textbook)
        await self.db.commit()
        return True

    async def get_textbook_metadata(self, textbook_id: str, user_id: str) -> dict:
        """Get textbook metadata for agent state."""
        textbook = await self.get_textbook(textbook_id, user_id)
        if not textbook:
            return {}

        return {
            "title": textbook.title,
            "total_chunks": textbook.total_chunks,
            "chapters": [
                {
                    "chapter_number": ch.chapter_number,
                    "title": ch.title,
                    "start_page": ch.start_page,
                    "end_page": ch.end_page,
                }
                for ch in textbook.chapters
            ],
        }
