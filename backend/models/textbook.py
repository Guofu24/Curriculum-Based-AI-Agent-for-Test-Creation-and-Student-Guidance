import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    STRUCTURED = "structured"
    INDEXED = "indexed"
    FAILED = "failed"
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"


class Textbook(Base):
    """
    Legacy textbook model, now acting as the system's document record.

    We keep the historical table/model name to avoid breaking the existing app,
    but expose it through document-oriented services and APIs.
    """

    __tablename__ = "textbooks"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_storage_url: Mapped[str] = mapped_column(String(1000), nullable=True)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=True)
    status: Mapped[ProcessingStatus] = mapped_column(
        SAEnum(ProcessingStatus, native_enum=False),
        default=ProcessingStatus.UPLOADED,
    )
    language: Mapped[str] = mapped_column(String(20), nullable=True, default="vi")
    version: Mapped[int] = mapped_column(Integer, default=1)
    total_pages_or_slides: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    parse_error_message: Mapped[str] = mapped_column(Text, nullable=True)
    curriculum_tree_json: Mapped[list] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    owner = relationship("User", back_populates="textbooks")
    course = relationship("Course", back_populates="documents")
    chapters = relationship(
        "TextbookChapter",
        back_populates="textbook",
        cascade="all, delete-orphan",
    )
    chunks = relationship(
        "TextbookChunk",
        back_populates="textbook",
        cascade="all, delete-orphan",
    )
    sections = relationship(
        "Section",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class TextbookChapter(Base):
    __tablename__ = "textbook_chapters"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    textbook_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=True)
    end_page: Mapped[int] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    key_concepts: Mapped[list] = mapped_column(JSON, nullable=True)

    textbook = relationship("Textbook", back_populates="chapters")


class TextbookChunk(Base):
    """Stores raw chunk text in PostgreSQL for BM25 keyword search."""

    __tablename__ = "textbook_chunks"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    textbook_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=True)
    chapter: Mapped[str] = mapped_column(String(500), nullable=True)
    parent_heading: Mapped[str] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)

    textbook = relationship("Textbook", back_populates="chunks")
