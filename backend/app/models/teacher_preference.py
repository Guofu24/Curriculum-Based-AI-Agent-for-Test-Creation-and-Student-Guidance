"""Teacher preference model for long-term memory."""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class TeacherPreference(Base):
    """Long-term memory for teacher preferences."""

    __tablename__ = "teacher_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_bloom_distribution: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    preferred_exam_types: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    subject_focus: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    style_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Episodic memory: topic strings from past exams (capped at 200 entries)
    topic_history: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # Recent rejection feedback texts for learning teacher style (capped at 20)
    reject_patterns: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="preferences")
