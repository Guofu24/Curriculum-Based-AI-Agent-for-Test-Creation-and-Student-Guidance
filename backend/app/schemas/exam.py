"""Exam schemas for request/response validation."""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Any, Literal


# ── Generation Schemas (for /generate endpoints) ────────────────────────────────

class BloomDistribution(BaseModel):
    """Bloom taxonomy distribution as percentages summing to 100."""
    nhan_biet: int = Field(default=20, ge=0, le=100)
    thong_hieu: int = Field(default=30, ge=0, le=100)
    van_dung: int = Field(default=30, ge=0, le=100)
    van_dung_cao: int = Field(default=20, ge=0, le=100)


class ExamConfigRequest(BaseModel):
    """
    Schema used by /api/v1/exams/generate endpoint.
    Contains the full exam configuration including bloom distribution.
    """
    document_id: str | None = None
    course_id: str | None = None
    title: str | None = None
    scope: list[str] = Field(default_factory=list)
    exam_type: str = "mixed"
    mcq_count: int = Field(default=40, ge=1, le=200)
    essay_count: int = Field(default=5, ge=0, le=50)
    bloom_distribution: BloomDistribution = Field(default_factory=BloomDistribution)
    user_prompt: str = Field(..., min_length=1)
    extra_instructions: str | None = None
    instructions: str | None = None
    time_limit_minutes: int | None = None
    output_language: str = "vi"
    strict_scope_flag: bool = True


class GenerationStep(BaseModel):
    """Schema matching frontend's GenerationStep interface."""
    step: int
    name: str
    status: str = "pending"
    message: str | None = None
    progress: float | None = None


class ExamGenerationRequest(BaseModel):
    """Schema matching frontend's ExamGenerationRequest interface."""
    document_id: str | None = None
    course_id: str | None = None
    chapters: list[int] = Field(default_factory=list)
    scope: list[dict] = Field(default_factory=list)
    prompt: str = Field(..., min_length=1)
    instructions: str | None = None
    total_questions: int = Field(default=40, ge=1, le=200)
    question_type: str | None = None
    exam_type: str = "mixed"
    difficulty: str | None = None
    question_distribution: dict[str, dict[str, float]] | None = None
    num_variants: int | None = None
    gradually_increasing: bool = False
    constraints: dict[str, Any] = Field(default_factory=dict)
    time_limit_minutes: int | None = None
    output_language: str = "vi"
    bloom_distribution: dict[str, int] | None = None
    formatting_preferences: dict[str, Any] | None = None

    def to_mvp_runtime_payload(self) -> dict:
        """Convert to legacy exam_config format."""
        return self.model_dump()


class ExamPartialRegenerateRequest(BaseModel):
    """Schema matching frontend's PartialEditRequest interface."""
    exam_id: str
    edits: list["PartialEditItem"] = Field(default_factory=list)


class PartialEditItem(BaseModel):
    """Schema for a single partial edit request."""
    question_ids: list[str]
    edit_prompt: str | None = None
    range_start: int | None = None
    range_end: int | None = None
    edit_type: str = "regenerate"
    new_content: str | None = None
    new_options: list[dict] | None = None
    new_correct_answer: str | None = None
    new_bloom_level: str | None = None


# ── Question Response ─────────────────────────────────────────────────────────

class MCQOption(BaseModel):
    """Schema for MCQ option."""
    label: str
    text: str


class SourceEvidence(BaseModel):
    """Schema for source evidence."""
    document_id: str | None = None
    section_id: str | None = None
    chunk_id: str | None = None
    chapter_number: int | None = None
    page: int | None = None
    parent_heading: str | None = None
    role: str | None = None
    score: float | None = None
    text_preview: str | None = None


class QuestionResponse(BaseModel):
    """Schema for a question in the API response."""
    id: str
    question_number: int
    blueprint_cell_key: str | None = None
    question_type: str
    bloom_level: str
    difficulty_score: float | None = None
    content: str
    options: list[MCQOption] | None = None
    correct_answer: str
    rubric: dict | None = None
    explanation: str | None = None
    source_citations: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)
    scope_tags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    verification_status: str | None = None
    is_human_edited: bool = False
    is_locked: bool = False
    is_validated: bool = False
    quality_score_detail: dict | None = None
    grounding_report_detail: dict | None = None
    error_categories: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


# ── Edit Operation ─────────────────────────────────────────────────────────────

class EditOperationResponse(BaseModel):
    """Schema for an edit operation."""
    id: str
    edit_type: str
    target_question_id: str | None = None
    target_slots: list[int] = Field(default_factory=list)
    prompt_used: str | None = None
    created_at: datetime


# ── Feedback Event ─────────────────────────────────────────────────────────────

