"""Exam schemas for request/response validation."""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Any, Literal


# ── Generation Schemas (for /generate endpoints) ────────────────────────────────

class BloomDistribution(BaseModel):
    """
    Bloom taxonomy distribution as percentages that MUST sum to 100%.

    Maps to the 4 Vietnamese Bloom levels:
    - **nhan_biet** (Nhận biết): Recall / Recognition — lowest cognitive level
    - **thong_hieu** (Thông hiểu): Understanding / Comprehension
    - **van_dung** (Vận dụng): Application — use knowledge in new situations
    - **van_dung_cao** (Vận dụng cao): Higher-order application — analyze, evaluate, create
    """
    nhan_biet: int = Field(
        default=20,
        ge=0,
        le=100,
        description="Percentage of Nhận biết (Recognition) level questions. Default: 20%.",
    )
    thong_hieu: int = Field(
        default=30,
        ge=0,
        le=100,
        description="Percentage of Thông hiểu (Understanding) level questions. Default: 30%.",
    )
    van_dung: int = Field(
        default=30,
        ge=0,
        le=100,
        description="Percentage of Vận dụng (Application) level questions. Default: 30%.",
    )
    van_dung_cao: int = Field(
        default=20,
        ge=0,
        le=100,
        description="Percentage of Vận dụng cao (Higher-order) level questions. Default: 20%.",
    )


class ExamConfigRequest(BaseModel):
    """
    Full exam generation configuration — used by POST /api/v1/exams/generate.

    Example request:
    ```json
    {
      "document_id": "550e8400-e29b-41d4-a716-446655440000",
      "scope": ["Chương 1: Dao động", "Chương 2: Sóng cơ"],
      "exam_type": "mixed",
      "mcq_count": 10,
      "essay_count": 2,
      "bloom_distribution": {
        "nhan_biet": 20,
        "thong_hieu": 30,
        "van_dung": 30,
        "van_dung_cao": 20
      },
      "user_prompt": "Tạo đề kiểm tra 1 tiết Vật lý lớp 11, phạm vi từ bảng tuần hoàn"
    }
    ```
    """
    document_id: str | None = Field(
        None,
        description="UUID of the uploaded document to generate exam from. "
                    "Document must have processing_status='completed'.",
    )
    course_id: str | None = Field(
        None,
        description="UUID of the course (optional). If not provided, course_id is null.",
    )
    title: str | None = Field(
        None,
        max_length=500,
        description="Custom exam title. Defaults to first 500 chars of user_prompt if not set.",
    )
    scope: list[str] = Field(
        default_factory=list,
        description="List of chapter/section titles to include in the exam scope. "
                    "Corresponds to heading_tree nodes from the uploaded document.",
    )
    exam_type: str = Field(
        default="mixed",
        description="Type of exam. Options: 'mcq' (only multiple-choice), "
                    "'essay' (only essay), 'mixed' (both). Default: 'mixed'.",
    )
    mcq_count: int = Field(
        default=40,
        ge=1,
        le=200,
        description="Target number of multiple-choice questions (MCQ). Range: 1–200. Default: 40.",
    )
    essay_count: int = Field(
        default=5,
        ge=0,
        le=50,
        description="Target number of essay/short-answer questions. Range: 0–50. Default: 5.",
    )
    bloom_distribution: BloomDistribution = Field(
        default_factory=BloomDistribution,
        description="Distribution of Bloom taxonomy levels across all questions. "
                    "Must sum to 100%. Defaults to 20/30/30/20.",
    )
    user_prompt: str | None = Field(
        default=None,
        max_length=5000,
        description="Free-text prompt describing the exam requirements in Vietnamese. "
                    "Used by the Planner Agent to clarify ambiguous requests.",
    )
    extra_instructions: str | None = Field(
        None,
        max_length=2000,
        description="Additional instructions passed down to all sub-agents. "
                    "Use this for special requirements (e.g., 'focus on diagrams', "
                    "'avoid numerical problems').",
    )
    instructions: str | None = Field(
        None,
        max_length=1000,
        description="Custom exam instructions displayed at the top of the paper "
                    "(e.g., 'Đề thi gồm 5 câu, thời gian 45 phút').",
    )
    time_limit_minutes: int | None = Field(
        None,
        ge=5,
        le=300,
        description="Time limit in minutes. Range: 5–300. Optional.",
    )
    output_language: str = Field(
        default="vi",
        description="Language for question content and instructions. Options: 'vi' (Vietnamese), "
                    "'en' (English). Default: 'vi'.",
    )
    strict_scope_flag: bool = Field(
        default=True,
        description="If True: all question content must be traceable to the document. "
                    "If False: the AI may include questions from general knowledge. Default: True.",
    )


