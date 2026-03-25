"""Phase 4 ACE foundation checks.

Run from `backend/`:
    python tests/phase4_foundation_checks.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.main import app
from app.models.exam import FeedbackSignalType
from app.models.playbook import PlaybookBulletStatus, PlaybookBulletType
from app.services.feedback.feedback_event_service import FeedbackEventService
from app.services.feedback.store_service import (
    build_feedback_store_summary,
    filter_feedback_events,
)
from app.services.playbook.reflection_service import ReflectionCandidateService
from app.services.playbook.retrieval_service import PlaybookRetrievalService
from app.services.playbook.warmup_service import build_warmup_export


class _FakeDb:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, item: object) -> None:
        self.items.append(item)


class _FakeAsyncResult:
    def __init__(self, *, one=None, all_items=None) -> None:
        self._one = one
        self._all_items = list(all_items or [])

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._all_items))


class _FakeAsyncDb:
    def __init__(self) -> None:
        self.items: list[object] = []

    async def execute(self, query):
        _ = query
        return _FakeAsyncResult(one=None, all_items=self.items)

    def add(self, item: object) -> None:
        self.items.append(item)

    async def flush(self) -> None:
        return None


async def check_reflection_candidate_generation() -> None:
    fake_db = _FakeAsyncDb()
    original = ReflectionCandidateService.generate_candidates.__globals__["FeedbackStoreService"].list_events

    async def _fake_list_events(self, *, user_id: str, **kwargs):
        _ = self, user_id, kwargs
        return [
            SimpleNamespace(
                id="event-1",
                error_categories_json=["weak_evidence", "scope_leak"],
                payload_json={},
            )
        ]

    ReflectionCandidateService.generate_candidates.__globals__["FeedbackStoreService"].list_events = _fake_list_events
    try:
        candidates = await ReflectionCandidateService(fake_db).generate_candidates(user_id="user-1")
    finally:
        ReflectionCandidateService.generate_candidates.__globals__["FeedbackStoreService"].list_events = original

    categories = {item.category for item in candidates}
    assert "weak_evidence" in categories
    assert "scope_leak" in categories
    assert fake_db.items


async def check_playbook_retrieval_modes() -> None:
    bullet = SimpleNamespace(
        id="bullet-1",
        status=PlaybookBulletStatus.APPROVED,
        subject="physics",
        language="vi",
        question_type="mcq_single_answer",
        scope_json={"stages": ["generation"], "error_categories": ["weak_evidence"]},
        bullet_type=SimpleNamespace(value=PlaybookBulletType.GENERATION_HEURISTIC.value),
        confidence=0.9,
        tags_json=["weak_evidence"],
        title="Use evidence-backed explanations",
        created_at=datetime.now(UTC),
    )

    service = PlaybookRetrievalService(db=None)

    class _Store:
        async def list_bullets(self, **kwargs):
            _ = kwargs
            return [bullet]

    service.store = _Store()
    old_mode = settings.PLAYBOOK_RETRIEVAL_MODE
    old_limit = settings.PLAYBOOK_RETRIEVAL_LIMIT
    settings.PLAYBOOK_RETRIEVAL_LIMIT = 2

    try:
        settings.PLAYBOOK_RETRIEVAL_MODE = "shadow"
        shadow = await service.retrieve(stage="generation", error_categories=["weak_evidence"])
        assert len(shadow.matched_bullets) == 1
        assert len(shadow.attached_bullets) == 0
        shadow_payload = shadow.as_event_payload()
        assert shadow_payload["retrieval_mode"] == "shadow"
        assert shadow_payload["would_attach_count"] == 1
        assert len(shadow_payload["would_attach_bullets"]) == 1
        assert len(shadow_payload["attached_bullets"]) == 0

        settings.PLAYBOOK_RETRIEVAL_MODE = "limited"
        limited = await service.retrieve(stage="generation", error_categories=["weak_evidence"])
        assert len(limited.matched_bullets) == 1
        assert len(limited.attached_bullets) == 1
    finally:
        settings.PLAYBOOK_RETRIEVAL_MODE = old_mode
        settings.PLAYBOOK_RETRIEVAL_LIMIT = old_limit


def check_feedback_store_filters_and_summary() -> None:
    now = datetime.now(UTC)
    event_warning = SimpleNamespace(
        id="event-1",
        exam_id="exam-1",
        exam_version_id="version-2",
        question_id="question-1",
        actor_id="user-1",
        signal_type=FeedbackSignalType.VERIFIER_WARNING,
        severity="warning",
        workflow_stage="verification",
        event_stage="verification",
        event_source="system",
        source_type="runtime",
        source_ref="question:question-1",
        review_status="needs_review",
        reviewed_by_human=False,
        error_categories_json=["weak_evidence"],
        before_snapshot_ref=None,
        after_snapshot_ref=None,
        linked_eval_sample_id="held-out-1",
        payload_json={"target_question_ids": ["question-1"]},
        created_at=now,
    )
    event_shadow = SimpleNamespace(
        id="event-2",
        exam_id="exam-1",
        exam_version_id="version-2",
        question_id=None,
        actor_id="user-1",
        signal_type=FeedbackSignalType.PLAYBOOK_SHADOW,
        severity="info",
        workflow_stage="review",
        event_stage="review",
        event_source="system",
        source_type="playbook",
        source_ref="review:shadow",
        review_status="logged",
        reviewed_by_human=False,
        error_categories_json=[],
        before_snapshot_ref="exam_version:version-1",
        after_snapshot_ref="exam_version:version-2",
        linked_eval_sample_id=None,
        payload_json={},
        created_at=now,
    )
    event_edit = SimpleNamespace(
        id="event-3",
        exam_id="exam-1",
        exam_version_id="version-2",
        question_id="question-1",
        actor_id="user-1",
        signal_type=FeedbackSignalType.HUMAN_EDIT,
        severity="info",
        workflow_stage="review",
        event_stage="review",
        event_source="human",
        source_type="human_review",
        source_ref="edit:edit_text",
        review_status="corrected",
        reviewed_by_human=True,
        error_categories_json=["weak_evidence"],
        before_snapshot_ref="exam_version:version-1",
        after_snapshot_ref="exam_version:version-2",
        linked_eval_sample_id=None,
        payload_json={"target_question_ids": ["question-1"]},
        created_at=now,
    )

    filtered = filter_feedback_events(
        [event_warning, event_shadow, event_edit],
        question_id="question-1",
        event_stage="review",
        review_status="corrected",
    )
    assert len(filtered) == 1
    assert filtered[0].id == "event-3"

    summary = build_feedback_store_summary([event_warning, event_shadow, event_edit])
    assert summary["total_events"] == 3
    assert summary["reviewed_by_human_count"] == 1
    assert summary["linked_eval_count"] == 1
    assert summary["top_error_categories"][0]["category"] == "weak_evidence"


def check_warmup_export_structure() -> None:
    question = SimpleNamespace(
        id="question-1",
        question_number=1,
        verification_status="failed",
        warnings_json=["Need more evidence"],
        source_evidence_json=[{"chunk_id": "chunk-1"}],
        is_human_edited=True,
        options=[{"label": "A", "text": "..."}, {"label": "B", "text": "..."}, {"label": "C", "text": "..."}, {"label": "D", "text": "..."}],
        correct_answer="A",
        grounding_report_json={},
    )
    feedback_event = SimpleNamespace(
        id="event-1",
        exam_version_id="version-1",
        question_id="question-1",
        signal_type=FeedbackSignalType.VERIFIER_WARNING,
        review_status="needs_review",
        event_stage="verification",
        workflow_stage="verification",
        source_type="runtime",
        error_categories_json=["weak_evidence"],
        linked_eval_sample_id="dev-1",
        created_at=datetime.now(UTC),
    )
    version = SimpleNamespace(
        id="version-1",
        version_number=1,
        questions=[question],
        feedback_events=[feedback_event],
    )
    exam = SimpleNamespace(
        id="exam-1",
        title="Exam 1",
        status="generated",
        textbook_id="doc-1",
        current_version=version,
        versions=[version],
        published_at=None,
        strict_scope_flag=True,
        selected_scope_json=[{"scope_id": "chapter:1", "scope_type": "chapter"}],
        feedback_events=[feedback_event],
    )
    bullet = SimpleNamespace(
        id="bullet-1",
        status=SimpleNamespace(value="approved"),
        bullet_type=SimpleNamespace(value="hard_rule"),
        title="Stay in scope",
        content="Stay in selected sections",
        scope_json={},
        tags_json=["scope"],
        confidence=0.9,
    )
    candidate = SimpleNamespace(
        id="candidate-1",
        status=SimpleNamespace(value="candidate"),
        category="weak_evidence",
        proposed_title="Require evidence",
        confidence=0.8,
    )

    export = build_warmup_export([exam], [bullet], [candidate])
    assert export["meta"]["exam_case_count"] == 1
    assert export["meta"]["question_case_count"] == 1
    assert export["meta"]["feedback_case_count"] == 1
    assert export["playbook_seed"][0]["bullet_id"] == "bullet-1"
    assert export["reflection_candidates"][0]["candidate_id"] == "candidate-1"


def check_feedback_event_service_phase4_fields() -> None:
    fake_db = _FakeDb()
    service = FeedbackEventService(fake_db)
    service.queue_playbook_shadow_event(
        exam_id="exam-1",
        exam_version_id="version-1",
        actor_id="user-1",
        stage="generation",
        payload={"matched_count": 2},
    )
    event = fake_db.items[0]
    assert event.signal_type == FeedbackSignalType.PLAYBOOK_SHADOW
    assert event.source_type == "playbook"
    assert event.event_stage == "generation"


def check_phase4_routes_are_mounted() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/v1/playbook/overview" in paths
    assert "/api/v1/playbook/candidates" in paths
    assert "/api/v1/exams/feedback-store" in paths
    assert "/api/v1/exams/feedback-summary" in paths


if __name__ == "__main__":
    check_feedback_store_filters_and_summary()
    asyncio.run(check_playbook_retrieval_modes())
    asyncio.run(check_reflection_candidate_generation())
    check_warmup_export_structure()
    check_feedback_event_service_phase4_fields()
    check_phase4_routes_are_mounted()
    print("Phase 4 foundation checks passed")
