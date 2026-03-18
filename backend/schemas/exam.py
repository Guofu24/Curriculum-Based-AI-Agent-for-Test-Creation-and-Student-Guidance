from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from core.mvp import DEFAULT_OUTPUT_LANGUAGE, DEFAULT_QUESTION_TYPE, normalize_mvp_language


class DifficultyDistribution(BaseModel):
    easy: int = 0
    medium: int = 0
    hard: int = 0


class QuestionDistribution(BaseModel):
    mcq: DifficultyDistribution = Field(default_factory=DifficultyDistribution)


class ScopeUnitPayload(BaseModel):
    scope_id: str | None = None
    section_id: str | None = None
    scope_type: str = "chapter"
    title: str | None = None
    chapter_number: int = 0
    page_from: int | None = None
    page_to: int | None = None
    tags: list[str] = Field(default_factory=list)


class AdvancedConstraints(BaseModel):
    strict_grounding: bool = True
    allow_applied_questions: bool = False
    grade_level_scope: str | None = None
    creativity_level: float = Field(default=0.0, ge=0.0, le=1.0)
    bloom_levels: list[str] = Field(
        default_factory=lambda: ["remember", "understand", "apply", "analyze"]
    )
    max_concurrency: int = Field(default=1, ge=1, le=1)

    @model_validator(mode="after")
    def harden_mvp(self):
        self.strict_grounding = True
        self.allow_applied_questions = False
        self.creativity_level = 0.0
        self.max_concurrency = 1
        return self


class ExamGenerationRequest(BaseModel):
    document_id: str | None = None
    course_id: str | None = None
    chapters: list[int] = Field(default_factory=list)
    scope: list[ScopeUnitPayload] = Field(default_factory=list)
    prompt: str = ""
    instructions: str = ""
    total_questions: int | None = Field(default=None, ge=1, le=100)
    question_type: str = DEFAULT_QUESTION_TYPE
    exam_type: str = "mcq"
    difficulty: str = "custom"
    question_distribution: QuestionDistribution = Field(default_factory=QuestionDistribution)
    num_variants: int = Field(default=1, ge=1, le=1)
    gradually_increasing: bool = False
    constraints: AdvancedConstraints = Field(default_factory=AdvancedConstraints)
    time_limit_minutes: int | None = None
    output_language: str = DEFAULT_OUTPUT_LANGUAGE
    bloom_distribution: dict[str, int] = Field(default_factory=dict)
    formatting_preferences: dict = Field(default_factory=dict)

    @field_validator("exam_type")
    @classmethod
    def validate_exam_type(cls, value: str) -> str:
        normalized = (value or "mcq").strip().lower()
        if normalized != "mcq":
            raise ValueError("MVP hien tai chi ho tro exam_type='mcq'")
        return normalized

    @field_validator("question_type")
    @classmethod
    def validate_question_type(cls, value: str) -> str:
        normalized = (value or DEFAULT_QUESTION_TYPE).strip().lower()
        if normalized not in {"mcq", DEFAULT_QUESTION_TYPE}:
            raise ValueError("MVP hien tai chi ho tro trac nghiem 1 dap an dung")
        return DEFAULT_QUESTION_TYPE

    @field_validator("output_language")
    @classmethod
    def validate_output_language(cls, value: str) -> str:
        return normalize_mvp_language(value)

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: str) -> str:
        normalized = (value or "custom").strip().lower()
        if normalized not in {"basic", "advanced", "application", "high_application", "custom"}:
            raise ValueError("difficulty khong hop le")
        return normalized

    @model_validator(mode="after")
    def normalize_scope(self):
        if not self.document_id and not self.course_id:
            raise ValueError("Provide document_id or course_id")

        if self.num_variants != 1:
            raise ValueError("MVP hien tai chi ho tro 1 exam version cho moi lan generate")

        if not self.scope and self.chapters:
            self.scope = [
                ScopeUnitPayload(
                    scope_id=f"chapter:{chapter}",
                    section_id=None,
                    scope_type="chapter",
                    title=f"Chapter {chapter}",
                    chapter_number=chapter,
                    tags=[f"chapter:{chapter}"],
                )
                for chapter in self.chapters
            ]

        if self.total_questions is None:
            total_mcq = (
                int(self.question_distribution.mcq.easy)
                + int(self.question_distribution.mcq.medium)
                + int(self.question_distribution.mcq.hard)
            )
            if total_mcq <= 0:
                raise ValueError("total_questions phai lon hon 0")
            self.total_questions = total_mcq

        self.gradually_increasing = False
        return self

    def to_mvp_runtime_payload(self) -> dict:
        mcq_distribution = {
            "easy": int(self.question_distribution.mcq.easy),
            "medium": int(self.question_distribution.mcq.medium),
            "hard": int(self.question_distribution.mcq.hard),
        }
        return {
            "document_id": self.document_id,
            "course_id": self.course_id,
            "chapters": list(self.chapters or []),
            "scope": [item.model_dump() for item in self.scope],
            "prompt": self.prompt,
            "instructions": self.instructions,
            "total_questions": self.total_questions,
            "question_type": DEFAULT_QUESTION_TYPE,
            "exam_type": "mcq",
            "difficulty": self.difficulty,
            "question_distribution": {"mcq": mcq_distribution},
            "num_variants": 1,
            "gradually_increasing": False,
            "constraints": {
                "strict_grounding": True,
                "allow_applied_questions": False,
                "grade_level_scope": self.constraints.grade_level_scope,
                "creativity_level": 0.0,
                "bloom_levels": list(self.constraints.bloom_levels or []),
                "max_concurrency": 1,
            },
            "time_limit_minutes": self.time_limit_minutes,
            "output_language": DEFAULT_OUTPUT_LANGUAGE,
            "bloom_distribution": dict(self.bloom_distribution or {}),
            "formatting_preferences": dict(self.formatting_preferences or {}),
            "strict_scope": True,
        }