class GenerationStep(BaseModel):
    """
    Schema matching frontend's GenerationStep interface.

    Represents a single step in the multi-agent generation pipeline.
    """
    step: int = Field(..., description="Step number (0-indexed).")
    name: str = Field(..., description="Human-readable step name.")
    status: str = Field(default="pending", description="Step status: 'pending', 'running', 'completed', 'failed'.")
    message: str | None = Field(None, description="Optional message or description.")
    progress: float | None = Field(None, description="Progress percentage (0.0–1.0).")


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
    """
    Schema for a single partial edit request applied during regeneration.

    - **question_ids**: List of question UUIDs to target with this edit
    - **edit_type**: Type of edit: 'regenerate', 'edit_text', 'edit_options', 'edit_answer', 'edit_bloom', 'delete', 'lock', 'unlock'
    - **new_content**: New question text (for edit_type='edit_text')
    - **new_options**: New MCQ options (for edit_type='edit_options')
    - **new_correct_answer**: New correct answer key (for edit_type='edit_answer')
    - **new_bloom_level**: New Bloom level (for edit_type='edit_bloom')
    """
    question_ids: list[str] = Field(
        ...,
        description="List of question UUIDs to target with this edit.",
    )
    edit_prompt: str | None = Field(
        None,
        description="Natural-language description of the edit.",
    )
    range_start: int | None = Field(
        None,
        description="Start index for range-based edits (inclusive).",
    )
    range_end: int | None = Field(
        None,
        description="End index for range-based edits (inclusive).",
    )
    edit_type: str = Field(
        default="regenerate",
        description="Type of edit: 'regenerate', 'edit_text', 'edit_options', "
                    "'edit_answer', 'edit_bloom', 'delete', 'lock', 'unlock'.",
    )
    new_content: str | None = Field(
        None,
        description="New question text. Used when edit_type='edit_text'.",
    )
    new_options: list[dict] | None = Field(
        None,
        description="New MCQ options [{label, text}]. Used when edit_type='edit_options'.",
    )
    new_correct_answer: str | None = Field(
        None,
        description="New correct answer key. Used when edit_type='edit_answer'.",
    )
    new_bloom_level: str | None = Field(
        None,
        description="New Bloom level. Used when edit_type='edit_bloom'.",
    )


# ── Question Response ─────────────────────────────────────────────────────────

class MCQOption(BaseModel):
    """Schema for MCQ option."""
    label: str = Field(..., description="Option label: 'A', 'B', 'C', 'D', etc.")
    text: str = Field(..., description="Option text/content.")


class SourceEvidence(BaseModel):
    """
    Schema for source evidence — the document chunk a question was grounded in.

    Used by the Validator Agent to verify that questions are traceable to source material.
    """
    document_id: str | None = Field(None, description="Source document UUID.")
    section_id: str | None = Field(None, description="Source section identifier.")
    chunk_id: str | None = Field(None, description="Source Pinecone chunk UUID.")
    chapter_number: int | None = Field(None, description="Chapter number in the source document.")
    page: int | None = Field(None, description="Page number in the source document.")
    parent_heading: str | None = Field(None, description="Nearest heading above the source text.")
    role: str | None = Field(
        None,
        description="Role of the evidence: 'primary', 'supporting', 'context'.",
    )
    score: float | None = Field(
        None,
        description="Relevance score from the retrieval step (0.0–1.0).",
    )
    text_preview: str | None = Field(
        None,
        description="Short preview of the source text (first 200 chars).",
    )


