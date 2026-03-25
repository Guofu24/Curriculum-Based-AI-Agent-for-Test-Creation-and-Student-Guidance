from __future__ import annotations

from app.models.exam import FeedbackSignalType
from app.schemas.exam import (
    EditOperationResponse,
    ExamListResponse,
    ExamResponse,
    ExamVersionResponse,
    FeedbackEventResponse,
    MCQOption,
    QuestionResponse,
)
from app.services.analytics.question_quality import question_error_categories


def enum_value(value):
    return value.value if hasattr(value, "value") else value


def parse_target_slots(raw_target: str | None) -> list[int]:
    slots: list[int] = []
    for item in str(raw_target or "").split(","):
        try:
            slot = int(item)
        except (TypeError, ValueError):
            continue
        if slot > 0:
            slots.append(slot)
    return sorted(set(slots))


def format_question(question) -> QuestionResponse:
    options = None
    if question.options and isinstance(question.options, list):
        options = [
            MCQOption(label=str(option.get("label", "")), text=str(option.get("text", "")))
            for option in question.options
            if isinstance(option, dict)
        ]

    return QuestionResponse(
        id=question.id,
        question_number=question.question_number,
        blueprint_cell_key=question.blueprint_cell_key,
        question_type=enum_value(question.question_type),
        bloom_level=enum_value(question.bloom_level),
        difficulty_score=question.difficulty_score,
        content=question.content,
        options=options,
        correct_answer=question.correct_answer,
        rubric=question.rubric_json,
        explanation=question.explanation,
        source_citations=question.source_chunks,
        source_evidence=question.source_evidence_json,
        scope_tags=question.scope_tags_json or [],
        warnings=question.warnings_json or [],
        verification_status=question.verification_status,
        is_human_edited=bool(question.is_human_edited),
        is_locked=bool(question.is_locked),
        is_validated=bool(question.is_validated),
        quality_score_detail=question.quality_score_json,
        grounding_report_detail=question.grounding_report_json,
        error_categories=question_error_categories(question),
    )


def format_feedback_event(event) -> dict:
    version_number = None
    exam_title = None
    event_dict = getattr(event, "__dict__", {})
    exam_version = event_dict.get("exam_version")
    if exam_version is not None:
        version_number = getattr(exam_version, "version_number", None)
    exam = event_dict.get("exam")
    if exam is not None:
        exam_title = getattr(exam, "title", None)

    return FeedbackEventResponse(
        id=event.id,
        exam_id=event.exam_id,
        exam_title=exam_title,
        exam_version_id=event.exam_version_id,
        version_number=version_number,
        actor_id=event.actor_id,
        signal_type=enum_value(event.signal_type),
        severity=event.severity,
        workflow_stage=event.workflow_stage,
        event_stage=getattr(event, "event_stage", None),
        event_source=event.event_source,
        source_type=getattr(event, "source_type", None),
        source_ref=getattr(event, "source_ref", None),
        review_status=event.review_status,
        reviewed_by_human=bool(event.reviewed_by_human),
        question_id=event.question_id,
        error_categories=list(getattr(event, "error_categories_json", None) or []),
        before_snapshot_ref=getattr(event, "before_snapshot_ref", None),
        after_snapshot_ref=getattr(event, "after_snapshot_ref", None),
        linked_eval_sample_id=getattr(event, "linked_eval_sample_id", None),
        payload=event.payload_json,
        created_at=event.created_at,
    ).model_dump()


def format_version(version) -> dict:
    questions = sorted(version.questions or [], key=lambda question: question.question_number)
    operations = sorted(version.edit_operations or [], key=lambda operation: operation.created_at)
    feedback_events = sorted(version.feedback_events or [], key=lambda event: event.created_at)
    return ExamVersionResponse(
        id=version.id,
        version_number=version.version_number,
        status=version.status,
        created_by=version.created_by,
        parent_version_id=version.parent_version_id,
        change_summary=version.change_summary,
        created_at=version.created_at,
        questions=[format_question(question) for question in questions],
        edit_operations=[
            EditOperationResponse(
                id=operation.id,
                edit_type=operation.edit_type,
                target_question_id=operation.target_question_id,
                target_slots=parse_target_slots(operation.target_question_id),
                prompt_used=operation.prompt_used,
                created_at=operation.created_at,
            )
            for operation in operations
        ],
        feedback_events=[format_feedback_event(event) for event in feedback_events],
    ).model_dump()


