"""Minimal smoke checks for the active MVP runtime.

Run from `backend/`:
    python tests/mvp_smoke_checks.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.runtime_models import GeneratedQuestion, RetrievedContext
from app.core.config import settings
from app.main import app
from app.models.curriculum import Section
from app.models.exam import BloomLevel
from app.models.textbook import PROCESSING_STATUS_ENUM, ProcessingStatus
from app.schemas.exam import ExamGenerationRequest
from app.services.curriculum.scope_service import CurriculumScopeService, ResolvedScope
from app.services.documents.processor import DocumentProcessor
from app.services.exam_planning.blueprint_service import BlueprintService, assign_chunks_to_slots
from app.services.exam_planning.spec_service import ExamSpecService
from app.services.exams.service import ExamService
from app.services.generation.mcq_generation_service import MCQGenerationService
from app.services.generation.question_generator import QuestionGeneratorService
from app.services.retrieval.fallback_embeddings import DeterministicHashEmbeddings, NoOpVectorStore
from app.services.retrieval.retrieval_engine import RetrievalEngine
from app.services.retrieval.scoped_retrieval_service import ScopedRetrievalService
from app.services.review.review_edit_service import ReviewEditService
from app.services.verification.grounding_checker import GroundingChecker
from app.services.verification.mcq_verifier_service import MCQVerifierService
from app.services.verification.validator import QuestionValidator
from app.utils.bloom_levels import normalize_bloom_level


class _FakeVectorStore:
    async def aadd_texts(self, **kwargs):
        _ = kwargs
        return None


class _FailingQueryVectorStore:
    async def asimilarity_search_with_score(self, **kwargs):
        _ = kwargs
        raise RuntimeError("vector backend unavailable")


class _ScalarListResult:
    def __init__(self, rows) -> None:
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _ExecuteResult:
    def __init__(self, rows) -> None:
        self._rows = list(rows)

    def scalars(self):
        return _ScalarListResult(self._rows)


class _FakeDBSession:
    def __init__(self, rows) -> None:
        self._rows = list(rows)

    async def execute(self, statement):
        _ = statement
        return _ExecuteResult(self._rows)


class _ScopeServiceStub:
    def __init__(self) -> None:
        self.heuristic_calls = 0

    def chunk_matches_section(self, metadata: dict, section: Section | None) -> bool:
        _ = metadata, section
        self.heuristic_calls += 1
        return False


class _SectionRepositoryStub:
    def __init__(self, sections: list[Section] | None = None) -> None:
        self.sections = list(sections or [])

    async def get_document_sections(self, document_id: str) -> list[Section]:
        return [section for section in self.sections if section.document_id == document_id]


class _RetrievalRepositoryStub(_SectionRepositoryStub):
    async def get_document_chunks_for_sections(self, document_id: str, section_ids: list[str]):
        _ = document_id, section_ids
        return []

    async def get_document_chunks_without_section_id(self, document_id: str):
        _ = document_id
        return []


class _FakeRetrievalAgent:
    def __init__(self, section_id: str) -> None:
        self.section_id = section_id

    async def retrieve_for_blueprint(self, blueprint, document_id: str, chapters: list[int], constraints: dict):
        _ = document_id, chapters, constraints
        contexts = []
        for slot in blueprint.slots:
            contexts.append(
                RetrievedContext(
                    slot_number=slot.slot_number,
                    query=slot.preferred_query,
                    scope_tags=list(slot.scope_tags or []),
                    chunks=[
                        {
                            "id": "chunk-1",
                            "text": "Van toc dac trung cho muc do nhanh cham cua chuyen dong.",
                            "metadata": {
                                "section_id": self.section_id,
                                "chunk_id": "chunk-1",
                                "chapter_number": 1,
                                "page": 1,
                                "parent_heading": "Bai 1",
                            },
                            "score": 0.95,
                        }
                    ],
                    combined_text="Van toc dac trung cho muc do nhanh cham cua chuyen dong.",
                )
            )
        return contexts

    async def retrieve_for_single_question(
        self,
        query: str,
        document_id: str,
        chapters: list[int] | None = None,
        scope_tags: list[str] | None = None,
    ):
        _ = query, document_id, chapters
        return RetrievedContext(
            slot_number=1,
            query=query,
            scope_tags=list(scope_tags or []),
            chunks=[
                {
                    "id": "chunk-1",
                    "text": "Van toc dac trung cho muc do nhanh cham cua chuyen dong.",
                    "metadata": {
                        "section_id": self.section_id,
                        "chunk_id": "chunk-1",
                        "chapter_number": 1,
                        "page": 1,
                        "parent_heading": "Bai 1",
                    },
                    "score": 0.95,
                }
            ],
            combined_text="Van toc dac trung cho muc do nhanh cham cua chuyen dong.",
        )


class _FakeLLM:
    async def ainvoke(self, messages):
        prompt = str(messages[-1].content if messages else "")
        if "JSON array" in prompt or "json array" in prompt.lower():
            return SimpleNamespace(
                content=(
                    '[{"question_type":"mcq","difficulty":"easy","bloom_level":"remember",'
                    '"content":"Theo doan van, dai luong dac trung cho muc do nhanh cham cua chuyen dong la gi?",'
                    '"options":[{"label":"A","text":"Van toc"},{"label":"B","text":"Quang duong"},'
                    '{"label":"C","text":"Thoi gian"},{"label":"D","text":"Luc"}],'
                    '"correct_answer":"A","explanation":"Doan van neu ro van toc dac trung cho muc do nhanh cham cua chuyen dong."}]'
                )
            )
        return SimpleNamespace(
            content=(
                '{"content":"Theo doan van, dai luong nao dac trung cho muc do nhanh cham cua chuyen dong?",'
                '"options":[{"label":"A","text":"Van toc"},{"label":"B","text":"Quang duong"},'
                '{"label":"C","text":"Thoi gian"},{"label":"D","text":"Luc"}],'
                '"correct_answer":"A","explanation":"Doan van cho biet van toc dac trung cho muc do nhanh cham cua chuyen dong."}'
            )
        )


def check_request_surface_is_mvp_only() -> None:
    request = ExamGenerationRequest(
        document_id="doc-1",
        total_questions=8,
        strict_scope=False,
        document_ids=["doc-1", "doc-2"],
        constraints={"strict_scope": False, "allow_applied_questions": True},
    )
    dumped = request.model_dump()
    assert "strict_scope" not in dumped
    assert "document_ids" not in dumped
    assert request.constraints.allow_applied_questions is False
    assert request.constraints.strict_grounding is True


def check_runtime_payload_is_hardened() -> None:
    request = ExamGenerationRequest(
        document_id="doc-1",
        total_questions=4,
        strict_scope=False,
        document_ids=["doc-1"],
        constraints={"strict_scope": False, "allow_applied_questions": True},
    )
    payload = request.to_mvp_runtime_payload()
    assert payload["document_id"] == "doc-1"
    assert payload["strict_scope"] is True
    assert payload["constraints"]["strict_grounding"] is True
    assert payload["constraints"]["allow_applied_questions"] is False
    assert payload["exam_type"] == "mcq"
    assert payload["question_type"] == "mcq_single_answer"
    assert "textbook_id" not in payload
    assert "document_ids" not in payload
    assert "essay" not in payload["question_distribution"]


def _build_topic_section(section_id: str = "doc-1:topic:1:1") -> Section:
    return Section(
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


async def _resolve_invalid_scope() -> ResolvedScope:
    section = _build_topic_section()
    repository = _SectionRepositoryStub([section])
    service = CurriculumScopeService(repository)
    return await service.resolve_scope(
        document_id="doc-1",
        requested_scope=[{"scope_id": "doc-1:missing", "section_id": "doc-1:missing"}],
        requested_chapters=[],
    )


def check_invalid_scope_does_not_expand_to_full_document() -> None:
    resolved = asyncio.run(_resolve_invalid_scope())
    assert resolved.selected_section_ids == []


async def _build_blueprint_with_section_id():
    section = _build_topic_section()
    repository = _SectionRepositoryStub([section])
    scope_service = CurriculumScopeService(repository)
    resolved_scope = await scope_service.resolve_scope(
        document_id="doc-1",
        requested_scope=[{"scope_id": section.id, "section_id": section.id}],
        requested_chapters=[],
    )
    request = ExamGenerationRequest(
        document_id="doc-1",
        total_questions=1,
        scope=[
            {
                "scope_id": section.id,
                "section_id": section.id,
                "scope_type": "topic",
                "title": "Bai 1",
                "chapter_number": 1,
                "tags": [f"section:{section.id}", "chapter:1"],
            }
        ],
    )
    spec = ExamSpecService().build_exam_spec(
        request=request,
        course_id=None,
        document_id="doc-1",
        resolved_scope=resolved_scope,
    )
    blueprint, _ = await BlueprintService().create_blueprint(
        prompt=spec.source_prompt,
        exam_type="mcq",
        difficulty="custom",
        chapters=list(resolved_scope.chapter_numbers),
        question_distribution={"mcq": {"easy": 1, "medium": 0, "hard": 0}},
        gradually_increasing=False,
        constraints={"strict_scope": True, "bloom_levels": ["remember"]},
        document_metadata={"title": "Vat ly 10"},
        scope=[
            {
                "scope_id": unit.scope_id,
                "section_id": unit.section_id,
                "scope_type": unit.scope_type,
                "title": unit.title,
                "chapter_number": unit.chapter_number,
                "page_from": unit.page_from,
                "page_to": unit.page_to,
                "tags": list(unit.tags or []),
            }
            for unit in spec.selected_scope
        ],
        time_limit_minutes=spec.time_limit_minutes,
        output_language=spec.output_language,
        instructions=spec.normalized_instructions,
        bloom_distribution={"remember": 1},
        formatting_preferences=spec.formatting_preferences,
    )
    return blueprint, section


def check_blueprint_preserves_section_id() -> None:
    blueprint, section = asyncio.run(_build_blueprint_with_section_id())
    assert blueprint.cells
    assert blueprint.cells[0].scope_unit.section_id == section.id
    assert f"section:{section.id}" in blueprint.slots[0].scope_tags


def check_question_generator_rejects_non_mcq_assignments() -> None:
    generator = QuestionGeneratorService(llm=None)
    try:
        generator._assert_mcq_only_assignments([{"question_type": "essay"}])
    except ValueError:
        return
    raise AssertionError("Expected non-MCQ assignments to be rejected")


def check_question_generator_normalizes_string_options() -> None:
    generator = QuestionGeneratorService(llm=None)
    options = generator._normalize_options(
        [
            "A. Van toc",
            "B. Quang duong",
            "C. Thoi gian",
            "D. Luc",
        ]
    )
    assert options == [
        {"label": "A", "text": "Van toc"},
        {"label": "B", "text": "Quang duong"},
        {"label": "C", "text": "Thoi gian"},
        {"label": "D", "text": "Luc"},
    ]
    assert generator._normalize_correct_answer("Van toc", options) == "A"
    assert generator._normalize_correct_answer("B. Quang duong", options) == "B"


def check_bloom_level_aliases_are_normalized() -> None:
    generator = QuestionGeneratorService(llm=None)
    assert normalize_bloom_level("analysis", fallback="remember") == "analyze"
    assert normalize_bloom_level("application", fallback="remember") == "apply"
    assert generator._normalize_payload_bloom_level("analysis", "remember") == "analyze"
    assert generator._normalize_payload_bloom_level("unknown-level", "remember") == "remember"

    db_question = ExamService(db=None)._question_to_db(
        exam_id="exam-1",
        exam_version_id="version-1",
        question=GeneratedQuestion(
            slot_number=1,
            blueprint_cell_key="cell-1",
            question_type="mcq",
            bloom_level="analysis",
            difficulty_score=0.5,
            content="Noi dung cau hoi",
            options=[
                {"label": "A", "text": "Phuong an A"},
                {"label": "B", "text": "Phuong an B"},
                {"label": "C", "text": "Phuong an C"},
                {"label": "D", "text": "Phuong an D"},
            ],
            correct_answer="A",
            explanation="Giai thich",
        ),
        quality_by_slot={},
        grounding_by_slot={},
    )
    assert db_question.bloom_level == BloomLevel.ANALYZE


def check_question_generator_sanitizes_and_truncates_context() -> None:
    generator = QuestionGeneratorService(llm=None)
    noisy_text = "C\u00a7x\n\n\uf03d \uf02d\n\nVan toc trung binh duoc tinh bang quang duong chia thoi gian.\n" * 20
    cleaned = generator._sanitize_source_text(noisy_text, 120)

    assert "\uf03d" not in cleaned
    assert "\uf02d" not in cleaned
    assert len(cleaned) <= 120
    assert "Van toc trung binh" in cleaned


def check_rate_limit_header_parser_supports_retry_windows() -> None:
    generator = QuestionGeneratorService(llm=None)
    assert generator._parse_seconds_header("10") == 10
    assert generator._parse_seconds_header("59.12s") == 59
    assert generator._parse_seconds_header("7m12s") == 432


def check_document_processing_status_uses_enum_values() -> None:
    assert PROCESSING_STATUS_ENUM.enums == [item.name for item in ProcessingStatus]
    bind_processor = PROCESSING_STATUS_ENUM.bind_processor(None)
    assert bind_processor is not None
    assert ProcessingStatus.PARSING is ProcessingStatus.PROCESSING
    assert ProcessingStatus.INDEXED is ProcessingStatus.PROCESSED
    assert bind_processor(ProcessingStatus.PARSING) == "PROCESSING"
    assert bind_processor(ProcessingStatus.INDEXED) == "PROCESSED"


def check_deterministic_fallback_embeddings_are_stable() -> None:
    embeddings = DeterministicHashEmbeddings(dimension=16)
    first = embeddings.embed_query("Van toc trung binh")
    second = embeddings.embed_query("Van toc trung binh")
    third = embeddings.embed_query("Luc ma sat")

    assert len(first) == 16
    assert first == second
    assert first != third
    assert round(sum(value * value for value in first), 6) == 1.0


def check_noop_vector_store_is_safe() -> None:
    store = NoOpVectorStore(namespace="doc-1")
    assert asyncio.run(store.aadd_texts(texts=["hello"], metadatas=[{}], ids=["c1"])) == []
    assert asyncio.run(store.asimilarity_search_with_score(query="hello", k=3)) == []


def check_chunk_section_id_is_attached() -> None:
    processor = DocumentProcessor(vector_store=_FakeVectorStore())
    formatted_chunks = [
        {
            "chunk_text": "Bai 1. Chuyen dong thang deu la chuyen dong co van toc khong doi.",
            "chunk_id": "c1",
            "chunk_index": 0,
            "metadata": {
                "source_file": "physics.pdf",
                "textbook_id": "doc-1",
                "page_number": 1,
                "chapter": "Chuong 1",
                "chapter_number": 1,
                "parent_heading": "Bai 1 Chuyen dong thang deu",
            },
        },
        {
            "chunk_text": "Van toc trung binh duoc tinh bang quang duong chia thoi gian.",
            "chunk_id": "c2",
            "chunk_index": 1,
            "metadata": {
                "source_file": "physics.pdf",
                "textbook_id": "doc-1",
                "page_number": 1,
                "chapter": "Chuong 1",
                "chapter_number": 1,
                "parent_heading": "Bai 1 Chuyen dong thang deu",
            },
        },
    ]
    chapters = [{"chapter_number": 1, "title": "Chuyen dong co", "start_page": 1, "end_page": 10}]

    sections = processor._derive_sections(formatted_chunks, chapters, "doc-1")
    assert sections
    for chunk in formatted_chunks:
        section_id = (chunk.get("metadata") or {}).get("section_id")
        assert isinstance(section_id, str) and section_id.startswith("doc-1:")


def check_retrieval_prefers_deterministic_section_id() -> None:
    scope_stub = _ScopeServiceStub()
    service = ScopedRetrievalService(
        retrieval_agent=None,
        repository=None,
        scope_service=scope_stub,
        section_by_id={},
    )
    section = Section(
        id="doc-1:topic:1:1",
        document_id="doc-1",
        section_title="Bai 1",
        section_type="topic",
        section_order=1,
    )
    context = RetrievedContext(
        slot_number=1,
        query="van toc",
        scope_tags=["section:doc-1:topic:1:1"],
        chunks=[
            {
                "id": "ok-1",
                "text": "text",
                "metadata": {"section_id": "doc-1:topic:1:1", "chunk_id": "ok-1"},
                "score": 0.9,
            },
            {
                "id": "bad-1",
                "text": "text",
                "metadata": {"section_id": "doc-1:topic:1:2", "chunk_id": "bad-1"},
                "score": 0.8,
            },
            {
                "id": "legacy-1",
                "text": "text",
                "metadata": {"chunk_id": "legacy-1"},
                "score": 0.7,
            },
        ],
    )

    chunk_metadata_index: dict[str, dict] = {}
    filtered = service._filter_context_chunks(
        context=context,
        document_id="doc-1",
        section=section,
        strict_scope=True,
        chunk_metadata_index=chunk_metadata_index,
    )

    ids = [item["id"] for item in filtered]
    assert ids == ["ok-1"]
    assert scope_stub.heuristic_calls == 1


async def _retrieve_with_vector_failure_uses_bm25() -> None:
    row = SimpleNamespace(
        metadata_json='{"chapter_number": 1, "parent_heading": "Bai 1"}',
        chapter="Chuong 1",
        parent_heading="Bai 1",
        page=1,
        chunk_id="chunk-1",
        content="Van toc trung binh duoc tinh bang quang duong chia cho thoi gian.",
    )
    agent = RetrievalEngine(
        vector_store=_FailingQueryVectorStore(),
        db_session=_FakeDBSession([row]),
    )
    context = await agent.retrieve_for_single_question(
        query="van toc trung binh",
        document_id="doc-1",
        chapter=1,
        top_k=3,
    )
    assert context.chunks
    assert context.chunks[0]["id"] == "chunk-1"
    assert "Van toc trung binh" in context.combined_text


def check_retrieval_falls_back_to_bm25_when_vector_search_fails() -> None:
    asyncio.run(_retrieve_with_vector_failure_uses_bm25())


async def _run_component_flow_smoke() -> None:
    section = _build_topic_section()
    repository = _RetrievalRepositoryStub([section])
    scope_service = CurriculumScopeService(repository)
    resolved_scope = await scope_service.resolve_scope(
        document_id="doc-1",
        requested_scope=[{"scope_id": section.id, "section_id": section.id}],
        requested_chapters=[],
    )
    request = ExamGenerationRequest(
        document_id="doc-1",
        total_questions=1,
        scope=[
            {
                "scope_id": section.id,
                "section_id": section.id,
                "scope_type": "topic",
                "title": "Bai 1",
                "chapter_number": 1,
                "tags": [f"section:{section.id}", "chapter:1"],
            }
        ],
    )

    spec = ExamSpecService().build_exam_spec(
        request=request,
        course_id=None,
        document_id="doc-1",
        resolved_scope=resolved_scope,
    )
    blueprint, _ = await BlueprintService().create_blueprint(
        prompt=spec.source_prompt,
        exam_type="mcq",
        difficulty="custom",
        chapters=list(resolved_scope.chapter_numbers),
        question_distribution={"mcq": {"easy": 1, "medium": 0, "hard": 0}},
        gradually_increasing=False,
        constraints={"strict_scope": True, "bloom_levels": ["remember"]},
        document_metadata={"title": "Vat ly 10"},
        scope=[
            {
                "scope_id": unit.scope_id,
                "section_id": unit.section_id,
                "scope_type": unit.scope_type,
                "title": unit.title,
                "chapter_number": unit.chapter_number,
                "page_from": unit.page_from,
                "page_to": unit.page_to,
                "tags": list(unit.tags or []),
            }
            for unit in spec.selected_scope
        ],
        time_limit_minutes=spec.time_limit_minutes,
        output_language=spec.output_language,
        instructions=spec.normalized_instructions,
        bloom_distribution={"remember": 1},
        formatting_preferences=spec.formatting_preferences,
    )

    retrieval_service = ScopedRetrievalService(
        retrieval_agent=_FakeRetrievalAgent(section.id),
        repository=repository,
        scope_service=scope_service,
        section_by_id={section.id: section},
    )
    retrieved_contexts, chunk_metadata_index, retrieval_stats = await retrieval_service.retrieve_for_blueprint(
        blueprint=blueprint,
        document_id="doc-1",
        strict_scope=True,
    )
    chunk_assignments = await assign_chunks_to_slots(blueprint, retrieved_contexts)
    assert chunk_assignments
    assert retrieval_stats["slots_with_chunks"] == len(retrieved_contexts)

    generation_service = MCQGenerationService(_FakeLLM())
    original_delay = settings.LLM_REQUEST_DELAY
    settings.LLM_REQUEST_DELAY = 0
    try:
        generated_questions = await generation_service.generate(
            chunk_assignments=chunk_assignments,
            strict_scope=True,
        )
    finally:
        settings.LLM_REQUEST_DELAY = original_delay
    assert generated_questions

    exam_service = ExamService(db=None)
    exam_service._enrich_source_evidence(generated_questions, chunk_metadata_index, "doc-1")

    verifier_service = MCQVerifierService(QuestionValidator(grounding_checker=GroundingChecker()))
    verified_questions, summary, _, _, _ = await verifier_service.verify(
        questions=generated_questions,
        blueprint=blueprint,
        resolved_scope=resolved_scope,
    )
    assert summary["total"] == len(generated_questions)
    assert verified_questions[0].source_evidence[0]["section_id"] == section.id

    edit_service = ReviewEditService()
    question_map, regenerate_targets = edit_service.apply_edits(
        existing_questions=verified_questions,
        edit_requests=[{"edit_type": "regenerate", "question_ids": ["1"], "edit_prompt": "Doi cach hoi"}],
    )
    assert regenerate_targets == [(1, "Doi cach hoi")]

    context, regen_index, regen_stats = await retrieval_service.retrieve_for_single_question(
        query=verified_questions[0].content,
        document_id="doc-1",
        scope_tags=list(verified_questions[0].scope_tags or []),
        strict_scope=True,
    )
    regenerated = await generation_service.regenerate_question(
        original_question=verified_questions[0],
        context=context,
        edit_prompt="Doi cach hoi",
    )
    exam_service._enrich_source_evidence([regenerated], regen_index, "doc-1")
    question_map[1] = regenerated
    final_questions = edit_service.renumber(question_map)
    assert final_questions[0].question_type == "mcq"
    assert final_questions[0].source_evidence[0]["section_id"] == section.id
    assert regen_stats["slots_with_chunks"] == 1


def check_component_flow_smoke() -> None:
    asyncio.run(_run_component_flow_smoke())


def check_production_routes_mvp_only() -> None:
    paths = {route.path for route in app.routes}
    assert any(path.startswith("/api/v1/documents") for path in paths)
    assert not any(path.startswith("/api/v1/textbooks") for path in paths)
    assert not any(path.startswith("/api/v1/guidance") for path in paths)
    assert not any(path.startswith("/api/v1/export") for path in paths)


if __name__ == "__main__":
    check_request_surface_is_mvp_only()
    check_runtime_payload_is_hardened()
    check_invalid_scope_does_not_expand_to_full_document()
    check_blueprint_preserves_section_id()
    check_question_generator_rejects_non_mcq_assignments()
    check_question_generator_normalizes_string_options()
    check_bloom_level_aliases_are_normalized()
    check_question_generator_sanitizes_and_truncates_context()
    check_rate_limit_header_parser_supports_retry_windows()
    check_document_processing_status_uses_enum_values()
    check_deterministic_fallback_embeddings_are_stable()
    check_noop_vector_store_is_safe()
    check_chunk_section_id_is_attached()
    check_retrieval_prefers_deterministic_section_id()
    check_retrieval_falls_back_to_bm25_when_vector_search_fails()
    check_component_flow_smoke()
    check_production_routes_mvp_only()
    print("MVP smoke checks passed")
