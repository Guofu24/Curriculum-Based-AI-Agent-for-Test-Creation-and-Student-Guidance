from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.curriculum import Section
from models.document import DocumentChunkRecord, DocumentRecord


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

    async def get_document_chunks(self, document_id: str) -> list[DocumentChunkRecord]:
        result = await self.db.execute(
            select(DocumentChunkRecord)
            .where(DocumentChunkRecord.textbook_id == document_id)
            .order_by(DocumentChunkRecord.chunk_index.asc())
        )
        return list(result.scalars().all())

    async def get_document_chunks_for_sections(
        self,
        document_id: str,
        section_ids: list[str],
    ) -> list[DocumentChunkRecord]:
        normalized_section_ids = [
            str(section_id).strip()
            for section_id in section_ids
            if str(section_id).strip()
        ]
        if not normalized_section_ids:
            return []

        result = await self.db.execute(
            select(DocumentChunkRecord)
            .where(
                DocumentChunkRecord.textbook_id == document_id,
                DocumentChunkRecord.section_id.in_(normalized_section_ids),
            )
            .order_by(DocumentChunkRecord.chunk_index.asc())
        )
        return list(result.scalars().all())

    async def get_document_chunks_without_section_id(self, document_id: str) -> list[DocumentChunkRecord]:
        result = await self.db.execute(
            select(DocumentChunkRecord)
            .where(
                DocumentChunkRecord.textbook_id == document_id,
                DocumentChunkRecord.section_id.is_(None),
            )
            .order_by(DocumentChunkRecord.chunk_index.asc())
        )
        return list(result.scalars().all())

    async def get_document(self, document_id: str) -> DocumentRecord | None:
        result = await self.db.execute(
            select(DocumentRecord).where(DocumentRecord.id == document_id)
        )
        return result.scalar_one_or_none()
