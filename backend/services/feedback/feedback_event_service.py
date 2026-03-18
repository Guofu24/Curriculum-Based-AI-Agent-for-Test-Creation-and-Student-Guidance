from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from models.exam import ExamQuestion, FeedbackEvent, FeedbackSignalType


class FeedbackEventService:
    """Structured feedback/event logging for the active exam lifecycle."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def queue_event(
        self,
        *,
        exam_id: str,
        signal_type: FeedbackSignalType,
        severity: str = "info",
        actor_id: str | None = None,
        exam_version_id: str | None = None,
        question_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        self.db.add(
            FeedbackEvent(
                exam_id=exam_id,
                exam_version_id=exam_version_id,
                question_id=question_id,
                actor_id=actor_id,
                signal_type=signal_type,
                severity=severity,
                payload_json=payload or {},
            )
        )

    def queue_retrieval_summary(
        self,
        *,
        exam_id: str,
        exam_version_id: str,
        actor_id: str | None,
        payload: dict,
    ) -> None:
        self.queue_event(
            exam_id=exam_id,
            exam_version_id=exam_version_id,
            actor_id=actor_id,
            signal_type=FeedbackSignalType.RETRIEVAL_SUMMARY,
            severity="info",
            payload=payload,
        )

    def queue_verifier_events(
        self,
        *,
        exam_id: str,
        exam_version_id: str,
        actor_id: str | None,
        questions: Iterable[ExamQuestion],
    ) -> None:
        for question in questions:
            warnings = list(question.warnings_json or [])
            verification_status = str(question.verification_status or "").strip().lower()
            if verification_status == "failed":
                signal_type = FeedbackSignalType.VERIFIER_FAILED
                severity = "error"
            elif warnings:
                signal_type = FeedbackSignalType.VERIFIER_WARNING
                severity = "warning"
            else:
                continue

            self.queue_event(
                exam_id=exam_id,
                exam_version_id=exam_version_id,
                question_id=question.id,
                actor_id=actor_id,
                signal_type=signal_type,
                severity=severity,
                payload={
                    "question_number": question.question_number,
                    "blueprint_cell_key": question.blueprint_cell_key,
                    "verification_status": question.verification_status,
                    "warnings": warnings,
                    "is_human_edited": bool(question.is_human_edited),
                    "is_locked": bool(question.is_locked),
                },
            )

    def queue_edit_events(
        self,
        *,
        exam_id: str,
        exam_version_id: str,
        actor_id: str | None,
        edit_requests: list[dict],
        question_id_by_slot: dict[int, str],
    ) -> None:
        for edit in edit_requests:
            edit_type = str(edit.get("edit_type") or "regenerate").strip().lower()
            targeted_slots: list[int] = []
            for raw_id in edit.get("question_ids") or []:
                try:
                    targeted_slots.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
            range_start = edit.get("range_start")
            range_end = edit.get("range_end")
            if isinstance(range_start, int) and isinstance(range_end, int):
                low = min(range_start, range_end)
                high = max(range_start, range_end)
                targeted_slots.extend(slot for slot in range(low, high + 1) if slot > 0)
            targeted_slots = sorted(set(targeted_slots))

            payload = {
                "edit_type": edit_type,
                "target_slots": targeted_slots,
                "target_question_ids": [
                    question_id_by_slot[slot]
                    for slot in targeted_slots
                    if slot in question_id_by_slot
                ],
                "edit_prompt": str(edit.get("edit_prompt") or "").strip() or None,
            }

            if edit_type == "regenerate":
                signal_type = FeedbackSignalType.REGENERATE_REQUESTED
            else:
                signal_type = FeedbackSignalType.HUMAN_EDIT
                if edit.get("new_content") is not None:
                    payload["new_content"] = edit.get("new_content")
                if edit.get("new_correct_answer") is not None:
                    payload["new_correct_answer"] = edit.get("new_correct_answer")
                if edit.get("new_bloom_level") is not None:
                    payload["new_bloom_level"] = edit.get("new_bloom_level")
                if edit.get("new_options") is not None:
                    payload["new_options"] = edit.get("new_options")

            question_id = None
            if len(targeted_slots) == 1:
                question_id = question_id_by_slot.get(targeted_slots[0])

            self.queue_event(
                exam_id=exam_id,
                exam_version_id=exam_version_id,
                question_id=question_id,
                actor_id=actor_id,
                signal_type=signal_type,
                severity="info",
                payload=payload,
            )

    def queue_publish_event(
        self,
        *,
        exam_id: str,
        exam_version_id: str | None,
        actor_id: str | None,
        payload: dict,
    ) -> None:
        self.queue_event(
            exam_id=exam_id,
            exam_version_id=exam_version_id,
            actor_id=actor_id,
            signal_type=FeedbackSignalType.EXAM_PUBLISHED,
            severity="info",
            payload=payload,
        )
