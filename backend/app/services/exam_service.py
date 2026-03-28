"""Exam service: handles exam creation, management, and history."""

import uuid
from typing import Any
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exam import Exam, ExamVersion, FeedbackEvent
from app.models.document import Document
from app.core.redis_client import RedisClient
from app.agents.memory import LongTermMemory


class ExamServiceError(Exception):
    """Raised when exam operation fails."""
    pass


class ExamService:
    """Service for exam management."""

    def __init__(self, db: AsyncSession, redis: RedisClient | None = None):
        self.db = db
        self.long_term = LongTermMemory(db)

    async def create_exam(
        self,
        user_id: UUID,
        document_id: UUID | None,
        title: str | None,
        scope: list[str],
        exam_config: dict,
        course_id: UUID | None = None,
    ) -> Exam:
        """Create a new exam record."""
        exam = Exam(
            user_id=user_id,
            document_id=document_id,
            course_id=course_id,
            title=title or exam_config.get("prompt", "Đề kiểm tra")[:500],
            scope=scope,
            exam_config=exam_config,
            questions=[],
            status="draft",
            exam_type=exam_config.get("exam_type", "mixed"),
            difficulty=exam_config.get("difficulty", "medium"),
            instructions=exam_config.get("instructions"),
            output_language=exam_config.get("output_language", "vi"),
            strict_scope_flag=exam_config.get("constraints", {}).get("strict_grounding", True),
            time_limit_minutes=exam_config.get("time_limit_minutes"),
        )

        self.db.add(exam)
        await self.db.commit()
        await self.db.refresh(exam)

        # Create initial version
        version = ExamVersion(
            exam_id=exam.id,
            version_number=1,
            status="draft",
            created_by=user_id,
            questions=[],
            edit_operations=[],
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(exam)

        return exam

    async def get_exam(self, exam_id: UUID, user_id: UUID) -> Exam | None:
        """Get an exam by ID, ensuring user owns it."""
        result = await self.db.execute(
            select(Exam).where(
                Exam.id == exam_id,
                Exam.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_exams(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
    ) -> tuple[list[Exam], int]:
        """List exams for a user with pagination."""
        offset = (page - 1) * limit

        query = select(Exam).where(Exam.user_id == user_id)
        if status:
            query = query.where(Exam.status == status)

        # Get total count
        count_result = await self.db.execute(
            select(func.count(Exam.id)).where(Exam.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            query
            .order_by(Exam.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        exams = list(result.scalars().all())

        return exams, total

    async def update_questions(
        self,
        exam_id: UUID,
        questions: list[dict],
        cost_report: dict | None = None,
    ) -> None:
        """Update exam questions after generation."""
        # Update current version
        version_result = await self.db.execute(
            select(ExamVersion)
            .where(ExamVersion.exam_id == exam_id)
            .order_by(ExamVersion.version_number.desc())
            .limit(1)
        )
        version = version_result.scalar_one_or_none()
        if version:
            version.questions = questions

        update_values: dict[str, Any] = {
            "questions": questions,
            "total_questions": len(questions),
            "updated_at": datetime.now(timezone.utc),
        }
        if cost_report:
            update_values["provider_logs"] = cost_report.get("breakdown", {})
            update_values["total_tokens"] = cost_report.get("total_tokens", 0)
            update_values["total_cost_usd"] = cost_report.get("total_cost_usd", 0)

        await self.db.execute(
            update(Exam).where(Exam.id == exam_id).values(**update_values)
        )
        await self.db.commit()

    async def update_question(
        self,
        exam_id: UUID,
        question_id: str,
        updates: dict,
    ) -> None:
        """Update a single question (inline edit)."""
        result = await self.db.execute(
            select(Exam).where(Exam.id == exam_id)
        )
        exam = result.scalar_one_or_none()
        if not exam:
            raise ExamServiceError("Exam not found")

        questions = exam.questions or []
        updated = False

        for i, q in enumerate(questions):
            q_id = q.get("id") or q.get("question_id")
            if q_id == question_id:
                questions[i] = {**q, **updates}
                updated = True
                break

        if not updated:
            raise ExamServiceError(f"Question {question_id} not found")

        # Update current version
        version_result = await self.db.execute(
            select(ExamVersion)
            .where(ExamVersion.exam_id == exam_id)
            .order_by(ExamVersion.version_number.desc())
            .limit(1)
        )
        version = version_result.scalar_one_or_none()
        if version:
            version.questions = questions

        # Log feedback event
        feedback = FeedbackEvent(
            exam_id=exam_id,
            signal_type="edit_direct",
            severity="info",
            workflow_stage="generation",
            event_source="human",
            question_id=UUID(question_id) if question_id else None,
            review_status="corrected",
            reviewed_by_human=True,
            payload={"updates": updates},
        )
        self.db.add(feedback)

        await self.db.execute(
            update(Exam)
            .where(Exam.id == exam_id)
            .values(
                questions=questions,
                human_edit_count=(exam.human_edit_count or 0) + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def partial_regenerate(
        self,
        exam_id: UUID,
        edits: list[dict],
        user_id: UUID,
    ) -> dict:
        """
        Apply partial edits/regeneration to specific questions.
        Called by the generation router.
        """
        result = await self.db.execute(
            select(Exam).where(Exam.id == exam_id)
        )
        exam = result.scalar_one_or_none()
        if not exam:
            raise ExamServiceError("Exam not found")

        questions = exam.questions or []
        all_ids = {q.get("id") or q.get("question_id"): i for i, q in enumerate(questions)}

        for edit in edits:
            edit_type = edit.get("edit_type", "regenerate")
            for qid in edit.get("question_ids", []):
                idx = all_ids.get(qid)
                if idx is None:
                    continue

                if edit_type == "delete":
                    questions[idx]["is_validated"] = False
                    questions[idx]["error_categories"] = ["deleted"]
                elif edit_type == "lock":
                    questions[idx]["is_locked"] = True
                elif edit_type == "unlock":
                    questions[idx]["is_locked"] = False
                elif edit_type == "edit_text":
                    questions[idx]["content"] = edit.get("new_content")
                    questions[idx]["is_human_edited"] = True
                elif edit_type == "edit_options" and edit.get("new_options"):
                    questions[idx]["options"] = [
                        {"label": o.get("label"), "text": o.get("text")}
                        for o in edit["new_options"]
                    ]
                    questions[idx]["is_human_edited"] = True
                elif edit_type == "edit_answer":
                    questions[idx]["correct_answer"] = edit.get("new_correct_answer")
                    questions[idx]["is_human_edited"] = True
                elif edit_type == "edit_bloom":
                    questions[idx]["bloom_level"] = edit.get("new_bloom_level")
                    questions[idx]["is_human_edited"] = True

        # Update exam
        await self.db.execute(
            update(Exam)
            .where(Exam.id == exam_id)
            .values(
                questions=questions,
                regenerate_count=(exam.regenerate_count or 0) + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

        return {"questions": questions, "cost": None}

    async def regenerate_questions(
        self,
        exam_id: UUID,
        question_ids: list[str] | None = None,
    ) -> None:
        """Mark questions for regeneration."""
        result = await self.db.execute(
            select(Exam).where(Exam.id == exam_id)
        )
        exam = result.scalar_one_or_none()
        if not exam:
            raise ExamServiceError("Exam not found")

        # Log feedback event
        feedback = FeedbackEvent(
            exam_id=exam_id,
            signal_type="regenerate_requested",
            severity="info",
            workflow_stage="generation",
            event_source="human",
            payload={"question_ids": question_ids},
        )
        self.db.add(feedback)

        await self.db.execute(
            update(Exam)
            .where(Exam.id == exam_id)
            .values(regenerate_count=(exam.regenerate_count or 0) + 1)
        )
        await self.db.commit()

    async def publish_exam(self, exam_id: UUID, user_id: UUID) -> None:
        """Publish an exam and learn teacher preferences."""
        result = await self.db.execute(
            select(Exam).where(
                Exam.id == exam_id,
                Exam.user_id == user_id,
            )
        )
        exam = result.scalar_one_or_none()
        if not exam:
            raise ExamServiceError("Exam not found")

        # Log feedback event
        feedback = FeedbackEvent(
            exam_id=exam_id,
            signal_type="publish",
            severity="info",
            workflow_stage="generation",
            event_source="human",
            actor_id=user_id,
            reviewed_by_human=True,
            review_status="accepted",
        )
        self.db.add(feedback)

        await self.db.execute(
            update(Exam)
            .where(Exam.id == exam_id)
            .values(
                status="published",
                published_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

        # Learn teacher preferences
        if exam.exam_config:
            try:
                await self.long_term.update_from_exam(user_id, exam.exam_config)
            except Exception:
                pass  # Non-critical

    async def delete_exam(self, exam_id: UUID, user_id: UUID) -> bool:
        """Delete an exam and its history."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return False

        await self.db.delete(exam)
        await self.db.commit()
        return True

    async def get_exam_history(
        self,
        exam_id: UUID,
        user_id: UUID,
    ) -> list[ExamVersion]:
        """Get exam versions (history) as ExamVersion list."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return []

        result = await self.db.execute(
            select(ExamVersion)
            .where(ExamVersion.exam_id == exam_id)
            .order_by(ExamVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def restore_snapshot(
        self,
        exam_id: UUID,
        history_id: UUID,
        user_id: UUID,
    ) -> None:
        """Restore exam to a previous version."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            raise ExamServiceError("Exam not found")

        result = await self.db.execute(
            select(ExamVersion).where(ExamVersion.id == history_id)
        )
        version = result.scalar_one_or_none()
        if not version or version.exam_id != exam_id:
            raise ExamServiceError("Version not found")

        # Update current version
        current_result = await self.db.execute(
            select(ExamVersion)
            .where(ExamVersion.exam_id == exam_id)
            .order_by(ExamVersion.version_number.desc())
            .limit(1)
        )
        current = current_result.scalar_one_or_none()

        # Log feedback event
        feedback = FeedbackEvent(
            exam_id=exam_id,
            signal_type="restore",
            severity="info",
            workflow_stage="generation",
            event_source="human",
            exam_version_id=version.id,
            payload={"restored_from_version": version.version_number},
        )
        self.db.add(feedback)

        if current:
            current.questions = version.questions

        await self.db.execute(
            update(Exam)
            .where(Exam.id == exam_id)
            .values(
                questions=version.questions,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    def get_mcq_essay_counts(self, questions: list[dict]) -> tuple[int, int]:
        """Get MCQ and essay counts from questions list."""
        mcq_count = sum(1 for q in questions if q.get("type") == "mcq" or q.get("question_type") == "mcq")
        essay_count = sum(1 for q in questions if q.get("type") == "essay" or q.get("question_type") == "essay")
        return mcq_count, essay_count

    # ── Feedback & Quality helpers ──────────────────────────────────────────────

    async def get_feedback_events(
        self,
        exam_id: UUID,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
    ) -> list[FeedbackEvent]:
        """Get feedback events for an exam."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return []

        offset = (page - 1) * limit
        result = await self.db.execute(
            select(FeedbackEvent)
            .where(FeedbackEvent.exam_id == exam_id)
            .order_by(FeedbackEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_quality_summary(self, user_id: UUID) -> dict:
        """Get quality metrics summary across all user's exams."""
        result = await self.db.execute(
            select(
                func.count(Exam.id).label("exams_generated"),
                func.avg(Exam.quality_score).label("avg_quality_score"),
                func.avg(Exam.verifier_pass_rate).label("avg_verifier_pass_rate"),
                func.avg(Exam.evidence_coverage_rate).label("avg_evidence_coverage_rate"),
                func.sum(Exam.regenerate_count).label("total_regenerates"),
                func.sum(Exam.human_edit_count).label("total_human_edits"),
                func.count(FeedbackEvent.id).label("total_feedback_events"),
            )
            .outerjoin(FeedbackEvent, Exam.id == FeedbackEvent.exam_id)
            .where(Exam.user_id == user_id)
        )
        row = result.one()

        # Get top error categories
        error_result = await self.db.execute(
            select(
                FeedbackEvent.error_categories,
            )
            .where(
                FeedbackEvent.exam_id.in_(
                    select(Exam.id).where(Exam.user_id == user_id)
                )
            )
        )
        error_counts: dict[str, int] = {}
        for row2 in error_result.all():
            cats = row2[0] or []
            for cat in cats:
                error_counts[cat] = error_counts.get(cat, 0) + 1

        top_errors = sorted(error_counts.items(), key=lambda x: -x[1])[:5]
        top_error_categories = [{"category": k, "count": v} for k, v in top_errors]

        # Get recent warnings
        recent_result = await self.db.execute(
            select(FeedbackEvent)
            .where(
                and_(
                    FeedbackEvent.exam_id.in_(
                        select(Exam.id).where(Exam.user_id == user_id)
                    ),
                    FeedbackEvent.severity.in_(["warning", "error"]),
                )
            )
            .order_by(FeedbackEvent.created_at.desc())
            .limit(10)
        )
        recent_warnings = list(recent_result.scalars().all())

        return {
            "documents_active": 0,  # TODO: compute from documents
            "exams_generated": row[0] or 0,
            "question_count": 0,  # TODO: sum total_questions
            "verifier_pass_rate": float(row[2] or 0),
            "verifier_warning_rate": 0,  # TODO
            "evidence_coverage_rate": float(row[3] or 0),
            "scope_violation_rate": 0,  # TODO
            "avg_regenerate_count": 0,  # TODO
            "avg_human_edit_count": 0,  # TODO
            "version_churn": 0,  # TODO
            "top_error_categories": top_error_categories,
            "recent_warnings": recent_warnings,
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_feedback_store_summary(self, user_id: UUID) -> dict:
        """Get feedback store summary across all user exams."""
        result = await self.db.execute(
            select(
                func.count(FeedbackEvent.id).label("total_events"),
                func.count(
                    FeedbackEvent.reviewed_by_human == True  # noqa: E712
                ).label("reviewed_count"),
                func.count(
                    FeedbackEvent.review_status == "accepted"  # noqa: E712
                ).label("accepted_count"),
                func.count(
                    FeedbackEvent.review_status == "rejected"  # noqa: E712
                ).label("rejected_count"),
                func.count(
                    FeedbackEvent.review_status == "corrected"  # noqa: E712
                ).label("corrected_count"),
            )
            .join(Exam, FeedbackEvent.exam_id == Exam.id)
            .where(Exam.user_id == user_id)
        )
        row = result.one()

        # Get recent events
        recent_result = await self.db.execute(
            select(FeedbackEvent)
            .join(Exam, FeedbackEvent.exam_id == Exam.id)
            .where(Exam.user_id == user_id)
            .order_by(FeedbackEvent.created_at.desc())
            .limit(10)
        )
        recent_events = list(recent_result.scalars().all())

        return {
            "total_events": row[0] or 0,
            "reviewed_by_human_count": row[1] or 0,
            "accepted_count": row[2] or 0,
            "rejected_count": row[3] or 0,
            "corrected_count": row[4] or 0,
            "linked_eval_count": 0,  # TODO
            "top_signal_types": [],  # TODO
            "top_error_categories": [],  # TODO
            "recent_events": recent_events,
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_feedback_store(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 50,
        severity: str | None = None,
        review_status: str | None = None,
    ) -> tuple[list[FeedbackEvent], int]:
        """Get filtered feedback events across all user exams."""
        base_query = (
            select(FeedbackEvent)
            .join(Exam, FeedbackEvent.exam_id == Exam.id)
            .where(Exam.user_id == user_id)
        )
        if severity:
            base_query = base_query.where(FeedbackEvent.severity == severity)
        if review_status:
            base_query = base_query.where(FeedbackEvent.review_status == review_status)

        count_result = await self.db.execute(
            select(func.count(FeedbackEvent.id))
            .join(Exam, FeedbackEvent.exam_id == Exam.id)
            .where(Exam.user_id == user_id)
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * limit
        result = await self.db.execute(
            base_query
            .order_by(FeedbackEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total
