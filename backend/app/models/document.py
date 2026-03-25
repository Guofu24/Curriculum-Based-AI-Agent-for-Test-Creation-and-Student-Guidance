"""Document-first aliases for the active MVP/Phase 3 runtime.

The database still persists to historical `textbooks` / `textbook_chunks`
tables for compatibility with existing local data. Active services, APIs, and
docs should import the aliases from this module so new contributors see the
document-oriented domain first.
"""

from app.models.textbook import (
    ProcessingStatus as DocumentProcessingStatus,
    Textbook as DocumentRecord,
    TextbookChapter as DocumentChapterRecord,
    TextbookChunk as DocumentChunkRecord,
)

__all__ = [
    "DocumentChunkRecord",
    "DocumentChapterRecord",
    "DocumentProcessingStatus",
    "DocumentRecord",
]

