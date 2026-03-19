from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from models.exam import FeedbackSignalType
from schemas.exam import ErrorCategoryCount
from services.analytics.question_quality import question_error_categories
from services.document_service import DocumentService
from services.exam_service import ExamService
from services.feedback.store_service import filter_feedback_events as filter_feedback_store_events


READY_DOCUMENT_STATUSES = {"indexed", "processed", "structured"}
WARNING_SIGNAL_TYPES = {
    FeedbackSignalType.VERIFIER_WARNING,
    FeedbackSignalType.VERIFIER_FAILED,
}


def _normalized_document_status(document) -> str:
    status = getattr(document, "status", None)
    return str(status.value if hasattr(status, "value") else status or "").strip().lower()


def _event_target_count(event, fallback_question_count: int = 1) -> int:
    payload = event.payload_json or {}
    target_ids = [item for item in (payload.get("target_question_ids") or []) if str(item).strip()]
    target_slots = [item for item in (payload.get("target_slots") or []) if item is not None]
    target_count = len(target_ids) or len(target_slots)
    if target_count > 0:
        return target_count
    explicit_count = payload.get("target_question_count")
    try:
        if explicit_count is not None:
            return max(int(explicit_count), 0)
    except (TypeError, ValueError):
        pass
    return max(fallback_question_count, 0)


def build_quality_summary(documents: list, exams: list) -> dict:
    active_documents = [
        document
        for document in documents
        if _normalized_document_status(document) in READY_DOCUMENT_STATUSES
    ]

    total_questions = 0
    passed_questions = 0
    warned_questions = 0
    evidence_covered_questions = 0
    scope_violation_questions = 0
    total_regenerate_targets = 0
    total_human_edit_targets = 0
    top_categories: Counter[str] = Counter()
    recent_warnings: list = []
    last_updated_at: datetime | None = None

    for exam in exams:
        current_version = getattr(exam, "current_version", None)

        duplicate_slots = {
            int(member_slot)
            for group in (getattr(exam, "duplicate_groups_json", None) or [])
            if isinstance(group, dict)
            for member_slot in (group.get("member_slots") or [])[1:]
            if member_slot is not None
        }

        questions = list(getattr(current_version, "questions", []) or [])
        total_questions += len(questions)
        for question in questions:
            warnings = list(getattr(question, "warnings_json", None) or [])
            status = str(getattr(question, "verification_status", "") or "").strip().lower()
            evidence = list(getattr(question, "source_evidence_json", None) or [])
            if status == "passed":
                passed_questions += 1
            if warnings:
                warned_questions += 1
            if evidence:
                evidence_covered_questions += 1
            categories = question_error_categories(question, duplicate_slots=duplicate_slots)
            if "scope_leak" in categories:
                scope_violation_questions += 1
            top_categories.update(categories)

        for event in list(getattr(exam, "feedback_events", []) or []):
            if event.signal_type == FeedbackSignalType.REGENERATE_REQUESTED:
                total_regenerate_targets += _event_target_count(
                    event,
                    fallback_question_count=len(questions),
                )
            elif event.signal_type == FeedbackSignalType.HUMAN_EDIT:
                total_human_edit_targets += _event_target_count(event)
            if event.signal_type in WARNING_SIGNAL_TYPES:
                recent_warnings.append(event)
            event_time = getattr(event, "created_at", None)
            if event_time and (last_updated_at is None or event_time > last_updated_at):
                last_updated_at = event_time

        updated_at = getattr(exam, "updated_at", None) or getattr(exam, "created_at", None)
        if updated_at and (last_updated_at is None or updated_at > last_updated_at):
            last_updated_at = updated_at

    question_denominator = max(total_questions, 1)
    exam_denominator = max(len(exams), 1)

    recent_warnings.sort(key=lambda item: item.created_at, reverse=True)

    return {
        "documents_active": len(active_documents),
        "exams_generated": len(exams),
        "question_count": total_questions,
        "verifier_pass_rate": round(passed_questions / question_denominator, 4),
        "verifier_warning_rate": round(warned_questions / question_denominator, 4),
        "evidence_coverage_rate": round(evidence_covered_questions / question_denominator, 4),
        "scope_violation_rate": round(scope_violation_questions / question_denominator, 4),
        "avg_regenerate_count": round(total_regenerate_targets / question_denominator, 4),
        "avg_human_edit_count": round(total_human_edit_targets / question_denominator, 4),
        "version_churn": round(
            sum(max(int(getattr(getattr(exam, "current_version", None), "version_number", 1) or 1) - 1, 0) for exam in exams)
            / exam_denominator,
            4,
        ),
        "top_error_categories": [
            ErrorCategoryCount(category=category, count=count).model_dump()
            for category, count in top_categories.most_common(5)
        ],
        "recent_warnings": recent_warnings[:5],
        "last_updated_at": last_updated_at,
    }


def filter_feedback_events(
    events: list,
    *,
    exam_version_id: str | None = None,
    question_id: str | None = None,
    signal_type: str | None = None,
    review_status: str | None = None,
    actor_id: str | None = None,
    event_stage: str | None = None,
    error_category: str | None = None,
    linked_eval_sample_id: str | None = None,
    limit: int = 100,
) -> list:
    return filter_feedback_store_events(
        events,
        exam_version_id=exam_version_id,
        question_id=question_id,
        signal_type=signal_type,
        review_status=review_status,
        actor_id=actor_id,
        event_stage=event_stage,
        error_category=error_category,
        linked_eval_sample_id=linked_eval_sample_id,
        limit=limit,
    )


class QualitySummaryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_summary(self, user_id: str) -> dict:
        documents = await DocumentService(self.db).list_documents(user_id=user_id)
        exams = await ExamService(self.db).get_exams(user_id)
        return build_quality_summary(documents, exams)

    async def get_feedback_events(
        self,
        *,
        user_id: str,
        exam_id: str,
        exam_version_id: str | None = None,
        question_id: str | None = None,
        signal_type: str | None = None,
        review_status: str | None = None,
        actor_id: str | None = None,
        event_stage: str | None = None,
        error_category: str | None = None,
        linked_eval_sample_id: str | None = None,
        limit: int = 100,
    ) -> list:
        exam = await ExamService(self.db).get_exam(exam_id, user_id)
        if not exam:
            raise ValueError("Exam not found")
        return filter_feedback_events(
            list(getattr(exam, "feedback_events", []) or []),
            exam_version_id=exam_version_id,
            question_id=question_id,
            signal_type=signal_type,
            review_status=review_status,
            actor_id=actor_id,
            event_stage=event_stage,
            error_category=error_category,
            linked_eval_sample_id=linked_eval_sample_id,
            limit=limit,
        )
