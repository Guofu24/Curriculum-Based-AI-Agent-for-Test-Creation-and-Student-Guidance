"""Phase 2 hardening checks for feedback logging, retrieval stats, and eval infra.

Run from `backend/`:
    python tests/phase2_hardening_checks.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents.state import BlueprintCell, ExamBlueprint, ExamSpec, GeneratedQuestion, RetrievedContext, ScopeUnit
from evals.run_phase2_eval import compute_metrics, load_dataset
from models.curriculum import Section
from models.exam import ExamQuestion, FeedbackSignalType
from services.curriculum.scope_service import ResolvedScope
from services.feedback.feedback_event_service import FeedbackEventService
from services.retrieval.scoped_retrieval_service import ScopedRetrievalService
from services.verification.mcq_verifier_service import MCQVerifierService
from agents.validator import ValidatorAgent
from agents.grounding_checker import GroundingChecker


class _FakeDb:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, item: object) -> None:
        self.items.append(item)


class _EmptyRepository:
    async def get_document_chunks_for_sections(self, document_id: str, section_ids: list[str]):
        _ = document_id, section_ids
        return []

    async def get_document_chunks_without_section_id(self, document_id: str):
        _ = document_id
        return []


class _ScopeServiceStub:
    def chunk_matches_section(self, metadata: dict, section: Section | None) -> bool:
        _ = metadata, section
        return False


class _MismatchedRetrievalAgent:
    async def retrieve_for_blueprint(self, blueprint, document_id: str, chapters: list[int], constraints: dict):
        _ = document_id, chapters, constraints
        return [
            RetrievedContext(
                slot_number=slot.slot_number,
                query=slot.preferred_query,
                scope_tags=list(slot.scope_tags or []),
                chunks=[
                    {
                        "id": "chunk-outside-scope",
                        "text": "Noi dung ngoai scope.",
                        "metadata": {
                            "section_id": "doc-1:topic:999",
                            "chunk_id": "chunk-outside-scope",
                            "chapter_number": 99,
                        },
                        "score": 0.42,
                    }
                ],
                combined_text="Noi dung ngoai scope.",
            )
            for slot in blueprint.slots
        ]


def _build_scope_unit(section_id: str = "doc-1:topic:1:1") -> ScopeUnit:
    return ScopeUnit(
        scope_id=section_id,
        section_id=section_id,
        scope_type="topic",
        title="Bai 1",
        chapter_number=1,
        tags=[f"section:{section_id}", "chapter:1"],
    )


def _build_resolved_scope(section_id: str = "doc-1:topic:1:1") -> ResolvedScope:
    section = Section(
        id=section_id,
        document_id="doc-1",
        section_title="Bai 1",
        section_type="topic",
        section_order=1,
        page_from=1,
        page_to=2,
        scope_label="Bai 1",
        metadata_json={"chapter_number": 1},
    )
    scope_unit = _build_scope_unit(section_id)
    return ResolvedScope(
        selected_scope=[scope_unit],
        selected_sections=[section],
        selected_section_ids=[section.id],
        chapter_numbers=[1],
        section_by_id={section.id: section},
    )


async def _check_retrieval_stats_for_empty_scope() -> None:
    resolved_scope = _build_resolved_scope()
    spec = ExamSpec(exam_type="mcq", total_questions=1, selected_scope=resolved_scope.selected_scope)
    blueprint = ExamBlueprint(
        title="Eval",
        exam_spec=spec,
        total_questions=1,
        cells=[
            BlueprintCell(
                cell_id="cell-1",
                scope_unit=resolved_scope.selected_scope[0],
                question_type="mcq",
                bloom_level="remember",
                target_count=1,
            )
        ],
        slots=[],
    )
    blueprint.slots = [
        type("Slot", (), {
            "slot_number": 1,
            "preferred_query": "van toc",
            "scope_tags": [f"section:{resolved_scope.selected_section_ids[0]}", "chapter:1"],
            "target_chapter": 1,
        })()
    ]
    retrieval_service = ScopedRetrievalService(
        retrieval_agent=_MismatchedRetrievalAgent(),
        repository=_EmptyRepository(),
        scope_service=_ScopeServiceStub(),
        section_by_id=resolved_scope.section_by_id,
    )
    contexts, _, stats = await retrieval_service.retrieve_for_blueprint(
        blueprint=blueprint,
        document_id="doc-1",
        strict_scope=True,
    )
    assert len(contexts) == 1
    assert contexts[0].chunks == []
    assert stats["slots_requested"] == 1
    assert stats["slots_without_chunks"] == 1
    assert stats["slots_with_chunks"] == 0


def check_retrieval_stats_for_empty_scope() -> None:
    asyncio.run(_check_retrieval_stats_for_empty_scope())


async def _check_verifier_failure_mode() -> None:
    resolved_scope = _build_resolved_scope()
    scope_unit = resolved_scope.selected_scope[0]
    blueprint = ExamBlueprint(
        title="Verifier",
        exam_spec=ExamSpec(exam_type="mcq", total_questions=1, selected_scope=[scope_unit]),
        total_questions=1,
        cells=[
            BlueprintCell(
                cell_id="cell-1",
                scope_unit=scope_unit,
                question_type="mcq",
                bloom_level="remember",
                target_count=1,
            )
        ],
    )
    question = GeneratedQuestion(
        slot_number=1,
        blueprint_cell_key="cell-1",
        question_type="mcq",
        bloom_level="remember",
        difficulty_score=0.2,
        content="Gia toc la gi?",
        options=[
            {"label": "A", "text": "Do bien thien van toc"},
            {"label": "B", "text": "Do bien thien quang duong"},
            {"label": "C", "text": "Do bien thien luc"},
        ],
        correct_answer="A",
        explanation="Ngan",
        source_evidence=[],
        scope_tags=list(scope_unit.tags),
        is_validated=True,
    )
    verifier = MCQVerifierService(ValidatorAgent(grounding_checker=GroundingChecker()))
    verified_questions, summary, _, _, _ = await verifier.verify(
        questions=[question],
        blueprint=blueprint,
        resolved_scope=resolved_scope,
    )
    assert summary["failed"] == 1
    assert verified_questions[0].verification_status == "failed"
    assert verified_questions[0].warnings


def check_verifier_failure_mode() -> None:
    asyncio.run(_check_verifier_failure_mode())


def check_feedback_event_service_records_structured_signals() -> None:
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
        correct_answer="A",
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
        payload={"slots_requested": 1, "slots_without_chunks": 1},
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
        actor_id="user-1",
        edit_requests=[
            {"edit_type": "regenerate", "question_ids": ["1"], "edit_prompt": "Lam ngan hon"},
            {"edit_type": "edit_text", "question_ids": ["1"], "new_content": "Noi dung moi"},
        ],
        question_id_by_slot={1: "question-1"},
    )
    service.queue_publish_event(
        exam_id="exam-1",
        exam_version_id="version-1",
        actor_id="user-1",
        payload={"question_count": 1},
    )

    signal_types = [item.signal_type for item in fake_db.items]
    assert FeedbackSignalType.RETRIEVAL_SUMMARY in signal_types
    assert FeedbackSignalType.VERIFIER_FAILED in signal_types
    assert FeedbackSignalType.REGENERATE_REQUESTED in signal_types
    assert FeedbackSignalType.HUMAN_EDIT in signal_types
    assert FeedbackSignalType.EXAM_PUBLISHED in signal_types


def check_eval_metrics() -> None:
    dataset = load_dataset(BACKEND_ROOT / "evals" / "samples" / "physics_phase2_eval.json")
    metrics = compute_metrics(dataset)
    assert metrics["sample_count"] == 2
    assert metrics["question_count"] == 3
    assert metrics["evidence_coverage_rate"] > 0
    assert metrics["scope_violation_rate"] > 0


if __name__ == "__main__":
    check_retrieval_stats_for_empty_scope()
    check_verifier_failure_mode()
    check_feedback_event_service_records_structured_signals()
    check_eval_metrics()
    print("Phase 2 hardening checks passed")