class QuestionResponse(BaseModel):
    """
    Schema for a question in the API response.

    Represents a single exam question with all its metadata including
    Bloom level, difficulty, source evidence, and validation status.
    """
    id: str = Field(..., description="Unique question identifier (UUID).")
    question_number: int = Field(..., description="Question number as displayed in the exam paper.")
    blueprint_cell_key: str | None = Field(None, description="Key of the blueprint cell this question fulfills.")
    question_type: str = Field(..., description="Question type: 'mcq' or 'essay'.")
    bloom_level: str = Field(..., description="Bloom taxonomy level: 'nhan_biet', 'thong_hieu', 'van_dung', 'van_dung_cao'.")
    difficulty_score: float | None = Field(None, description="Difficulty score (0.0–1.0).")
    content: str = Field(..., description="Question text content.")
    options: list[MCQOption] | None = Field(None, description="MCQ options. Null for essay questions.")
    correct_answer: str = Field(..., description="Correct answer key ('A', 'B', 'C', 'D' for MCQ; text for essay).")
    rubric: dict | None = Field(None, description="Essay grading rubric with criteria and point values.")
    explanation: str | None = Field(None, description="Explanation for the correct answer.")
    source_citations: list[str] = Field(
        default_factory=list,
        description="List of source document references (formatted strings).",
    )
    source_evidence: list[SourceEvidence] = Field(
        default_factory=list,
        description="Detailed source evidence from retrieval step.",
    )
    scope_tags: list[str] = Field(
        default_factory=list,
        description="Chapter/section tags indicating which scope unit this question covers.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Validation warnings for this question (e.g., 'ambiguous_wording', 'out_of_scope').",
    )
    verification_status: str | None = Field(
        None,
        description="Verification result: 'passed', 'failed', 'warning', or null.",
    )
    is_human_edited: bool = Field(
        default=False,
        description="True if this question was manually edited by the teacher.",
    )
    is_locked: bool = Field(
        default=False,
        description="True if this question is locked and will not be regenerated.",
    )
    is_validated: bool = Field(
        default=False,
        description="True if this question passed the Validator Agent checks.",
    )
    quality_score_detail: dict | None = Field(
        None,
        description="Detailed quality breakdown from the Validator Agent.",
    )
    grounding_report_detail: dict | None = Field(
        None,
        description="Detailed grounding report from the Validator Agent.",
    )
    error_categories: list[str] = Field(
        default_factory=list,
        description="Error categories detected by the Validator Agent.",
    )
    created_at: datetime | None = Field(None, description="Question creation timestamp (UTC).")


# ── Edit Operation ─────────────────────────────────────────────────────────────

class EditOperationResponse(BaseModel):
    """
    Schema for an edit operation record.

    Logs every edit applied to an exam (regenerate, inline edit, prompt edit, etc.).
    """
    id: str = Field(..., description="Unique operation identifier.")
    edit_type: str = Field(..., description="Type: 'regenerate', 'edit_text', 'edit_options', etc.")
    target_question_id: str | None = Field(None, description="Target question UUID (for single-question edits).")
    target_slots: list[int] = Field(
        default_factory=list,
        description="Target blueprint slot indices (for blueprint-level edits).",
    )
    prompt_used: str | None = Field(None, description="Original prompt or instruction used for this edit.")
    created_at: datetime = Field(..., description="Operation timestamp (UTC).")


# ── Feedback Event ─────────────────────────────────────────────────────────────

class FeedbackEventResponse(BaseModel):
    """
    Schema for a feedback event.

    Tracks all human and system signals throughout the exam generation lifecycle:
    blueprint approval/rejection, question edits, regeneration requests, etc.
    """
    id: str = Field(..., description="Unique event identifier.")
    exam_id: str = Field(..., description="Exam UUID this event belongs to.")
    exam_title: str | None = Field(None, description="Exam title at the time of the event.")
    exam_version_id: str | None = Field(None, description="Exam version UUID at the time of the event.")
    version_number: int | None = Field(None, description="Exam version number at the time of the event.")
    actor_id: str | None = Field(None, description="UUID of the user who triggered this event (human or 'system').")
    signal_type: str = Field(
        ...,
        description="Signal type: 'publish', 'regenerate_requested', 'edit_direct', "
                    "'restore', 'reject_blueprint', 'approve_blueprint', etc.",
    )
    severity: str = Field(
        ...,
        description="Severity: 'info', 'warning', 'error'. "
                    "'error' indicates a validation failure.",
    )
    workflow_stage: str | None = Field(
        None,
        description="Workflow stage: 'generation', 'review', 'export'.",
    )
    event_stage: str | None = Field(None, description="Alias of workflow_stage.")
    event_source: str | None = Field(
        None,
        description="Event source: 'human', 'agent', 'system'.",
    )
    source_type: str | None = Field(None, description="Source type identifier.")
    source_ref: str | None = Field(None, description="Reference to the source object.")
    review_status: str | None = Field(
        None,
        description="Review outcome: 'accepted', 'rejected', 'corrected', 'pending'.",
    )
    reviewed_by_human: bool = Field(
        default=False,
        description="True if this event was triggered by a human action.",
    )
    question_id: str | None = Field(None, description="Related question UUID (if applicable).")
    error_categories: list[str] = Field(
        default_factory=list,
        description="Error categories for validation/error events.",
    )
    before_snapshot_ref: str | None = Field(None, description="Reference to state before this event.")
    after_snapshot_ref: str | None = Field(None, description="Reference to state after this event.")
    linked_eval_sample_id: str | None = Field(None, description="Linked evaluation sample ID.")
    payload: dict | None = Field(None, description="Additional event-specific metadata.")
    created_at: datetime = Field(..., description="Event timestamp (UTC).")


