from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PlaybookBulletType(str, enum.Enum):
    HARD_RULE = "hard_rule"
    GENERATION_HEURISTIC = "generation_heuristic"
    FAILURE_PATTERN = "failure_pattern"
    REVIEW_HEURISTIC = "review_heuristic"
    VERIFIER_HINT = "verifier_hint"
    SUBJECT_HINT = "subject_hint"


class PlaybookBulletStatus(str, enum.Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class ReflectionCandidateStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    MERGED = "merged"


class PlaybookBullet(Base):
    __tablename__ = "playbook_bullets"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    status: Mapped[PlaybookBulletStatus] = mapped_column(
        SAEnum(PlaybookBulletStatus, native_enum=False),
        nullable=False,
        default=PlaybookBulletStatus.DRAFT,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    bullet_type: Mapped[PlaybookBulletType] = mapped_column(
        SAEnum(PlaybookBulletType, native_enum=False),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(50), nullable=False, default="physics")
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="vi")
    question_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="mcq_single_answer",
    )
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=True)
    source_signals_json: Mapped[list] = mapped_column(JSON, nullable=True)
    helpful_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    harmful_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    tags_json: Mapped[list] = mapped_column(JSON, nullable=True)
    created_from: Mapped[str] = mapped_column(String(100), nullable=True)
    review_status: Mapped[str] = mapped_column(String(50), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    reflection_candidates = relationship(
        "ReflectionCandidate",
        back_populates="promoted_bullet",
    )


class ReflectionCandidate(Base):
    __tablename__ = "reflection_candidates"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    status: Mapped[ReflectionCandidateStatus] = mapped_column(
        SAEnum(ReflectionCandidateStatus, native_enum=False),
        nullable=False,
        default=ReflectionCandidateStatus.CANDIDATE,
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False, default="physics")
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="vi")
    question_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="mcq_single_answer",
    )
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    proposed_title: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_bullet_type: Mapped[PlaybookBulletType] = mapped_column(
        SAEnum(PlaybookBulletType, native_enum=False),
        nullable=False,
    )
    proposed_bullet_text: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=True)
    source_event_ids_json: Mapped[list] = mapped_column(JSON, nullable=True)
    source_eval_sample_ids_json: Mapped[list] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    merge_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    review_notes: Mapped[str] = mapped_column(Text, nullable=True)
    promoted_bullet_id: Mapped[str] = mapped_column(
        ForeignKey("playbook_bullets.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    promoted_bullet = relationship(
        "PlaybookBullet",
        back_populates="reflection_candidates",
    )
