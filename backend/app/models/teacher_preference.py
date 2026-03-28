"""Teacher preference model for long-term memory."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TeacherPreference(Base):
    """Long-term memory for teacher preferences."""

    __tablename__ = "teacher_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preferred_bloom_distribution = Column(JSON, nullable=True)  # Default bloom distribution
    preferred_exam_types = Column(JSON, nullable=True)  # mcq/essay/mixed ratios
    subject_focus = Column(String(100), nullable=True)  # physics, math, etc.
    style_notes = Column(Text, nullable=True)  # Agent-written style preference notes
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="preferences")