# ── Exam Version ─────────────────────────────────────────────────────────────

class ExamVersionResponse(BaseModel):
    """
    Schema for an exam version (snapshot).

    Each version captures the exam state at a point in time, enabling
    version comparison and restoration.
    """
    id: str = Field(..., description="Version UUID.")
    version_number: int = Field(..., description="Version number (monotonically increasing).")
    status: str = Field(..., description="Version status: 'draft', 'under_review', 'published'.")
    created_by: str = Field(..., description="UUID of the user who created this version.")
    parent_version_id: str | None = Field(
        None,
        description="UUID of the parent version (null for initial version).",
    )
    change_summary: str | None = Field(None, description="Human-readable summary of changes in this version.")
    created_at: datetime = Field(..., description="Version creation timestamp (UTC).")
    questions: list[QuestionResponse] = Field(
        default_factory=list,
        description="Questions at the time of this version snapshot.",
    )
    edit_operations: list[EditOperationResponse] = Field(
        default_factory=list,
        description="Edit operations applied in this version.",
    )
    feedback_events: list[FeedbackEventResponse] = Field(
        default_factory=list,
        description="Feedback events associated with this version.",
    )


# ── Exam Responses ─────────────────────────────────────────────────────────────

class ExamListResponse(BaseModel):
    """
    Exam summary for list view (GET /exams).
    """
    id: str = Field(..., description="Exam UUID.")
    title: str | None = Field(None, description="Exam title.")
    document_id: str | None = Field(None, description="Source document UUID.")
    course_id: str | None = Field(None, description="Course UUID (if associated).")
    exam_type: str = Field(..., description="Exam type: 'mcq', 'essay', or 'mixed'.")
    difficulty: str = Field(..., description="Difficulty level: 'easy', 'medium', or 'hard'.")
    status: str = Field(..., description="Status: 'draft', 'under_review', 'published'.")
    chapters: list[int] = Field(default_factory=list, description="Chapter numbers included.")
    total_questions: int = Field(default=0, description="Total question count.")
    strict_scope_flag: bool = Field(
        default=True,
        description="True if strict document grounding is enforced.",
    )
    quality_score: float | None = Field(None, description="Overall quality score (0.0–1.0).")
    current_version_number: int | None = Field(None, description="Current version number.")
    version_count: int = Field(default=0, description="Total number of versions created.")
    verifier_pass_rate: float | None = Field(
        None,
        description="Percentage of questions that passed Validator Agent checks.",
    )
    evidence_coverage_rate: float | None = Field(
        None,
        description="Percentage of questions with source evidence.",
    )
    warning_count: int = Field(default=0, description="Total validation warnings.")
    regenerate_count: int = Field(default=0, description="Total regeneration requests.")
    human_edit_count: int = Field(default=0, description="Total manual edits.")
    feedback_event_count: int = Field(
        default=0,
        description="Total feedback events logged for this exam.",
    )
    created_at: datetime | None = Field(None, description="Creation timestamp (UTC).")
    updated_at: datetime | None = Field(None, description="Last update timestamp (UTC).")


