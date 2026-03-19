from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.course import CourseMembership
from models.exam import Exam, ExamSpecRecord, ExamVersion
from models.playbook import ReflectionCandidate
from services.analytics.question_quality import question_error_categories
from services.playbook.store_service import PlaybookService


def build_warmup_export(exams: list, bullets: list, candidates: list) -> dict:
    exam_cases: list[dict] = []
    question_cases: list[dict] = []
    feedback_cases: list[dict] = []

    for exam in exams:
        versions = sorted(list(getattr(exam, "versions", []) or []), key=lambda item: item.version_number)
        current_version = getattr(exam, "current_version", None)
        feedback_events = list(getattr(exam, "feedback_events", []) or [])

        exam_cases.append(
            {
                "exam_id": exam.id,
                "title": exam.title,
                "status": str(getattr(exam.status, "value", exam.status)),
                "document_id": exam.textbook_id,
                "current_version_id": getattr(current_version, "id", None),
                "version_count": len(versions),
                "published_at": getattr(exam, "published_at", None).isoformat() if getattr(exam, "published_at", None) else None,
                "strict_scope_flag": bool(getattr(exam, "strict_scope_flag", False)),
                "selected_scope": list(getattr(exam, "selected_scope_json", []) or []),
                "feedback_event_count": len(feedback_events),
            }
        )

        for version in versions:
            questions = list(getattr(version, "questions", []) or [])
            version_feedback = list(getattr(version, "feedback_events", []) or [])
            for question in questions:
                question_cases.append(
                    {
                        "exam_id": exam.id,
                        "exam_version_id": version.id,
                        "question_id": question.id,
                        "question_number": question.question_number,
                        "version_number": version.version_number,
                        "verification_status": question.verification_status,
                        "warnings": list(question.warnings_json or []),
                        "source_evidence": list(question.source_evidence_json or []),
                        "is_human_edited": bool(question.is_human_edited),
                        "error_categories": question_error_categories(question),
                    }
                )
            for event in version_feedback:
                feedback_cases.append(
                    {
                        "event_id": event.id,
                        "exam_id": exam.id,
                        "exam_version_id": event.exam_version_id,
                        "question_id": event.question_id,
                        "signal_type": str(getattr(event.signal_type, "value", event.signal_type)),
                        "review_status": event.review_status,
                        "event_stage": getattr(event, "event_stage", None) or getattr(event, "workflow_stage", None),
                        "source_type": getattr(event, "source_type", None),
                        "error_categories": list(getattr(event, "error_categories_json", None) or []),
                        "linked_eval_sample_id": getattr(event, "linked_eval_sample_id", None),
                        "created_at": event.created_at.isoformat() if getattr(event, "created_at", None) else None,
                    }
                )

    return {
        "meta": {
            "exported_at": datetime.utcnow().isoformat(),
            "exam_case_count": len(exam_cases),
            "question_case_count": len(question_cases),
            "feedback_case_count": len(feedback_cases),
            "playbook_seed_count": len(bullets),
            "reflection_candidate_count": len(candidates),
        },
        "exam_cases": exam_cases,
        "question_cases": question_cases,
        "feedback_cases": feedback_cases,
        "playbook_seed": [
            {
                "bullet_id": bullet.id,
                "status": bullet.status.value,
                "bullet_type": bullet.bullet_type.value,
                "title": bullet.title,
                "content": bullet.content,
                "scope": dict(bullet.scope_json or {}),
                "tags": list(bullet.tags_json or []),
                "confidence": bullet.confidence,
            }
            for bullet in bullets
        ],
        "reflection_candidates": [
            {
                "candidate_id": item.id,
                "status": item.status.value,
                "category": item.category,
                "proposed_title": item.proposed_title,
                "confidence": item.confidence,
            }
            for item in candidates
        ],
    }


class WarmupExportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _exam_options(self):
        return (
            selectinload(Exam.exam_spec_record).selectinload(ExamSpecRecord.scopes),
            selectinload(Exam.exam_spec_record).selectinload(ExamSpecRecord.blueprint_cells),
            selectinload(Exam.feedback_events),
            selectinload(Exam.current_version).selectinload(ExamVersion.questions),
            selectinload(Exam.current_version).selectinload(ExamVersion.edit_operations),
            selectinload(Exam.current_version).selectinload(ExamVersion.feedback_events),
            selectinload(Exam.versions).selectinload(ExamVersion.questions),
            selectinload(Exam.versions).selectinload(ExamVersion.edit_operations),
            selectinload(Exam.versions).selectinload(ExamVersion.feedback_events),
        )

    async def _load_user_exams(self, user_id: str) -> list[Exam]:
        membership_subquery = (
            select(CourseMembership.course_id)
            .where(CourseMembership.user_id == user_id)
        )
        result = await self.db.execute(
            select(Exam)
            .where(
                or_(
                    Exam.owner_id == user_id,
                    Exam.course_id.in_(membership_subquery),
                )
            )
            .options(*self._exam_options())
            .order_by(Exam.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def _load_all_exams(self) -> list[Exam]:
        result = await self.db.execute(
            select(Exam)
            .options(*self._exam_options())
            .order_by(Exam.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def build_user_export(self, *, user_id: str) -> dict:
        exams = await self._load_user_exams(user_id)
        bullets = await PlaybookService(self.db).list_bullets(limit=200)
        candidate_result = await self.db.execute(
            select(ReflectionCandidate).order_by(ReflectionCandidate.updated_at.desc())
        )
        candidates = list(candidate_result.scalars().all())
        return build_warmup_export(exams, bullets, candidates)

    async def build_global_export(self) -> dict:
        exams = await self._load_all_exams()
        bullets = await PlaybookService(self.db).list_bullets(limit=500)
        candidate_result = await self.db.execute(
            select(ReflectionCandidate).order_by(ReflectionCandidate.updated_at.desc())
        )
        candidates = list(candidate_result.scalars().all())
        return build_warmup_export(exams, bullets, candidates)
