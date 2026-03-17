"""
Student Guidance Models — Database tables for student submissions and mastery profiles.

These models support the extended Student Guidance features:
  - StudentSubmission: Records of student answers to exam questions
  - MasteryProfile: Aggregated mastery levels per student per scope unit

Spec reference: §5.12 (Submissions), §5.13 (Mastery Profiles), §6.16
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database import Base


class StudentSubmission(Base):
    """
    Records a student's answers to a specific exam.

    Fields align with spec §5.12:
    - Links to user, exam, and exam_version
    - Stores individual answers as JSON
    - Tracks scoring (auto + manual) and submission status
    """
    __tablename__ = "student_submissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    exam_id = Column(String, ForeignKey("exams.id"), nullable=False, index=True)
    exam_version_id = Column(String, ForeignKey("exam_versions.id"), nullable=True)

    # Status: draft, submitted, graded, reviewed
    status = Column(String, default="submitted", nullable=False)

    # Student answers — JSON array of {question_id, answer, is_correct, score}
    answers_json = Column(JSONB, default=list)

    # Scoring
    total_score = Column(Float, nullable=True)
    max_possible_score = Column(Float, nullable=True)
    auto_graded = Column(Boolean, default=False)
    manual_graded = Column(Boolean, default=False)

    # Per-question analysis — JSON array of {question_id, bloom_level, scope_tags, is_correct, mastery_signal}
    question_analysis_json = Column(JSONB, default=list)

    # Guidance output — generated after grading
    guidance_text = Column(Text, nullable=True)
    guidance_json = Column(JSONB, nullable=True)  # structured guidance data
    weak_topics_json = Column(JSONB, default=list)  # [{scope_id, title, mastery_level, recommendation}]
    strong_topics_json = Column(JSONB, default=list)

    submitted_at = Column(DateTime, default=datetime.utcnow)
    graded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    student = relationship("User", foreign_keys=[student_id])
    exam = relationship("Exam", foreign_keys=[exam_id])


class MasteryProfile(Base):
    """
    Aggregated mastery profile per student per scope unit.

    Updated incrementally as students complete exams.
    Tracks mastery across Bloom levels for personalized guidance.

    Spec reference: §5.13
    """
    __tablename__ = "mastery_profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Scope identification
    scope_id = Column(String, nullable=False, index=True)
    scope_type = Column(String, default="chapter")  # chapter, topic, learning_objective
    scope_title = Column(String, nullable=True)
    chapter_number = Column(Integer, nullable=True)

    # Mastery scores (0.0 to 1.0)
    overall_mastery = Column(Float, default=0.0)

    # Per-Bloom mastery — {bloom_level: mastery_score}
    bloom_mastery_json = Column(JSONB, default=dict)

    # Statistics
    total_attempts = Column(Integer, default=0)
    correct_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)

    # Trend data — [{date, score, exam_id}]
    trend_json = Column(JSONB, default=list)

    # Recommendation
    recommended_focus = Column(Text, nullable=True)
    last_exam_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    # Relationships
    student = relationship("User", foreign_keys=[student_id])

    # Composite unique constraint
    __table_args__ = (
        # Each student has one mastery entry per scope unit
        # (handled at application level for flexibility)
    )