class ExamResponse(BaseModel):
    """
    Full exam detail response (GET /exams/{id}).
    """
    id: str = Field(..., description="Exam UUID.")
    title: str | None = Field(None, description="Exam title.")
    document_id: str | None = Field(None, description="Source document UUID.")
    course_id: str | None = Field(None, description="Course UUID (if associated).")
    exam_type: str = Field(..., description="Exam type: 'mcq', 'essay', or 'mixed'.")
    difficulty: str = Field(..., description="Difficulty level.")
    status: str = Field(..., description="Status: 'draft', 'under_review', 'published'.")
    chapters: list[int] = Field(default_factory=list, description="Chapter numbers included.")
    variant_number: int = Field(default=1, description="Variant number for multi-variant exams.")
    total_questions: int = Field(default=0, description="Total question count.")
    instructions: str | None = Field(None, description="Exam instructions shown at the top of the paper.")
    output_language: str = Field(default="vi", description="Output language: 'vi' or 'en'.")
    strict_scope_flag: bool = Field(
        default=True,
        description="True if strict document grounding is enforced.",
    )
    quality_score: float | None = Field(None, description="Overall quality score (0.0–1.0).")
    created_at: datetime | None = Field(None, description="Creation timestamp (UTC).")
    updated_at: datetime | None = Field(None, description="Last update timestamp (UTC).")
    published_at: datetime | None = Field(None, description="Publish timestamp (UTC).")
    questions: list[QuestionResponse] = Field(
        default_factory=list,
        description="Full list of exam questions.",
    )
    exam_spec: dict | None = Field(None, description="Internal exam specification dict.")
    blueprint: dict | None = Field(None, description="Blueprint: list of slots with Bloom × chapter distribution.")
    selected_scope: list[dict] | None = Field(None, description="Selected scope units (chapters/sections).")
    quality_scores: list[dict] | None = Field(
        None,
        description="Per-question quality scores from the Validator Agent.",
    )
    grounding_reports: list[dict] | None = Field(
        None,
        description="Per-question grounding reports from the Validator Agent.",
    )
    duplicate_groups: list[dict] | None = Field(
        None,
        description="Groups of duplicate questions detected by the Dedup Checker.",
    )
    provider_logs: list[dict] | None = Field(
        None,
        description="API cost and token usage logs per agent call.",
    )
    edit_impact_level: str | None = Field(None, description="Impact level of the most recent edit.")
    edit_history: list[dict] | None = Field(None, description="History of all edit operations.")
    feedback_events: list[dict] | None = Field(
        None,
        description="All feedback events for this exam.",
    )
    current_version: dict | None = Field(None, description="Current version metadata.")
    versions: list[dict] = Field(
        default_factory=list,
        description="All version snapshots for this exam.",
    )


class ErrorCategoryCount(BaseModel):
    """
    Schema for error category count.
    """
    category: str = Field(..., description="Error category label (e.g., 'ambiguous_wording', 'out_of_scope').")
    count: int = Field(..., description="Number of occurrences of this error category.")


class NamedCount(BaseModel):
    """Schema for named count."""
    name: str = Field(..., description="Name of the item (e.g., signal type).")
    count: int = Field(..., description="Number of occurrences.")


class QualitySummaryResponse(BaseModel):
    """
    Quality metrics summary across all user exams.

    Aggregated from all Exam records and FeedbackEvent records belonging to the user.
    Useful for dashboard analytics and teacher self-improvement.
    """
    documents_active: int = Field(default=0, description="Number of documents in 'completed' status.")
    exams_generated: int = Field(default=0, description="Total number of exams generated.")
    question_count: int = Field(default=0, description="Total questions across all exams.")
    verifier_pass_rate: float = Field(
        default=0.0,
        description="Average percentage of questions that passed Validator Agent checks.",
    )
    verifier_warning_rate: float = Field(
        default=0.0,
        description="Average percentage of questions with validation warnings.",
    )
    evidence_coverage_rate: float = Field(
        default=0.0,
        description="Average percentage of questions with source evidence.",
    )
    scope_violation_rate: float = Field(
        default=0.0,
        description="Average percentage of questions flagged for out-of-scope content.",
    )
    avg_regenerate_count: float = Field(
        default=0.0,
        description="Average number of regeneration requests per exam.",
    )
    avg_human_edit_count: float = Field(
        default=0.0,
        description="Average number of manual edits per exam.",
    )
    version_churn: float = Field(
        default=0.0,
        description="Average number of versions created per exam.",
    )
    top_error_categories: list[ErrorCategoryCount] = Field(
        default_factory=list,
        description="Top 5 most frequent error categories across all exams.",
    )
    recent_warnings: list[dict] = Field(
        default_factory=list,
        description="10 most recent warning/error feedback events.",
    )
    last_updated_at: datetime | None = Field(
        None,
        description="Timestamp when this summary was last computed.",
    )


