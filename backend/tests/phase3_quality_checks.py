"""Phase 3 quality checks for eval data, feedback metadata, and summary helpers.

Run from `backend/`:
    python tests/phase3_quality_checks.py
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evals.phase3_eval import build_error_analysis, build_phase3_report, load_eval_samples
from app.models.exam import ExamQuestion, FeedbackSignalType
from app.services.analytics.question_quality import question_error_categories
from app.services.analytics.quality_summary_service import build_quality_summary, filter_feedback_events
from app.services.feedback.feedback_event_service import FeedbackEventService


class _FakeDb:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, item: object) -> None:
        self.items.append(item)


def check_eval_dataset_splits() -> None:
    dev_samples = load_eval_samples(split="dev")
    held_out_samples = load_eval_samples(split="held_out")
    assert dev_samples
    assert held_out_samples
    assert all(sample["split"] == "dev" for sample in dev_samples)
    assert all(sample["split"] == "held_out" for sample in held_out_samples)


def check_phase3_report_metrics() -> None:
    report = build_phase3_report(split="all")
    metrics = report["metrics"]
    assert metrics["sample_count"] >= 5
    assert metrics["question_count"] >= 10
    assert metrics["retrieval_hit_quality"] > 0
    assert metrics["top_error_categories"]


def check_error_analysis_report() -> None:
    report = build_error_analysis(split="all")
    assert report["categories"]
    assert report["categories"][0]["samples"]


def check_feedback_event_service_adds_phase3_metadata() -> None:
    fake_db = _FakeDb()
    service = FeedbackEventService(fake_db)
    question = ExamQuestion(
        id="question-1",
        exam_id="exam-1",
        exam_version_id="version-1",
        question_number=1,
        question_type="mcq",
        bloom_level="remember",
        difficulty_score=0.2,
        content="Noi dung",
        correct_answer="E",
        options=[{"label": "A", "text": "Van toc"}],
        source_evidence_json=[],
        warnings_json=["Missing evidence"],
        verification_status="failed",
        is_human_edited=True,
    )

    service.queue_retrieval_summary(
        exam_id="exam-1",
        exam_version_id="version-1",
        actor_id="user-1",
        payload={"slots_requested": 1},
    )
    service.queue_verifier_events(
        exam_id="exam-1",
        exam_version_id="version-1",
        actor_id="user-1",
        questions=[question],
    )
    service.queue_edit_events(
        exam_id="exam-1",
        exam_version_id="version-1",
        parent_version_id="version-0",
        actor_id="user-1",
        edit_requests=[
            {"edit_type": "regenerate", "question_ids": ["1"]},
            {"edit_type": "delete", "question_ids": ["1"]},
        ],
        question_id_by_slot={1: "question-1"},
    )
    service.queue_publish_event(
        exam_id="exam-1",
        exam_version_id="version-1",
        actor_id="user-1",
        payload={"question_count": 1},
    )

    assert {item.workflow_stage for item in fake_db.items} >= {"retrieval", "verification", "review", "publish"}
    assert any(item.review_status == "accepted" for item in fake_db.items)
    assert any(item.review_status == "rejected" for item in fake_db.items)
    assert any(item.reviewed_by_human for item in fake_db.items)


def check_question_error_categories() -> None:
    question = SimpleNamespace(
        question_number=2,
        warnings_json=[
            "Question evidence is outside the selected section scope",
            "Distractor(s) ['B'] may be more supported than correct answer",
        ],
        source_evidence_json=[],
        options=[{"label": "A", "text": "..."}, {"label": "B", "text": "..."}],
        correct_answer="E",
        grounding_report_json={"verbatim_ratio": 0.75},
    )
    categories = question_error_categories(question, duplicate_slots={2})
    assert set(categories) >= {
        "scope_leak",
        "weak_evidence",
        "wrong_answer_key",
        "ambiguous_options",
        "duplicate_question",
        "verbatim_copy",
    }


def check_quality_summary_and_feedback_filtering() -> None:
    question = SimpleNamespace(
        warnings_json=["Need review"],
        verification_status="failed",
        source_evidence_json=[],
        question_number=1,
        options=[{"label": "A", "text": "..."}, {"label": "B", "text": "..."}, {"label": "C", "text": "..."}, {"label": "D", "text": "..."}],
        correct_answer="A",
        grounding_report_json={},
    )
    warning_event = SimpleNamespace(
        id="event-1",
        exam_id="exam-1",
        exam_version_id="version-2",
        question_id="question-1",
        actor_id="system",
        signal_type=FeedbackSignalType.VERIFIER_WARNING,
        severity="warning",
        workflow_stage="verification",
        event_source="system",
        review_status="needs_review",
        reviewed_by_human=False,
        payload_json={"target_question_ids": ["question-1"]},
        created_at=datetime.now(UTC),
    )
    regenerate_event = SimpleNamespace(
        id="event-2",
        exam_id="exam-1",
        exam_version_id="version-2",
        question_id=None,
        actor_id="user-1",
        signal_type=FeedbackSignalType.REGENERATE_REQUESTED,
        severity="info",
        workflow_stage="review",
        event_source="human",
        review_status="reviewed_by_human",
        reviewed_by_human=True,
        payload_json={"target_question_ids": ["question-1"], "target_question_count": 1},
        created_at=datetime.now(UTC),
    )
    summary = build_quality_summary(
        documents=[SimpleNamespace(status="indexed")],
        exams=[
            SimpleNamespace(
                current_version=SimpleNamespace(version_number=2, questions=[question]),
                duplicate_groups_json=[],
                feedback_events=[warning_event, regenerate_event],
                updated_at=None,
                created_at=None,
            )
        ],
    )
    assert summary["documents_active"] == 1
    assert summary["exams_generated"] == 1
    assert summary["avg_regenerate_count"] == 1.0
    assert summary["top_error_categories"]

    filtered = filter_feedback_events(
        [warning_event, regenerate_event],
        question_id="question-1",
        signal_type="verifier_warning",
    )
    assert len(filtered) == 1
    assert filtered[0].id == "event-1"


if __name__ == "__main__":
    check_eval_dataset_splits()
    check_phase3_report_metrics()
    check_error_analysis_report()
    check_feedback_event_service_adds_phase3_metadata()
    check_question_error_categories()
    check_quality_summary_and_feedback_filtering()
    print("Phase 3 quality checks passed")
