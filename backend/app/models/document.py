"""Document model for uploaded teaching materials."""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Integer, ForeignKey, func, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.exam import Exam


class Document(Base):
    """Document model for uploaded teaching materials.

    Fields per spec:
    - id, user_id, original_filename, file_type, s3_key
    - processing_status: pending | processing | completed | failed
    - heading_tree: JSONB — full nested heading structure
    - total_chapters: int — number of level-1 headings detected
    - uploaded_at
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf, docx, pptx
    s3_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending, processing, completed, failed
    parse_error_message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    heading_tree: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    total_chapters: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_pages_or_slides: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_chunks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="documents")
    exams: Mapped[List["Exam"]] = relationship(
        "Exam", back_populates="document", cascade="all, delete-orphan"
    )
