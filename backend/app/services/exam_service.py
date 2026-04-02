"""Exam service: demo-safe exam CRUD and history operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory import LongTermMemory
from app.core.redis_client import RedisClient
from app.models.exam import Exam, ExamHistory


class ExamServiceError(Exception):
    """Raised when an exam operation fails."""


class ExamService:
    """Service for exam management on top of the current Exam/ExamHistory models."""

    def __init__(self, db: AsyncSession, redis: RedisClient | None = None):
        self.db = db
        self.redis = redis
        self.long_term = LongTermMemory(db)

    async def create_exam(
        self,
        user_id: UUID,
        document_id: UUID | str | None,
        title: str | None,
        scope: list[str],
        exam_config: dict,
        course_id: UUID | None = None,
    ) -> Exam:
        """Create a new exam record."""
        _ = course_id  # Compatibility argument kept for router parity.

        stored_config = {
            **(exam_config or {}),
            "scope": list(scope or []),
        }
        normalized_document_id = UUID(str(document_id)) if document_id else None

        exam = Exam(
            user_id=user_id,
            document_id=normalized_document_id,
            title=title or (stored_config.get("user_prompt") or "De kiem tra")[:500],
            scope=list(scope or []),
            exam_config=stored_config,
            questions=[],
            status="draft",
        )
        self.db.add(exam)
        await self.db.flush()

        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="generate",
                change_description="Initial exam record created.",
            )
        )
        await self.db.commit()
        await self.db.refresh(exam)
        return exam

    async def get_exam(self, exam_id: UUID, user_id: UUID | None) -> Exam | None:
        """Get an exam by id. When user_id is None, skip ownership filter."""
        stmt = select(Exam).where(Exam.id == exam_id)
        if user_id is not None:
            stmt = stmt.where(Exam.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_exams(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
    ) -> tuple[list[Exam], int]:
        """List exams for a user with pagination."""
        offset = max(page - 1, 0) * limit

        stmt = select(Exam).where(Exam.user_id == user_id)
        count_stmt = select(func.count(Exam.id)).where(Exam.user_id == user_id)
        if status:
            stmt = stmt.where(Exam.status == status)
            count_stmt = count_stmt.where(Exam.status == status)

        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        result = await self.db.execute(
            stmt.order_by(Exam.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def update_questions(
        self,
        exam_id: UUID,
        questions: list[dict],
        cost_report: dict | None = None,
    ) -> None:
        """Persist generated questions and append a history snapshot."""
        exam = await self.get_exam(exam_id, user_id=None)
        if not exam:
            raise ExamServiceError("Exam not found")

        exam.questions = list(questions or [])
        exam.cost_report = cost_report
        exam.total_tokens = (cost_report or {}).get("total_tokens")
        exam.total_cost_usd = (cost_report or {}).get("total_cost_usd")
        exam.status = "ready_for_review" if questions else "draft"
        exam.updated_at = datetime.now(timezone.utc)
        exam.exam_config = {
            **(exam.exam_config or {}),
            "blueprint": (cost_report or {}).get("blueprint", (exam.exam_config or {}).get("blueprint", {})),
        }

        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="generate",
                change_description=f"Stored {len(questions or [])} generated questions.",
            )
        )
        await self.db.commit()

    async def update_question(
        self,
        exam_id: UUID,
        question_id: str,
        updates: dict,
        user_id: UUID | None = None,
    ) -> None:
        """Update a single question in-place and append history."""
        exam = await self.get_exam(exam_id, user_id=None)
        if not exam:
            raise ExamServiceError("Exam not found")
        if user_id is not None and exam.user_id != user_id:
            raise ExamServiceError("Access denied")

        questions = list(exam.questions or [])
        updated = False
        for idx, question in enumerate(questions):
            qid = question.get("id") or question.get("question_id")
            if qid == question_id:
                merged = {**question, **updates, "is_human_edited": True}
                questions[idx] = merged
                updated = True
                break

        if not updated:
            raise ExamServiceError(f"Question {question_id} not found")

        exam.questions = questions
        exam.updated_at = datetime.now(timezone.utc)
        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="edit_direct",
                change_description=f"Question {question_id} updated.",
            )
        )
        await self.db.commit()

    async def partial_regenerate(
        self,
        exam_id: UUID,
        edits: list[dict],
        user_id: UUID,
    ) -> dict:
        """Apply lightweight partial edits for demo/runtime compatibility."""
        exam = await self.get_exam(exam_id, user_id=None)
        if not exam:
            raise ExamServiceError("Exam not found")
        if exam.user_id != user_id:
            raise ExamServiceError("Access denied")

        questions = list(exam.questions or [])
        id_to_index = {
            (q.get("id") or q.get("question_id")): idx
            for idx, q in enumerate(questions)
            if isinstance(q, dict)
        }

        for edit in edits:
            for qid in edit.get("question_ids", []):
                idx = id_to_index.get(qid)
                if idx is None:
                    continue
                if edit.get("edit_type") == "delete":
                    questions[idx]["deleted"] = True
                elif edit.get("edit_type") == "lock":
                    questions[idx]["is_locked"] = True
                elif edit.get("edit_type") == "unlock":
                    questions[idx]["is_locked"] = False
                elif edit.get("edit_type") == "edit_text":
                    questions[idx]["stem"] = edit.get("new_content", questions[idx].get("stem", ""))
                elif edit.get("edit_type") == "edit_answer":
                    questions[idx]["correct_answer"] = edit.get("new_correct_answer")
                elif edit.get("edit_type") == "edit_bloom":
                    questions[idx]["bloom_level"] = edit.get("new_bloom_level")
                elif edit.get("edit_type") == "edit_options" and edit.get("new_options"):
                    questions[idx]["options"] = edit["new_options"]
                questions[idx]["is_human_edited"] = True

        exam.questions = questions
        exam.updated_at = datetime.now(timezone.utc)
        exam.exam_config = {
            **(exam.exam_config or {}),
            "regenerate_count": int((exam.exam_config or {}).get("regenerate_count", 0)) + 1,
        }
        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="regenerate",
                change_description="Partial regenerate/edit applied.",
            )
        )
        await self.db.commit()
        return {"questions": questions, "cost": None}

    async def regenerate_questions(
        self,
        exam_id: UUID,
        question_ids: list[str] | None = None,
        user_id: UUID | None = None,
    ) -> None:
        """Mark an exam as queued for regeneration."""
        exam = await self.get_exam(exam_id, user_id=None)
        if not exam:
            raise ExamServiceError("Exam not found")
        if user_id is not None and exam.user_id != user_id:
            raise ExamServiceError("Access denied")

        exam.status = "regenerating"
        exam.updated_at = datetime.now(timezone.utc)
        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="regenerate",
                change_description=f"Requested regeneration for {question_ids or 'all questions'}.",
            )
        )
        await self.db.commit()

    async def publish_exam(self, exam_id: UUID, user_id: UUID) -> None:
        """Publish an exam and update teacher preferences."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            raise ExamServiceError("Exam not found")

        exam.status = "published"
        exam.updated_at = datetime.now(timezone.utc)
        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="published",
                change_description="Exam published.",
            )
        )
        await self.db.commit()

        try:
            await self.long_term.update_from_exam(user_id, exam.exam_config or {})
        except Exception:
            pass

    async def delete_exam(self, exam_id: UUID, user_id: UUID) -> bool:
        """Delete an exam."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return False

        await self.db.delete(exam)
        await self.db.commit()
        return True

    async def get_exam_history(self, exam_id: UUID, user_id: UUID) -> list[ExamHistory]:
        """Return history snapshots for an exam."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return []

        result = await self.db.execute(
            select(ExamHistory)
            .where(ExamHistory.exam_id == exam_id)
            .order_by(ExamHistory.created_at.desc())
        )
        return list(result.scalars().all())

    async def restore_snapshot(
        self,
        exam_id: UUID,
        history_id: UUID,
        user_id: UUID,
    ) -> None:
        """Restore an exam from a history snapshot."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            raise ExamServiceError("Exam not found")

        result = await self.db.execute(
            select(ExamHistory).where(ExamHistory.id == history_id, ExamHistory.exam_id == exam_id)
        )
        history = result.scalar_one_or_none()
        if not history or not history.snapshot:
            raise ExamServiceError("Version not found")

        snapshot = history.snapshot
        exam.title = snapshot.get("title", exam.title)
        exam.scope = snapshot.get("scope", exam.scope)
        exam.exam_config = snapshot.get("exam_config", exam.exam_config)
        exam.questions = snapshot.get("questions", exam.questions)
        exam.status = snapshot.get("status", exam.status)
        exam.cost_report = snapshot.get("cost_report", exam.cost_report)
        exam.total_tokens = snapshot.get("total_tokens", exam.total_tokens)
        exam.total_cost_usd = snapshot.get("total_cost_usd", exam.total_cost_usd)
        exam.updated_at = datetime.now(timezone.utc)

        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="restore",
                change_description=f"Restored snapshot {history_id}.",
            )
        )
        await self.db.commit()

    def get_mcq_essay_counts(self, questions: list[dict]) -> tuple[int, int]:
        """Count MCQ and essay questions."""
        mcq_count = sum(
            1
            for q in questions
            if q.get("type") == "mcq" or q.get("question_type") == "mcq"
        )
        essay_count = sum(
            1
            for q in questions
            if q.get("type") == "essay" or q.get("question_type") == "essay"
        )
        return mcq_count, essay_count

    async def get_feedback_events(
        self,
        exam_id: UUID,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
    ) -> list[dict]:
        """Compatibility stub until a dedicated feedback table exists."""
        _ = (exam_id, user_id, page, limit)
        return []

    async def get_quality_summary(self, user_id: UUID) -> dict:
        """Return lightweight quality metrics derived from Exam rows only."""
        exams, total = await self.list_exams(user_id=user_id, page=1, limit=500)
        question_count = sum(len(exam.questions or []) for exam in exams)

        valid_rates = [
            rate for exam in exams if (rate := exam.verifier_pass_rate) is not None
        ]
        evidence_rates = [
            rate for exam in exams if (rate := exam.evidence_coverage_rate) is not None
        ]

        return {
            "documents_active": 0,
            "exams_generated": total,
            "question_count": question_count,
            "verifier_pass_rate": round(sum(valid_rates) / len(valid_rates), 4) if valid_rates else 0.0,
            "verifier_warning_rate": 0.0,
            "evidence_coverage_rate": round(sum(evidence_rates) / len(evidence_rates), 4) if evidence_rates else 0.0,
            "scope_violation_rate": 0.0,
            "avg_regenerate_count": round(
                sum(exam.regenerate_count for exam in exams) / len(exams), 4
            ) if exams else 0.0,
            "avg_human_edit_count": round(
                sum(exam.human_edit_count for exam in exams) / len(exams), 4
            ) if exams else 0.0,
            "version_churn": round(
                sum(exam.version_count for exam in exams) / len(exams), 4
            ) if exams else 0.0,
            "top_error_categories": [],
            "recent_warnings": [],
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_feedback_store_summary(self, user_id: UUID) -> dict:
        """Compatibility stub until feedback events are persisted separately."""
        _ = user_id
        return {
            "total_events": 0,
            "reviewed_by_human_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "corrected_count": 0,
            "linked_eval_count": 0,
            "top_signal_types": [],
            "top_error_categories": [],
            "recent_events": [],
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_feedback_store(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 50,
        severity: str | None = None,
        review_status: str | None = None,
    ) -> tuple[list[dict], int]:
        """Compatibility stub until feedback events are persisted separately."""
        _ = (user_id, page, limit, severity, review_status)
        return [], 0

    def _snapshot_from_exam(self, exam: Exam) -> dict[str, Any]:
        """Serialize the current exam state for history snapshots."""
        return {
            "title": exam.title,
            "scope": list(exam.scope or []),
            "exam_config": dict(exam.exam_config or {}),
            "questions": list(exam.questions or []),
            "status": exam.status,
            "cost_report": exam.cost_report,
            "total_tokens": exam.total_tokens,
            "total_cost_usd": float(exam.total_cost_usd) if exam.total_cost_usd is not None else None,
        }
