from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.curriculum import Section
from models.textbook import Textbook, TextbookChunk


class DocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_document_sections(self, document_id: str) -> list[Section]:
        result = await self.db.execute(
            select(Section)
            .where(Section.document_id == document_id)
            .order_by(Section.section_order.asc(), Section.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_document_chunks(self, document_id: str) -> list[TextbookChunk]:
        result = await self.db.execute(
            select(TextbookChunk)
            .where(TextbookChunk.textbook_id == document_id)
            .order_by(TextbookChunk.chunk_index.asc())
        )
        return list(result.scalars().all())

    async def get_document(self, document_id: str) -> Textbook | None:
        result = await self.db.execute(
            select(Textbook).where(Textbook.id == document_id)
        )
        return result.scalar_one_or_none()
