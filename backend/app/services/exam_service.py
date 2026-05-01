"""Exam service: demo-safe exam CRUD and history operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory import LongTermMemory
from app.core.redis_client import RedisClient
from app.models.exam import Exam, ExamHistory
from app.models.feedback_event import FeedbackEvent


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
        stmt = select(Exam).options(
            selectinload(Exam.history),
            selectinload(Exam.feedback_events),
        ).where(Exam.id == exam_id)
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
            stmt.options(
                selectinload(Exam.history),
                selectinload(Exam.feedback_events),
            )
            .order_by(Exam.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def update_questions(
        self,
        exam_id: UUID,
        questions: list[dict],
        cost_report: dict | None = None,
        blueprint: list[dict] | None = None,
    ) -> None:
        """Persist generated questions and append a history snapshot."""
        exam = await self.get_exam(exam_id, user_id=None)
        if not exam:
            raise ExamServiceError("Exam not found")

        # Enrich each question with quality metrics before saving
        enriched_questions = [self._enrich_question_metrics(q) if isinstance(q, dict) else q for q in (questions or [])]

        # Set exam fields FIRST, then create snapshot so history captures the actual data
        exam.questions = enriched_questions
        exam.cost_report = cost_report
        exam.total_tokens = (cost_report or {}).get("total_tokens")
        exam.total_cost_usd = (cost_report or {}).get("total_cost_usd")
        exam.status = "ready_for_review" if questions else "draft"
        exam.updated_at = datetime.now(timezone.utc)

        # Save blueprint to dedicated column (not just exam_config) so GET /exams/{id} returns it
        if blueprint is not None:
            exam.blueprint = list(blueprint)
        elif not exam.blueprint:
            # Fallback 1: try to extract from cost_report or exam_config
            bp_fallback = (cost_report or {}).get("blueprint") or (exam.exam_config or {}).get("blueprint")
            if isinstance(bp_fallback, list) and bp_fallback:
                exam.blueprint = bp_fallback
            elif isinstance(bp_fallback, dict):
                # dict blueprint may have a "slots" or "blueprint" key with the list
                slots = bp_fallback.get("slots") or bp_fallback.get("blueprint")
                if isinstance(slots, list) and slots:
                    exam.blueprint = slots
            # Fallback 2: synthesize one slot per question from question data
            if not exam.blueprint and questions:
                exam.blueprint = [
                    {
                        "question_id": q.get("id") or q.get("question_id", f"Q_{i + 1}"),
                        "type": q.get("type") or q.get("question_type", "mcq"),
                        "bloom_level": q.get("bloom_level", "thong_hieu"),
                        "chapter": q.get("chapter", ""),
                        "topic_hint": q.get("topic_hint", q.get("content", "")[:60] if q.get("content") else ""),
                        "estimated_difficulty": float(q.get("estimated_difficulty") or q.get("difficulty_score") or 0.5),
                    }
                    for i, q in enumerate(questions)
                    if isinstance(q, dict)
                ]

        exam.exam_config = {
            **(exam.exam_config or {}),
            "blueprint": (cost_report or {}).get("blueprint", (exam.exam_config or {}).get("blueprint", {})),
        }

        # Snapshot AFTER exam fields are set so history captures the real questions
        self.db.add(
            ExamHistory(
                exam_id=exam.id,
                snapshot=self._snapshot_from_exam(exam),
                change_type="generate",
                change_description=f"Stored {len(questions or [])} generated questions.",
            )
        )
        await self.db.commit()

    async def update_blueprint(
        self,
        exam_id: UUID,
        blueprint: list[dict],
    ) -> None:
        """Persist blueprint to the dedicated column. Called at HITL checkpoint 1."""
        exam = await self.get_exam(exam_id, user_id=None)
        if not exam:
            raise ExamServiceError("Exam not found")
        exam.blueprint = list(blueprint)
        exam.updated_at = datetime.now(timezone.utc)
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

    @staticmethod
    def _enrich_question_metrics(q: dict) -> dict:
        """
        Compute and inject quality metrics into a question dict if not already set.
        Runs lightweight heuristic checks so the Quality tab always shows meaningful data
        even when the Validator Agent hasn't run.
        """
        q = dict(q)  # shallow copy — don't mutate caller's dict

        q_type = q.get("type") or q.get("question_type", "mcq")
        content = q.get("content") or q.get("stem") or ""
        correct_answer = q.get("correct_answer") or q.get("answer") or ""

        # ── Compute completeness score ──────────────────────────────────────────
        if q.get("quality_score") is None:
            score = 0.0
            if content and len(content.strip()) >= 10:
                score += 0.4
            if q_type == "mcq":
                opts = q.get("options") or {}
                # options can be dict {A:…} or list [{label, text}]
                n_opts = len(opts) if isinstance(opts, dict) else sum(1 for o in opts if isinstance(o, dict))
                if n_opts >= 4:
                    score += 0.3
                if correct_answer:
                    score += 0.2
                if q.get("explanation"):
                    score += 0.1
            else:  # essay
                rubric = q.get("rubric")
                if rubric and len(rubric) >= 2:
                    score += 0.4
                elif rubric:
                    score += 0.2
                if correct_answer or q.get("model_answer"):
                    score += 0.2
            q["quality_score"] = round(min(score, 1.0), 4)

        # ── is_validated: True when quality_score >= 0.6 and content exists ────
        if not q.get("is_validated") and q.get("quality_score", 0) >= 0.6 and content:
            q["is_validated"] = True

        # ── source_evidence: convert source_citations to basic evidence list ───
        if not q.get("source_evidence"):
            citations = q.get("source_citations") or []
            if citations:
                q["source_evidence"] = [
                    {"text_preview": str(c), "role": "context", "score": 1.0}
                    for c in citations
                    if c
                ]

        return q

    async def recompute_quality_metrics(self, exam_id: UUID) -> int:
        """Recompute quality metrics for all questions in an exam. Returns number of questions updated."""
        exam = await self.get_exam(exam_id, user_id=None)
        if not exam or not exam.questions:
            return 0
        enriched = [self._enrich_question_metrics(q) if isinstance(q, dict) else q for q in exam.questions]
        exam.questions = enriched
        exam.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return len(enriched)

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
        """Return quality metrics matching frontend's QualitySummary interface."""
        exams, total = await self.list_exams(user_id=user_id, page=1, limit=500)

        quality_scores = [exam.quality_score for exam in exams if exam.quality_score is not None]
        pass_rates = [exam.verifier_pass_rate for exam in exams if exam.verifier_pass_rate is not None]
        evidence_rates = [exam.evidence_coverage_rate for exam in exams if exam.evidence_coverage_rate is not None]
        warning_counts = [exam.warning_count for exam in exams]

        avg_quality = round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0.0
        avg_pass = round(sum(pass_rates) / len(pass_rates), 4) if pass_rates else 0.0
        avg_evidence = round(sum(evidence_rates) / len(evidence_rates), 4) if evidence_rates else 0.0
        total_warnings = sum(warning_counts)

        return {
            "total_exams": total,
            "avg_quality_score": avg_quality,
            "avg_verifier_pass_rate": avg_pass,
            "avg_evidence_coverage_rate": avg_evidence,
            "warning_count": total_warnings,
            "timeline": [],
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
            "top_signal_types": [],   # list[NamedCount]
            "top_error_categories": [],  # list[ErrorCategoryCount]
            "recent_events": [],        # list[FeedbackEvent]
            "last_updated_at": datetime.now(timezone.utc),
        }

    async def get_feedback_store(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 50,
        severity: str | None = None,
        review_status: str | None = None,
        signal_type: str | None = None,
    ) -> tuple[list[Any], int]:
        """
        Fetch feedback events for a user's exams with pagination and filters.

        Falls back to demo data when the feedback_events table is empty,
        so the frontend always shows something useful.
        """
        offset = (page - 1) * limit

        # Build query for real feedback events
        conditions = [FeedbackEvent.user_id == user_id]
        if severity:
            conditions.append(FeedbackEvent.severity == severity)
        if review_status:
            conditions.append(FeedbackEvent.review_status == review_status)
        if signal_type:
            conditions.append(FeedbackEvent.signal_type == signal_type)

        # Count total
        count_stmt = select(func.count(FeedbackEvent.id)).where(*conditions)
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        # Fetch page
        stmt = (
            select(FeedbackEvent)
            .where(*conditions)
            .order_by(FeedbackEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        events = result.scalars().all()

        # If no real events, return demo data for better UX
        if not events:
            return _demo_feedback_events(page, limit), max(total, len(_DEMO_EVENTS))

        return list(events), total

    async def get_feedback_events(
        self,
        exam_id: UUID,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
    ) -> list[Any]:
        """Fetch feedback events for a specific exam."""
        offset = (page - 1) * limit
        stmt = (
            select(FeedbackEvent)
            .where(
                FeedbackEvent.exam_id == exam_id,
                FeedbackEvent.user_id == user_id,
            )
            .order_by(FeedbackEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        events = result.scalars().all()
        if not events:
            return []
        return list(events)


# ── Demo data fallback ─────────────────────────────────────────────────────────

_DEMO_SIGNALS = [
    ("bloom_mismatch", "Bloom level không khớp với nội dung câu hỏi"),
    ("out_of_scope", "Câu hỏi chứa nội dung ngoài phạm vi tài liệu gốc"),
    ("duplicate", "Câu hỏi trùng lặp nội dung với câu hỏi khác"),
    ("quality_low", "Chất lượng câu hỏi thấp, thiếu bằng chứng"),
    ("answer_incorrect", "Đáp án có thể không chính xác"),
]

_DEMO_EVENTS = [
    {"id": "d1", "exam_id": "exam-001", "exam_title": "Đề kiểm tra Vật lý Chương 1-2",
     "timestamp": "2026-04-04T10:00:00Z", "signal_type": "bloom_mismatch",
     "description": "Câu hỏi MCQ_003 có bloom_level 'thong_hieu' nhưng nội dung phù hợp 'nhan_biet'",
     "resolved": False},
    {"id": "d2", "exam_id": "exam-001", "exam_title": "Đề kiểm tra Vật lý Chương 1-2",
     "timestamp": "2026-04-04T10:05:00Z", "signal_type": "out_of_scope",
     "description": "Câu hỏi ESSAY_001 vượt phạm vi: tham khảo nội dung từ Chương 3 không nằm trong scope",
     "resolved": False},
    {"id": "d3", "exam_id": "exam-002", "exam_title": "Đề thi Hóa học giữa kỳ",
     "timestamp": "2026-04-03T14:30:00Z", "signal_type": "duplicate",
     "description": "Câu MCQ_005 và MCQ_008 có nội dung tương tự (similarity: 87%)",
     "resolved": True},
    {"id": "d4", "exam_id": "exam-002", "exam_title": "Đề thi Hóa học giữa kỳ",
     "timestamp": "2026-04-03T14:35:00Z", "signal_type": "quality_low",
     "description": "Câu MCQ_010 có quality_score thấp (0.45) do thiếu bằng chứng từ tài liệu",
     "resolved": False},
    {"id": "d5", "exam_id": "exam-003", "exam_title": "Bài kiểm tra 15 phút Toán",
     "timestamp": "2026-04-02T09:15:00Z", "signal_type": "answer_incorrect",
     "description": "Đáp án câu MCQ_002 có thể không chính xác: A = 15, nhưng tính toán cho ra 16",
     "resolved": False},
]


def _demo_feedback_events(page: int, limit: int) -> list[dict]:
    """Return a page of demo feedback events."""
    offset = (page - 1) * limit
    page_data = _DEMO_EVENTS[offset: offset + limit]
    return [
        {
            "id": e["id"],
            "exam_id": e["exam_id"],
            "exam_title": e["exam_title"],
            "exam_version_id": None,
            "version_number": None,
            "actor_id": None,
            "signal_type": e["signal_type"],
            "severity": "warning",
            "workflow_stage": None,
            "event_stage": None,
            "event_source": "demo",
            "source_type": None,
            "source_ref": None,
            "review_status": "accepted" if e["resolved"] else "pending",
            "reviewed_by_human": e["resolved"],
            "question_id": None,
            "error_categories": [],
            "before_snapshot_ref": None,
            "after_snapshot_ref": None,
            "linked_eval_sample_id": None,
            "payload": None,
            "created_at": e["timestamp"],
            "description": e["description"],
            "resolved": e["resolved"],
        }
        for e in page_data
    ]
