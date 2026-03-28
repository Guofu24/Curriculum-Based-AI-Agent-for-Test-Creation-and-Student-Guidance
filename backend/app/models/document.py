"""Document model - aligned with frontend's API expectations."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, JSON, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Document(Base):
    """Document model for uploaded teaching materials."""

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)

    title = Column(String(500), nullable=False)
    file_name = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # pdf, docx, pptx
    file_size = Column(BigInteger, default=0)
    file_hash = Column(String(64), nullable=True)  # SHA256 hash for deduplication
    file_storage_url = Column(String(1000), nullable=True)  # S3 presigned URL or path

    language = Column(String(10), default="vi")

    status = Column(String(50), default="pending")  # pending, processing, processed, structured, indexed, failed
    parse_error_message = Column(String(2000), nullable=True)
    version = Column(Integer, default=1)

    # RAG pipeline outputs
    total_pages_or_slides = Column(Integer, default=0)
    total_chunks = Column(Integer, default=0)

    # Curriculum tree (matches frontend's CurriculumNode[])
    curriculum_tree = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="documents")
    course = relationship("Course", back_populates="documents")
    exams = relationship("Exam", back_populates="document")
