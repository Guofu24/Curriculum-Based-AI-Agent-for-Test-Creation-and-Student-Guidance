"""FeedbackEvent model for quality signals from the AI pipeline."""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from enum import Enum

from sqlalchemy import String, ForeignKey, DateTime, func, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.exam import Exam


class SignalType(str, Enum):
    """Types of quality signals from the pipeline."""
    BLOOM_MISMATCH = "bloom_mismatch"
    OUT_OF_SCOPE = "out_of_scope"
    DUPLICATE = "duplicate"
    QUALITY_LOW = "quality_low"
    ANSWER_INCORRECT = "answer_incorrect"
    VALIDATION_WARNING = "validation_warning"
    GENERATION_ERROR = "generation_error"
    PUBLISH = "publish"
    EDIT_APPLIED = "edit_applied"


class Severity(str, Enum):
    """Severity levels for feedback signals."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReviewStatus(str, Enum):
    """Review status for feedback events."""
    PENDING = "pending"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class FeedbackEvent(Base):
    """
    Feedback event model for quality signals and human review signals.

    Persists feedback events that were previously stored only in Redis.
    This enables the Feedback Store UI and analytics features.
    """

    __tablename__ = "feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exam_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_history.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Signal classification
    signal_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(
        String(20), default=Severity.WARNING.value, nullable=False
    )

    # Workflow context
    workflow_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Source tracking
    source_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Review tracking
    review_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True
    )
    reviewed_by_human: Mapped[bool] = mapped_column(
        String(5), default="false", nullable=False
    )

    # Error categorization
    error_categories: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Snapshot references for diff tracking
    before_snapshot_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    after_snapshot_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Flexible payload for additional data
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Human-readable description
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    exam: Mapped["Exam"] = relationship("Exam", back_populates="feedback_events")
    user: Mapped["User"] = relationship("User")

    @property
    def is_resolved(self) -> bool:
        """Return True if this event has been reviewed."""
        return self.review_status in (
            ReviewStatus.ACCEPTED.value,
            ReviewStatus.REJECTED.value,
            ReviewStatus.CORRECTED.value,
        )
