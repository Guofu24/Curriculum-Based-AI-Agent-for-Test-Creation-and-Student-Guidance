import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Text, ForeignKey, Enum as SAEnum, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from database import Base


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class Textbook(Base):
    __tablename__ = "textbooks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf, docx, pptx
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    status: Mapped[ProcessingStatus] = mapped_column(
        SAEnum(ProcessingStatus), default=ProcessingStatus.PENDING
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    owner = relationship("User", back_populates="textbooks")
    chapters = relationship("TextbookChapter", back_populates="textbook", cascade="all, delete-orphan")
    chunks = relationship("TextbookChunk", back_populates="textbook", cascade="all, delete-orphan")


class TextbookChapter(Base):
    __tablename__ = "textbook_chapters"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    textbook_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=True)
    end_page: Mapped[int] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    key_concepts: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array of concepts

    textbook = relationship("Textbook", back_populates="chapters")


class TextbookChunk(Base):
    """Stores raw chunk text in PostgreSQL for BM25 keyword search.
    Vector embeddings are stored in Pinecone (cloud)."""
    __tablename__ = "textbook_chunks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    textbook_id: Mapped[str] = mapped_column(ForeignKey("textbooks.id"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)  # JSON extra metadata

    textbook = relationship("Textbook", back_populates="chunks")
