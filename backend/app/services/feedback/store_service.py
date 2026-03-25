from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.exams.service import ExamService


def event_error_categories(event) -> list[str]:
    raw = getattr(event, "error_categories_json", None)
    if not raw:
        payload = getattr(event, "payload_json", None) or {}
        raw = payload.get("error_categories") or []
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


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
    normalized_signal_type = str(signal_type or "").strip().lower() or None
    normalized_review_status = str(review_status or "").strip().lower() or None
    normalized_event_stage = str(event_stage or "").strip().lower() or None
    normalized_error_category = str(error_category or "").strip().lower() or None
    normalized_actor_id = str(actor_id or "").strip() or None
    normalized_eval_sample_id = str(linked_eval_sample_id or "").strip() or None
    filtered: list = []

    def _sort_key(item) -> datetime:
        return getattr(item, "created_at", None) or datetime.min

    for event in sorted(events, key=_sort_key, reverse=True):
        signal_value = str(
            event.signal_type.value if hasattr(event.signal_type, "value") else event.signal_type
        ).lower()
        stage_value = str(
            getattr(event, "event_stage", None)
            or getattr(event, "workflow_stage", None)
            or ""
        ).strip().lower()
        payload = getattr(event, "payload_json", None) or {}
        target_ids = {
            str(item)
            for item in (payload.get("target_question_ids") or [])
            if str(item).strip()
        }

        if exam_version_id and event.exam_version_id != exam_version_id:
            continue
        if question_id and event.question_id != question_id and question_id not in target_ids:
            continue
        if normalized_signal_type and signal_value != normalized_signal_type:
            continue
        if normalized_review_status and str(event.review_status or "").strip().lower() != normalized_review_status:
            continue
        if normalized_actor_id and str(event.actor_id or "").strip() != normalized_actor_id:
            continue
        if normalized_event_stage and stage_value != normalized_event_stage:
            continue
        if normalized_error_category and normalized_error_category not in {
            item.lower()
            for item in event_error_categories(event)
        }:
            continue
        if normalized_eval_sample_id and str(getattr(event, "linked_eval_sample_id", "") or "").strip() != normalized_eval_sample_id:
            continue
        filtered.append(event)
        if len(filtered) >= limit:
            break

    return filtered


def build_feedback_store_summary(events: list) -> dict:
    reviewed_by_human_count = 0
    accepted_count = 0
    rejected_count = 0
    corrected_count = 0
    linked_eval_count = 0
    top_signal_types: Counter[str] = Counter()
    top_error_categories: Counter[str] = Counter()
    last_updated_at: datetime | None = None

    for event in events:
        if bool(getattr(event, "reviewed_by_human", False)):
            reviewed_by_human_count += 1
        review_status = str(getattr(event, "review_status", "") or "").strip().lower()
        if review_status == "accepted":
            accepted_count += 1
        elif review_status == "rejected":
            rejected_count += 1
        elif review_status == "corrected":
            corrected_count += 1
        if getattr(event, "linked_eval_sample_id", None):
            linked_eval_count += 1
        signal_name = str(
            event.signal_type.value if hasattr(event.signal_type, "value") else event.signal_type
        ).strip()
        if signal_name:
            top_signal_types.update([signal_name])
        top_error_categories.update(event_error_categories(event))
        created_at = getattr(event, "created_at", None)
        if created_at and (last_updated_at is None or created_at > last_updated_at):
            last_updated_at = created_at

    return {
        "total_events": len(events),
        "reviewed_by_human_count": reviewed_by_human_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "corrected_count": corrected_count,
        "linked_eval_count": linked_eval_count,
        "top_signal_types": [
            {"name": name, "count": count}
            for name, count in top_signal_types.most_common(6)
        ],
        "top_error_categories": [
            {"category": name, "count": count}
            for name, count in top_error_categories.most_common(6)
        ],
        "recent_events": sorted(
            events,
            key=lambda item: getattr(item, "created_at", None) or datetime.min,
            reverse=True,
        )[:8],
        "last_updated_at": last_updated_at,
    }


class FeedbackStoreService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_exam_events(
        self,
        *,
        user_id: str,
        exam_id: str | None = None,
    ) -> list:
        if exam_id:
            exam = await ExamService(self.db).get_exam(exam_id, user_id)
            if not exam:
                raise ValueError("Exam not found")
            return list(getattr(exam, "feedback_events", []) or [])

        exams = await ExamService(self.db).get_exams(user_id)
        events: list = []
        for exam in exams:
            events.extend(list(getattr(exam, "feedback_events", []) or []))
        return events

    async def list_events(
        self,
        *,
        user_id: str,
        exam_id: str | None = None,
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
        events = await self._load_exam_events(user_id=user_id, exam_id=exam_id)
        return filter_feedback_events(
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

    async def build_summary(
        self,
        *,
        user_id: str,
        exam_id: str | None = None,
    ) -> dict:
        events = await self._load_exam_events(user_id=user_id, exam_id=exam_id)
        return build_feedback_store_summary(events)