class FeedbackStoreSummaryResponse(BaseModel):
    """
    Feedback store summary across all user exams.

    Tracks human review actions and system signals for analytics and improvement.
    """
    total_events: int = Field(default=0, description="Total feedback events across all exams.")
    reviewed_by_human_count: int = Field(
        default=0,
        description="Number of events triggered by a human (vs. system).",
    )
    accepted_count: int = Field(
        default=0,
        description="Number of questions accepted after review.",
    )
    rejected_count: int = Field(
        default=0,
        description="Number of questions rejected during review.",
    )
    corrected_count: int = Field(
        default=0,
        description="Number of questions corrected (edited then accepted).",
    )
    linked_eval_count: int = Field(
        default=0,
        description="Number of events linked to an evaluation sample.",
    )
    top_signal_types: list[NamedCount] = Field(
        default_factory=list,
        description="Most frequent signal types (e.g., 'publish', 'regenerate_requested').",
    )
    top_error_categories: list[ErrorCategoryCount] = Field(
        default_factory=list,
        description="Most frequent error categories in reviewed questions.",
    )
    recent_events: list[dict] = Field(
        default_factory=list,
        description="10 most recent feedback events.",
    )
    last_updated_at: datetime | None = Field(
        None,
        description="Timestamp when this summary was last computed.",
    )


class ExamGenerateResponse(BaseModel):
    """
    Response from POST /api/v1/exams/generate.

    - **exam_id**: UUID of the newly created exam record
    - **job_id**: Unique job identifier for tracking
    - **websocket_url**: WebSocket URL for real-time streaming, e.g. ws://localhost:8000/ws/exam/{exam_id}
    """
    exam_id: str = Field(..., description="UUID of the newly created exam record.")
    job_id: str = Field(..., description="Unique job identifier for this generation job.")
    message: str = Field(
        default="Exam generation started.",
        description="Human-readable status message.",
    )
    websocket_url: str | None = Field(
        None,
        description="WebSocket URL for real-time event streaming, e.g. ws://localhost:8000/ws/exam/{exam_id}",
    )


class EditQuestionRequest(BaseModel):
    """
    Schema for inline editing of a single question.

    - **question_id**: UUID of the question to edit
    - **updates**: Dict of fields to update. Supported keys:
        `content`, `options`, `correct_answer`, `rubric`, `bloom_level`,
        `difficulty_score`, `explanation`, `source_citations`

    Example:
    ```json
    {
      "question_id": "550e8400-e29b-41d4-a716-446655440003",
      "updates": {
        "content": "Nội dung câu hỏi đã chỉnh sửa...",
        "correct_answer": "D"
      }
    }
    ```
    """
    question_id: str = Field(
        ...,
        description="UUID of the question to edit.",
    )
    updates: dict[str, Any] = Field(
        ...,
        description="Partial update dict. Only provided fields are modified. "
                    "Supported keys: content, options, correct_answer, rubric, bloom_level, "
                    "difficulty_score, explanation, source_citations, is_locked, is_human_edited.",
    )


class PromptEditRequest(BaseModel):
    """
    Schema for natural-language prompt-based exam editing.

    - **prompt**: Free-text instruction describing what to change.
      Examples:
      - "Đổi câu hỏi số 3 thành dạng bài tập về vectơ"
      - "Thêm 2 câu Vận dụng cao vào phần Sóng cơ"
      - "Sửa lại đáp án câu 5 thành C"
    """
    prompt: str = Field(
        ...,
        min_length=5,
        max_length=5000,
        description="Natural-language edit instruction. "
                    "The Planner Agent analyzes this and determines which questions "
                    "to modify and how.",
    )


class RegenerateRequest(BaseModel):
    """
    Schema for question regeneration.

    - **question_ids**: Specific questions to regenerate. If null, all questions are regenerated.
    - **scope**: Override scope for regenerated questions (optional).
    """
    question_ids: list[str] | None = Field(
        None,
        description="List of question UUIDs to regenerate. "
                    "If null or empty, all questions are regenerated.",
    )
    scope: list[str] | None = Field(
        None,
        description="Override scope (chapters/sections) for regenerated questions. "
                    "If null, uses the original exam scope.",
    )


