"""
Shared orchestration state and exam-generation domain dataclasses.

These structures intentionally model the spec-first workflow:
- request normalization into an ExamSpec
- blueprint cells before generation
- slot-level retrieval and provenance
- auditable question metadata for review/edit/versioning
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass
class ScopeUnit:
    scope_id: str
    section_id: str | None = None
    scope_type: str = "chapter"
    title: str = ""
    chapter_number: int = 0
    page_from: int | None = None
    page_to: int | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ExamSpec:
    exam_type: str
    total_questions: int
    course_id: str | None = None
    document_id: str | None = None
    question_type: str = "mcq_single_answer"
    time_limit_minutes: int | None = None
    output_language: str = "vi"
    instructions: str = ""
    normalized_instructions: str = ""
    strict_scope_flag: bool = True
    selected_scope: list[ScopeUnit] = field(default_factory=list)
    selected_section_ids: list[str] = field(default_factory=list)
    bloom_distribution: dict[str, int] = field(default_factory=dict)
    question_mix: dict[str, int] = field(default_factory=dict)
    formatting_preferences: dict[str, Any] = field(default_factory=dict)
    source_prompt: str = ""


@dataclass
class BlueprintCell:
    cell_id: str
    scope_unit: ScopeUnit
    question_type: str
    bloom_level: str
    target_count: int
    generated_count: int = 0
    priority: int = 0
    overgenerate_count: int = 0


@dataclass
class QuestionSlot:
    slot_number: int
    question_type: str
    bloom_level: str
    difficulty_score: float
    target_chapter: int = 0
    target_topics: list[str] = field(default_factory=list)
    blueprint_cell_key: str = ""
    scope_tags: list[str] = field(default_factory=list)
    chunk_mode: str = "single"
    preferred_query: str = ""


@dataclass
class ExamBlueprint:
    title: str
    exam_spec: ExamSpec
    total_questions: int
    cells: list[BlueprintCell] = field(default_factory=list)
    slots: list[QuestionSlot] = field(default_factory=list)
    difficulty_distribution: dict[str, int] = field(default_factory=dict)
    bloom_distribution: dict[str, int] = field(default_factory=dict)


@dataclass
class RetrievedContext:
    slot_number: int
    chunks: list[dict] = field(default_factory=list)
    combined_text: str = ""
    query: str = ""
    scope_tags: list[str] = field(default_factory=list)


@dataclass
class GeneratedQuestion:
    slot_number: int
    question_type: str
    bloom_level: str
    difficulty_score: float
    content: str
    correct_answer: str
    blueprint_cell_key: str = ""
    options: list[dict] | None = None
    rubric: dict[str, Any] | None = None
    explanation: str = ""
    source_chunks: list[str] = field(default_factory=list)
    source_texts: list[str] = field(default_factory=list)
    source_evidence: list[dict] = field(default_factory=list)
    scope_tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verification_status: str = "pending"
    is_human_edited: bool = False
    is_locked: bool = False
    is_validated: bool = False
    validation_notes: str = ""


@dataclass
class ChunkAssignment:
    chunk_id: str
    chunk_text: str
    chapter: int = 0
    assignments: list[dict] = field(default_factory=list)
    context_chunks: list[dict] = field(default_factory=list)
    chunk_mode: str = "single"
    bundle_strategy: str = "single"
    supporting_chunks: list[dict] = field(default_factory=list)
    bundle_score: float = 0.0
    assignment_reason: str = ""
    evidence_roles: dict[str, str] = field(default_factory=dict)
    estimated_context_tokens: int = 0
    bundle_validation_report: dict[str, Any] = field(default_factory=dict)
    source_chunks: list[str] = field(default_factory=list)
    primary_chunk: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.primary_chunk is None:
            self.primary_chunk = {
                "chunk_id": self.chunk_id,
                "chunk_text": self.chunk_text,
            }
        if not self.supporting_chunks and self.context_chunks:
            self.supporting_chunks = list(self.context_chunks)
        if not self.source_chunks:
            self.source_chunks = self.get_source_chunk_ids()

    def get_supporting_chunks(self) -> list[dict]:
        return list(self.supporting_chunks or self.context_chunks or [])

    def get_source_chunk_ids(self) -> list[str]:
        chunk_ids: list[str] = []
        primary_id = (self.primary_chunk or {}).get("chunk_id") or self.chunk_id
        if primary_id:
            chunk_ids.append(primary_id)
        for chunk in self.get_supporting_chunks():
            chunk_id = chunk.get("chunk_id")
            if chunk_id and chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
        return chunk_ids


class AgentState(TypedDict, total=False):
    user_id: str
    textbook_id: str
    chapters: list[int]
    prompt: str
    exam_type: str
    difficulty: str
    question_distribution: dict[str, Any]
    num_variants: int
    gradually_increasing: bool
    constraints: dict[str, Any]
    textbook_metadata: dict[str, Any]
    processing_status: str
    exam_spec: ExamSpec | None
    blueprint: ExamBlueprint | None
    retrieved_contexts: list[RetrievedContext]
    generated_questions: list[GeneratedQuestion]
    validated_questions: list[GeneratedQuestion]
    validation_summary: dict[str, Any]
    judged_questions: list[GeneratedQuestion]
    quality_scores: list[dict[str, Any]]
    grounding_reports: list[dict[str, Any]]
    duplicate_groups: list[dict[str, Any]]
    final_questions: list[GeneratedQuestion]
    current_step: str
    step_progress: float
    error: str | None
    chunk_assignments: list[ChunkAssignment]
    chunk_assignment_payloads: list[dict[str, Any]]
    question_chunk_metadata: list[dict[str, Any]]
    original_quota: dict[str, int]
    edit_requests: list[dict[str, Any]] | None
    is_partial_edit: bool
    edit_impact_level: str | None
    refreshed_contexts: list[RetrievedContext]
    provider_logs: list[dict[str, Any]]
    scope: list[dict[str, Any]]
    time_limit_minutes: int | None
    output_language: str
    instructions: str
    bloom_distribution: dict[str, int]
    formatting_preferences: dict[str, Any]
    strict_scope: bool
    # Audit results (from Scope Auditor & Bloom Auditor agents)
    scope_audit_results: list[dict[str, Any]]
    bloom_audit_results: list[dict[str, Any]]
    # Agent references
    _retrieval_agent: Any
    _blueprint_agent: Any
    _question_generator: Any
    _validator: Any
    _reviewer: Any
    _pruning_agent: Any
    _quality_judge: Any
    _dedup_filter: Any
    _scope_auditor: Any
    _bloom_auditor: Any
    _requirement_parser: Any
    _db_session: Any
    _retry_attempted: bool