class MCQOption(BaseModel):
    label: str
    text: str


class SourceEvidenceResponse(BaseModel):
    document_id: str | None = None
    section_id: str | None = None
    chunk_id: str
    chapter_number: int | None = None
    page: int | None = None
    parent_heading: str | None = None
    role: str | None = None
    score: float | None = None
    text_preview: str | None = None


class QuestionResponse(BaseModel):
    id: str
    question_number: int
    blueprint_cell_key: str | None = None
    question_type: str
    bloom_level: str
    difficulty_score: float
    content: str
    options: list[MCQOption] | None = None
    correct_answer: str
    rubric: dict | None = None
    explanation: str | None = None
    source_citations: list[str] | None = None
    source_evidence: list[SourceEvidenceResponse] | None = None
    scope_tags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    verification_status: str | None = None
    is_human_edited: bool = False
    is_locked: bool = False
    is_validated: bool = False
    quality_score_detail: dict | None = None
    grounding_report_detail: dict | None = None

    model_config = {"from_attributes": True}


class BlueprintCellResponse(BaseModel):
    cell_id: str
    section_id: str | None = None
    scope_unit: dict
    question_type: str
    bloom_level: str
    target_count: int
    generated_count: int = 0
    priority: int = 0
    overgenerate_count: int = 0


class ExamSpecResponse(BaseModel):
    course_id: str | None = None
    document_id: str | None = None
    exam_type: str
    question_type: str = DEFAULT_QUESTION_TYPE
    total_questions: int
    time_limit_minutes: int | None = None
    output_language: str = DEFAULT_OUTPUT_LANGUAGE
    instructions: str = ""
    normalized_instructions: str = ""
    strict_scope_flag: bool = True
    selected_scope: list[dict] = Field(default_factory=list)
    selected_section_ids: list[str] = Field(default_factory=list)
    bloom_distribution: dict[str, int] = Field(default_factory=dict)
    question_mix: dict[str, int] = Field(default_factory=dict)
    formatting_preferences: dict = Field(default_factory=dict)
    source_prompt: str = ""