class ExportFormat(BaseModel):
    """
    Schema for export format selection (G12).

    - **format**: Output format — 'pdf' or 'docx'
    - **include_answers**: `false` = bản học sinh, `true` = bản giáo viên
    """
    format: Literal["pdf", "docx"] = Field(
        ...,
        description="Output file format. 'pdf' uses WeasyPrint; 'docx' uses python-docx.",
    )
    include_answers: bool = Field(
        default=False,
        description="`false` = bản học sinh (no answer key). "
                    "`true` = bản giáo viên (includes answer key, explanations, rubric).",
    )


class BlueprintApprovalRequest(BaseModel):
    """
    Schema for blueprint approval at HITL Checkpoint 1.

    - **approved**: Must be `true` to unblock pipeline. Set to `false` to cancel.
    - **feedback**: Optional note saved with the approval event.
    """
    approved: bool = Field(
        ...,
        description="Set to `true` to approve the blueprint and unblock question generation. "
                    "Set to `false` to cancel the generation.",
    )
    feedback: str | None = Field(
        None,
        max_length=2000,
        description="Optional approval note saved with the FeedbackEvent. "
                    "Use this to record why the blueprint was approved.",
    )


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


# ── HITL Request Schemas ───────────────────────────────────────────────────────

class BlueprintRejectionRequest(BaseModel):
    """
    Schema for blueprint rejection with feedback (G8).

    - **feedback**: Teacher feedback describing what to change in the blueprint.
      Passed to OutlineAgent as additional instruction. Minimum 5 characters.
    """
    feedback: str = Field(
        ...,
        min_length=5,
        max_length=5000,
        description="Teacher feedback for the outline. "
                    "Describe what needs to be changed in the blueprint "
                    "(e.g., 'Chương 3 có tỷ trọng cao hơn, bổ sung thêm câu Vận dụng cao').",
    )

    class Config:
        from_attributes = True


# ── HITL Response Schemas ──────────────────────────────────────────────────────

class BlueprintApprovalResponse(BaseModel):
    """
    Response from POST /api/v1/exams/{id}/approve-blueprint.

    Returned when the blueprint is approved and the pipeline is unblocked.
    """
    status: str = Field(
        default="approved",
        description="Always 'approved' on success.",
    )
    message: str = Field(
        default="Blueprint đã được phê duyệt. Bắt đầu sinh câu hỏi.",
        description="Human-readable confirmation message.",
    )


class BlueprintRejectionResponse(BaseModel):
    """
    Response from POST /api/v1/exams/{id}/reject-blueprint (G8).

    The pipeline re-runs the outline with the provided feedback and dispatches
    a Celery task for the full pipeline.
    """
    status: str = Field(
        default="rejected_with_feedback",
        description="'rejected_with_feedback' when feedback was applied.",
    )
    blueprint: list[dict] = Field(
        default_factory=list,
        description="New blueprint regenerated with the teacher's feedback. "
                    "Emitted as HITL Checkpoint 1 via WebSocket.",
    )
    distribution_summary: dict = Field(
        default_factory=dict,
        description="Bloom distribution summary for the new blueprint.",
    )
    message: str = Field(
        default="Blueprint đã được điều chỉnh theo phản hồi của bạn. Đề đang được sinh lại.",
        description="Human-readable status message.",
    )