def get_active_version(exam):
    if getattr(exam, "current_version", None):
        return exam.current_version
    versions = list(getattr(exam, "versions", []) or [])
    if not versions:
        return None
    return max(versions, key=lambda version: version.version_number)


def _event_target_count(event, signal_type: FeedbackSignalType) -> int:
    payload = event.payload_json or {}
    target_ids = [item for item in (payload.get("target_question_ids") or []) if str(item).strip()]
    target_slots = [item for item in (payload.get("target_slots") or []) if item is not None]
    target_count = len(target_ids) or len(target_slots)
    if target_count:
        return target_count
    try:
        explicit_count = int(payload.get("target_question_count") or 0)
    except (TypeError, ValueError):
        explicit_count = 0
    if explicit_count:
        return explicit_count
    return 1 if signal_type in {FeedbackSignalType.REGENERATE_REQUESTED, FeedbackSignalType.HUMAN_EDIT} else 0


def format_exam_list(exam) -> ExamListResponse:
    current_version = get_active_version(exam)
    questions = list(getattr(current_version, "questions", []) or [])
    question_count = max(len(questions), 1)
    passed_questions = sum(
        1
        for question in questions
        if str(question.verification_status or "").strip().lower() == "passed"
    )
    evidence_covered = sum(1 for question in questions if question.source_evidence_json)
    warning_count = sum(len(question.warnings_json or []) for question in questions)
    feedback_events = list(getattr(exam, "feedback_events", []) or [])

    regenerate_count = sum(
        _event_target_count(event, FeedbackSignalType.REGENERATE_REQUESTED)
        for event in feedback_events
        if event.signal_type == FeedbackSignalType.REGENERATE_REQUESTED
    )
    human_edit_count = sum(
        _event_target_count(event, FeedbackSignalType.HUMAN_EDIT)
        for event in feedback_events
        if event.signal_type == FeedbackSignalType.HUMAN_EDIT
    )

    return ExamListResponse(
        id=exam.id,
        title=exam.title,
        document_id=exam.textbook_id,
        course_id=exam.course_id,
        exam_type=enum_value(exam.exam_type),
        difficulty=enum_value(exam.difficulty),
        status=enum_value(exam.status),
        chapters=exam.chapters or [],
        total_questions=exam.total_questions,
        strict_scope_flag=bool(exam.strict_scope_flag),
        quality_score=exam.quality_score,
        current_version_number=getattr(current_version, "version_number", None),
        version_count=int(getattr(current_version, "version_number", 0) or 0),
        verifier_pass_rate=round(passed_questions / question_count, 4) if questions else None,
        evidence_coverage_rate=round(evidence_covered / question_count, 4) if questions else None,
        warning_count=warning_count,
        regenerate_count=regenerate_count,
        human_edit_count=human_edit_count,
        feedback_event_count=len(feedback_events),
        created_at=exam.created_at,
        updated_at=exam.updated_at,
    )


def format_exam(exam) -> ExamResponse:
    active_version = get_active_version(exam)
    questions = sorted(
        (active_version.questions if active_version else []) or [],
        key=lambda question: question.question_number,
    )
    versions = sorted(list(exam.versions or []), key=lambda version: version.version_number)
    return ExamResponse(
        id=exam.id,
        title=exam.title,
        document_id=exam.textbook_id,
        course_id=exam.course_id,
        exam_type=enum_value(exam.exam_type),
        difficulty=enum_value(exam.difficulty),
        status=enum_value(exam.status),
        chapters=exam.chapters or [],
        variant_number=exam.variant_number,
        total_questions=exam.total_questions,
        instructions=exam.instructions,
        output_language=exam.output_language,
        strict_scope_flag=bool(exam.strict_scope_flag),
        quality_score=exam.quality_score,
        created_at=exam.created_at,
        updated_at=exam.updated_at,
        published_at=exam.published_at,
        questions=[format_question(question) for question in questions],
        exam_spec=exam.exam_spec_json,
        blueprint=exam.blueprint_json,
        selected_scope=exam.selected_scope_json,
        quality_scores=exam.quality_scores_json,
        grounding_reports=exam.grounding_reports_json,
        duplicate_groups=exam.duplicate_groups_json,
        provider_logs=exam.provider_logs_json,
        edit_impact_level=exam.edit_impact_level,
        edit_history=exam.edit_history_json,
        feedback_events=[
            format_feedback_event(event)
            for event in sorted(list(exam.feedback_events or []), key=lambda item: item.created_at)
        ],
        current_version=format_version(active_version) if active_version else None,
        versions=[format_version(version) for version in versions],
    )

