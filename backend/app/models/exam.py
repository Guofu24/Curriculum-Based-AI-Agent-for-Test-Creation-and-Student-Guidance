"""Exam model for generated test papers."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Integer, ForeignKey, Numeric, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.document import Document


class Exam(Base):
    """Exam model for generated test papers."""

    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    exam_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    questions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")  # draft, published
    cost_report: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="exams")
    document: Mapped[Optional["Document"]] = relationship("Document", back_populates="exams")
    history: Mapped[List["ExamHistory"]] = relationship(
        "ExamHistory", back_populates="exam", cascade="all, delete-orphan"
    )

    @property
    def course_id(self) -> None:
        return None

    @property
    def exam_type(self) -> str:
        return (self.exam_config or {}).get("exam_type", "mixed")

    @property
    def difficulty(self) -> str:
        return (self.exam_config or {}).get("difficulty", "medium")

    @property
    def chapters(self) -> list[str]:
        return list(self.scope or [])

    @property
    def total_questions(self) -> int:
        return len(self.questions or [])

    @property
    def strict_scope_flag(self) -> bool:
        return (self.exam_config or {}).get("strict_scope_flag", True)

    @property
    def quality_score(self) -> float | None:
        scores = [
            q.get("quality_score")
            for q in (self.questions or [])
            if isinstance(q, dict) and q.get("quality_score") is not None
        ]
        if not scores:
            return None
        return round(sum(float(s) for s in scores) / len(scores), 4)

    @property
    def version_count(self) -> int:
        return len(self.history or []) or 1

    @property
    def verifier_pass_rate(self) -> float | None:
        questions = [q for q in (self.questions or []) if isinstance(q, dict)]
        if not questions:
            return None
        passed = sum(1 for q in questions if q.get("is_validated"))
        return round(passed / len(questions), 4)

    @property
    def evidence_coverage_rate(self) -> float | None:
        questions = [q for q in (self.questions or []) if isinstance(q, dict)]
        if not questions:
            return None
        covered = sum(1 for q in questions if q.get("source_evidence"))
        return round(covered / len(questions), 4)

    @property
    def warning_count(self) -> int:
        return sum(len(q.get("warnings", [])) for q in (self.questions or []) if isinstance(q, dict))

    @property
    def regenerate_count(self) -> int:
        return int((self.exam_config or {}).get("regenerate_count", 0))

    @property
    def human_edit_count(self) -> int:
        return sum(1 for q in (self.questions or []) if isinstance(q, dict) and q.get("is_human_edited"))

    @property
    def variant_number(self) -> int:
        return 1

    @property
    def instructions(self) -> str | None:
        return (self.exam_config or {}).get("instructions")

    @property
    def output_language(self) -> str:
        return (self.exam_config or {}).get("output_language", "vi")

    @property
    def published_at(self) -> None:
        return None

    @property
    def exam_spec(self) -> dict:
        return dict(self.exam_config or {})

    @property
    def blueprint(self) -> dict:
        return (self.exam_config or {}).get("blueprint") or {}

    @property
    def selected_scope(self) -> list[str]:
        return list(self.scope or [])

    @property
    def quality_scores(self) -> list[dict]:
        return [
            {
                "question_id": q.get("id") or q.get("question_id"),
                "quality_score": q.get("quality_score"),
                "verification_status": q.get("verification_status"),
            }
            for q in (self.questions or [])
            if isinstance(q, dict)
        ]

    @property
    def grounding_reports(self) -> list[dict]:
        return [
            {
                "question_id": q.get("id") or q.get("question_id"),
                "source_evidence": q.get("source_evidence", []),
            }
            for q in (self.questions or [])
            if isinstance(q, dict)
        ]

    @property
    def duplicate_groups(self) -> list:
        return []

    @property
    def provider_logs(self) -> dict:
        return (self.cost_report or {}).get("breakdown", {})


class ExamHistory(Base):
    """Versioned snapshot of an exam for history tracking."""

    __tablename__ = "exam_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)  # generate, edit_direct, edit_prompt, regenerate
    change_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    exam: Mapped["Exam"] = relationship("Exam", back_populates="history")
