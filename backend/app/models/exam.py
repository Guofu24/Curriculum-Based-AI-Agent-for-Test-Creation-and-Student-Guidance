"""Exam model - aligned with frontend's API expectations."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, JSON, Numeric, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Exam(Base):
    """Exam model for generated test papers."""

    __tablename__ = "exams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)

    title = Column(String(500), nullable=False)
    exam_type = Column(String(50), default="mcq")  # mcq, essay, mixed
    difficulty = Column(String(50), default="medium")
    status = Column(String(50), default="draft")  # draft, published

    # Scope
    chapters = Column(JSON, nullable=True)  # [1, 2, 3] - chapter numbers
    selected_scope = Column(JSON, nullable=True)  # [ScopeUnitPayload, ...]
    scope = Column(JSON, nullable=True)  # raw scope strings for generation

    # Configuration
    instructions = Column(Text, nullable=True)
    output_language = Column(String(10), default="vi")
    strict_scope_flag = Column(Boolean, default=True)
    time_limit_minutes = Column(Integer, nullable=True)

    # Variant support
    variant_number = Column(Integer, default=1)

    # Questions (JSON) - structured to match frontend's Question[]
    questions = Column(JSON, nullable=True)
    total_questions = Column(Integer, default=0)

    # Spec and blueprint
    exam_config = Column(JSON, nullable=True)  # raw generation config
    exam_spec = Column(JSON, nullable=True)
    blueprint = Column(JSON, nullable=True)

    # Quality scores
    quality_score = Column(Numeric(5, 4), nullable=True)
    quality_scores = Column(JSON, nullable=True)  # [QualityScoreDetail, ...]
    grounding_reports = Column(JSON, nullable=True)  # [GroundingReportDetail, ...]
    duplicate_groups = Column(JSON, nullable=True)

    # Cost tracking
    provider_logs = Column(JSON, nullable=True)
    total_cost_usd = Column(Numeric(10, 4), nullable=True)
    total_tokens = Column(Integer, nullable=True)

    # Versioning
    current_version_id = Column(UUID(as_uuid=True), nullable=True)
    version_count = Column(Integer, default=0)

    # Counts
    verifier_pass_rate = Column(Numeric(5, 4), nullable=True)
    evidence_coverage_rate = Column(Numeric(5, 4), nullable=True)
    regenerate_count = Column(Integer, default=0)
    human_edit_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="exams")
    document = relationship("Document", back_populates="exams")
    versions = relationship("ExamVersion", back_populates="exam", cascade="all, delete-orphan")
    feedback_events = relationship("FeedbackEvent", back_populates="exam", cascade="all, delete-orphan")


class ExamVersion(Base):
    """Versioned snapshot of an exam."""

    __tablename__ = "exam_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    status = Column(String(50), default="draft")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    parent_version_id = Column(UUID(as_uuid=True), nullable=True)
    change_summary = Column(Text, nullable=True)

    # Full snapshot of this version
    questions = Column(JSON, nullable=True)
    edit_operations = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    exam = relationship("Exam", back_populates="versions")
    feedback_events = relationship("FeedbackEvent", back_populates="exam_version", cascade="all, delete-orphan")


class FeedbackEvent(Base):
    """Feedback event for observability."""

    __tablename__ = "feedback_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    exam_version_id = Column(UUID(as_uuid=True), ForeignKey("exam_versions.id", ondelete="SET NULL"), nullable=True)

    actor_id = Column(UUID(as_uuid=True), nullable=True)
    signal_type = Column(String(50), nullable=False)  # regenerate_requested, edit_text, publish, etc.
    severity = Column(String(20), default="info")  # info, warning, error
    workflow_stage = Column(String(50), nullable=True)  # generation, verification, review, etc.
    event_source = Column(String(50), nullable=True)  # human, agent, system
    source_type = Column(String(50), nullable=True)  # playbook_shadow, verifier, etc.
    source_ref = Column(String(200), nullable=True)

    question_id = Column(UUID(as_uuid=True), nullable=True)
    review_status = Column(String(50), nullable=True)  # accepted, rejected, corrected
    reviewed_by_human = Column(Boolean, default=False)

    error_categories = Column(JSON, nullable=True)  # ["wrong_answer", "bloom_mismatch", ...]

    # Snapshot refs for before/after comparison
    before_snapshot_ref = Column(String(200), nullable=True)
    after_snapshot_ref = Column(String(200), nullable=True)

    # Payload for additional data
    payload = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    exam = relationship("Exam", back_populates="feedback_events")
    exam_version = relationship("ExamVersion", back_populates="feedback_events")