class ExamBlueprintResponse(BaseModel):
    title: str
    total_questions: int
    difficulty_distribution: dict = Field(default_factory=dict)
    bloom_distribution: dict = Field(default_factory=dict)
    cells: list[BlueprintCellResponse] = Field(default_factory=list)


class ExamResponse(BaseModel):
    id: str
    title: str
    document_id: str
    course_id: str | None = None
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = Field(default_factory=list)
    variant_number: int
    total_questions: int
    instructions: str | None = None
    output_language: str = DEFAULT_OUTPUT_LANGUAGE
    strict_scope_flag: bool = True
    quality_score: float | None = None
    created_at: datetime
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
    feedback_events: list[FeedbackEventResponse] | None = None
    current_version: ExamVersionResponse | None = None
    versions: list[ExamVersionResponse] | None = None

    model_config = {"from_attributes": True}


class ExamListResponse(BaseModel):
    id: str
    title: str
    document_id: str
    course_id: str | None = None
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = Field(default_factory=list)
    total_questions: int
    strict_scope_flag: bool = True
    quality_score: float | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class QuestionEditRequest(BaseModel):
    question_ids: list[str] = Field(default_factory=list)
    edit_prompt: str | None = None
    range_start: int | None = None
    range_end: int | None = None
    edit_type: str = "regenerate"
    new_content: str | None = None
    new_options: list[MCQOption] | None = None
    new_correct_answer: str | None = None
    new_bloom_level: str | None = None

    @field_validator("edit_type")
    @classmethod
    def normalize_edit_type(cls, value: str) -> str:
        normalized = (value or "regenerate").strip().lower()
        if normalized not in {
            "regenerate",
            "edit_text",
            "edit_options",
            "edit_answer",
            "edit_bloom",
            "lock",
            "unlock",
            "delete",
        }:
            raise ValueError("Unsupported edit_type")
        return normalized

    @model_validator(mode="after")
    def validate_targeting(self):
        has_ids = bool(self.question_ids)
        has_range = self.range_start is not None and self.range_end is not None
        if not has_ids and not has_range and self.edit_type != "regenerate":
            raise ValueError("Provide question_ids or range_start/range_end")
        if has_range and (self.range_start <= 0 or self.range_end <= 0):
            raise ValueError("range_start and range_end must be >= 1")
        if self.edit_type == "edit_text" and not (self.new_content and self.new_content.strip()):
            raise ValueError("new_content is required when edit_type is 'edit_text'")
        if self.edit_type == "edit_options":
            if not self.new_options or len(self.new_options) != 4:
                raise ValueError("new_options must contain exactly 4 options")
        if self.edit_type == "edit_answer" and not (
            self.new_correct_answer and self.new_correct_answer.strip()
        ):
            raise ValueError("new_correct_answer is required when edit_type is 'edit_answer'")
        if self.edit_type == "edit_bloom" and not (
            self.new_bloom_level and self.new_bloom_level.strip()
        ):
            raise ValueError("new_bloom_level is required when edit_type is 'edit_bloom'")
        return self


class ExamPartialRegenerateRequest(BaseModel):
    exam_id: str
    edits: list[QuestionEditRequest]


class EditOperationResponse(BaseModel):
    id: str
    edit_type: str
    target_question_id: str | None = None
    prompt_used: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackEventResponse(BaseModel):
    id: str
    signal_type: str
    severity: str
    question_id: str | None = None
    payload: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExamVersionResponse(BaseModel):
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

    model_config = {"from_attributes": True}


ExamResponse.model_rebuild()


class GenerationStep(BaseModel):
    step: int
    name: str
    status: str
    message: str | None = None
    progress: float | None = None