class FeedbackEventResponse(BaseModel):
    """Schema for a feedback event."""
    id: str
    exam_id: str
    exam_title: str | None = None
    exam_version_id: str | None = None
    version_number: int | None = None
    actor_id: str | None = None
    signal_type: str
    severity: str
    workflow_stage: str | None = None
    event_stage: str | None = None
    event_source: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    review_status: str | None = None
    reviewed_by_human: bool = False
    question_id: str | None = None
    error_categories: list[str] = Field(default_factory=list)
    before_snapshot_ref: str | None = None
    after_snapshot_ref: str | None = None
    linked_eval_sample_id: str | None = None
    payload: dict | None = None
    created_at: datetime


# ── Exam Version ─────────────────────────────────────────────────────────────

class ExamVersionResponse(BaseModel):
    """Schema for an exam version."""
    id: str
    version_number: int
    status: str
    created_by: str
    parent_version_id: str | None = None
    change_summary: str | None = None
    created_at: datetime
    questions: list[QuestionResponse] = Field(default_factory=list)
    edit_operations: list[EditOperationResponse] = Field(default_factory=list)
    feedback_events: list[FeedbackEventResponse] = Field(default_factory=list)


# ── Exam Responses ─────────────────────────────────────────────────────────────

class ExamListResponse(BaseModel):
    """Schema for exam list item."""
    id: str
    title: str | None = None
    document_id: str | None = None
    course_id: str | None = None
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = Field(default_factory=list)
    total_questions: int = 0
    strict_scope_flag: bool = True
    quality_score: float | None = None
    current_version_number: int | None = None
    version_count: int = 0
    verifier_pass_rate: float | None = None
    evidence_coverage_rate: float | None = None
    warning_count: int = 0
    regenerate_count: int = 0
    human_edit_count: int = 0
    feedback_event_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExamResponse(BaseModel):
    """Schema for full exam detail response."""
    id: str
    title: str | None = None
    document_id: str | None = None
    course_id: str | None = None
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = Field(default_factory=list)
    variant_number: int = 1
    total_questions: int = 0
    instructions: str | None = None
    output_language: str = "vi"
    strict_scope_flag: bool = True
    quality_score: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None
    questions: list[QuestionResponse] = Field(default_factory=list)
    exam_spec: dict | None = None
    blueprint: dict | None = None
    selected_scope: list[dict] | None = None
    quality_scores: list[dict] | None = None
    grounding_reports: list[dict] | None = None
    duplicate_groups: list[dict] | None = None
    provider_logs: list[dict] | None = None
    edit_impact_level: str | None = None
    edit_history: list[dict] | None = None
    feedback_events: list[dict] | None = None
    current_version: dict | None = None
    versions: list[dict] = Field(default_factory=list)


class ErrorCategoryCount(BaseModel):
    """Schema for error category count."""
    category: str
    count: int


class NamedCount(BaseModel):
    """Schema for named count."""
    name: str
    count: int


class QualitySummaryResponse(BaseModel):
    """Schema for quality summary."""
    documents_active: int = 0
    exams_generated: int = 0
    question_count: int = 0
    verifier_pass_rate: float = 0.0
    verifier_warning_rate: float = 0.0
    evidence_coverage_rate: float = 0.0
    scope_violation_rate: float = 0.0
    avg_regenerate_count: float = 0.0
    avg_human_edit_count: float = 0.0
    version_churn: float = 0.0
    top_error_categories: list[ErrorCategoryCount] = Field(default_factory=list)
    recent_warnings: list[dict] = Field(default_factory=list)
    last_updated_at: datetime | None = None


class FeedbackStoreSummaryResponse(BaseModel):
    """Schema for feedback store summary."""
    total_events: int = 0
    reviewed_by_human_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    corrected_count: int = 0
    linked_eval_count: int = 0
    top_signal_types: list[NamedCount] = Field(default_factory=list)
    top_error_categories: list[ErrorCategoryCount] = Field(default_factory=list)
    recent_events: list[dict] = Field(default_factory=list)
    last_updated_at: datetime | None = None


class ExamGenerateResponse(BaseModel):
    """Schema for exam generation job response."""
    exam_id: str
    job_id: str
    message: str = "Exam generation started"
    websocket_url: str | None = None


class EditQuestionRequest(BaseModel):
    """Schema for editing a single question."""
    question_id: str
    updates: dict[str, Any]


class PromptEditRequest(BaseModel):
    """Schema for prompt-based editing."""
    prompt: str = Field(..., min_length=5)


class RegenerateRequest(BaseModel):
    """Schema for regenerating questions."""
    question_ids: list[str] | None = None
    scope: list[str] | None = None


class ExportFormat(BaseModel):
    """Schema for export format selection."""
    format: Literal["pdf", "docx"]


class BlueprintApprovalRequest(BaseModel):
    """Schema for blueprint approval."""
    approved: bool
    feedback: str | None = None


class ExamHistoryItem(BaseModel):
    """Schema for exam history snapshot."""
    id: UUID
    change_type: str
    change_description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class RestoreSnapshotRequest(BaseModel):
    """Schema for restoring a snapshot."""
    history_id: UUID


# Update forward reference
ExamPartialRegenerateRequest.model_rebuild()