class ReviewDataResponse(BaseModel):
    """
    Response from GET /api/v1/exams/{id}/review-data (HITL Checkpoint 2).

    Returns the complete data needed to render the exam review screen:
    questions, per-question quality scores, cost report, feedback events,
    rejection history, and exam metadata.
    """
    exam_id: str = Field(..., description="Exam UUID.")
    title: str | None = Field(None, description="Exam title.")
    status: str = Field(..., description="Current exam status.")
    questions: list[dict] = Field(
        default_factory=list,
        description="Full list of exam questions with all fields.",
    )
    blueprint: dict | None = Field(None, description="Blueprint: list of slots with Bloom distribution.")
    exam_config: dict | None = Field(None, description="Original exam configuration.")
    quality_scores: list[dict] = Field(
        default_factory=list,
        description="Per-question quality scores from the Validator Agent.",
    )
    cost_report: dict = Field(
        default_factory=dict,
        description="Cost report from Redis session: breakdown per agent, total cost in USD.",
    )
    feedback_events: list[dict] = Field(
        default_factory=list,
        description="All feedback events for this exam.",
    )
    rejection_history: list[dict] = Field(
        default_factory=list,
        description="History of blueprint rejections (G8) with timestamps.",
    )
    instructions: str | None = Field(None, description="Exam instructions.")
    scope: list[str] = Field(default_factory=list, description="Selected scope (chapters/sections).")
    exam_type: str = Field(default="mixed", description="Exam type.")
    total_questions: int = Field(default=0, description="Total question count.")
    warning_count: int = Field(default=0, description="Total validation warnings.")
    regenerate_count: int = Field(default=0, description="Total regeneration requests.")
    human_edit_count: int = Field(default=0, description="Total manual edits.")
    version_count: int = Field(default=1, description="Total number of versions created.")


class ExportPreviewResponse(BaseModel):
    """
    Response from GET /api/v1/exams/{id}/preview (HITL Checkpoint 3).

    Returns rendered HTML for preview — does NOT produce a PDF file.
    Frontend can display this inline before the user confirms export.
    """
    exam_id: str = Field(..., description="Exam UUID.")
    title: str = Field(default="Đề kiểm tra", description="Exam title.")
    scope: list[str] = Field(default_factory=list, description="Selected scope.")
    total_questions: int = Field(default=0, description="Total question count.")
    mcq_count: int = Field(default=0, description="Number of MCQ questions.")
    essay_count: int = Field(default=0, description="Number of essay questions.")
    preview_html: str = Field(
        ...,
        description="Full rendered HTML with current parameters (include_answers, include_blueprint).",
    )
    student_preview_html: str = Field(
        ...,
        description="HTML preview without answers (bản học sinh).",
    )
    teacher_preview_html: str = Field(
        ...,
        description="HTML preview with answers and rubric (bản giáo viên).",
    )
    include_answers: bool = Field(
        default=False,
        description="Whether answers are included in preview_html.",
    )
    include_blueprint: bool = Field(
        default=False,
        description="Whether the Bloom distribution table is included.",
    )
    word_count: int = Field(
        default=0,
        description="Character count of the preview HTML.",
    )
    estimated_pdf_pages: int = Field(
        default=1,
        description="Estimated PDF page count based on question count.",
    )


class ExamReviewRequest(BaseModel):
    """
    Schema for full exam review submission at HITL Checkpoint 2.

    If **approved=true**: exam is marked ready for export.
    If **approved=false**: a Celery task is dispatched to regenerate with feedback.

    Example request:
    ```json
    {
      "approved": false,
      "feedback": "Câu 3 và câu 7 chưa chính xác, xin điều chỉnh lại nội dung",
      "direct_edits": [
        {"question_id": "MCQ_003", "updates": {"content": "Nội dung mới..."}}
      ]
    }
    ```
    """
    approved: bool = Field(
        ...,
        description="`true` = approve exam and mark ready for export. "
                    "`false` = request changes and regenerate with feedback.",
    )
    feedback: str | None = Field(
        None,
        max_length=5000,
        description="Teacher feedback for revision. Required when approved=false. "
                    "Passed down to the Builder Agent as additional instruction.",
    )
    direct_edits: list[dict] | None = Field(
        None,
        description="Inline edits to apply to specific questions before regeneration. "
                    "Each entry: {question_id: str, updates: dict}. "
                    "Only applied when approved=false.",
    )

    class Config:
        from_attributes = True


class ExamReviewResponse(BaseModel):
    """
    Response from POST /api/v1/exams/{id}/submit-review (HITL Checkpoint 2).

    - **approved=true**: Exam is marked ready for export.
    - **approved=false**: A Celery task is dispatched to regenerate with feedback.
    """
    status: str = Field(
        ...,
        description="'approved' or 'regenerating'.",
    )
    message: str = Field(
        ...,
        description="Human-readable status message.",
    )
    exam_id: str | None = Field(
        None,
        description="Exam UUID. Present when status='approved'.",
    )
    checkpoint: int | None = Field(
        None,
        description="HITL checkpoint number. Always 2.",
    )


# Update forward reference
ExamPartialRegenerateRequest.model_rebuild()
