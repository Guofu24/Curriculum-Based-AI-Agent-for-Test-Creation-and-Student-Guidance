from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.mvp import DEFAULT_OUTPUT_LANGUAGE, DEFAULT_QUESTION_TYPE, normalize_mvp_language


class DifficultyDistribution(BaseModel):
    easy: int = 0
    medium: int = 0
    hard: int = 0


class QuestionDistribution(BaseModel):
    mcq: DifficultyDistribution = Field(default_factory=DifficultyDistribution)
    essay: DifficultyDistribution = Field(default_factory=DifficultyDistribution)


class ScopeUnitPayload(BaseModel):
    scope_id: Optional[str] = None
    section_id: Optional[str] = None
    scope_type: str = "chapter"
    title: Optional[str] = None
    chapter_number: int = 0
    page_from: Optional[int] = None
    page_to: Optional[int] = None
    tags: list[str] = Field(default_factory=list)


class AdvancedConstraints(BaseModel):
    strict_grounding: bool = True
    allow_applied_questions: bool = False
    strict_scope: bool = True
    grade_level_scope: Optional[str] = None
    creativity_level: float = Field(default=0.0, ge=0.0, le=1.0)
    bloom_levels: list[str] = Field(
        default_factory=lambda: [
            "remember",
            "understand",
            "apply",
            "analyze",
        ]
    )
    max_concurrency: int = Field(default=1, ge=1, le=1)


class ExamGenerationRequest(BaseModel):
    textbook_id: Optional[str] = None
    document_id: Optional[str] = None
    document_ids: list[str] = Field(default_factory=list)
    course_id: Optional[str] = None
    chapters: list[int] = Field(default_factory=list)
    scope: list[ScopeUnitPayload] = Field(default_factory=list)
    prompt: str = ""
    instructions: str = ""
    total_questions: Optional[int] = Field(default=None, ge=1, le=100)
    question_type: str = DEFAULT_QUESTION_TYPE
    exam_type: str = "mcq"
    difficulty: str = "custom"
    question_distribution: QuestionDistribution = Field(default_factory=QuestionDistribution)
    num_variants: int = Field(default=1, ge=1, le=1)
    gradually_increasing: bool = False
    constraints: AdvancedConstraints = Field(default_factory=AdvancedConstraints)
    time_limit_minutes: Optional[int] = None
    output_language: str = DEFAULT_OUTPUT_LANGUAGE
    bloom_distribution: dict[str, int] = Field(default_factory=dict)
    formatting_preferences: dict = Field(default_factory=dict)
    strict_scope: bool = True

    @field_validator("exam_type")
    @classmethod
    def validate_exam_type(cls, value: str) -> str:
        normalized = (value or "mcq").strip().lower()
        if normalized != "mcq":
            raise ValueError("MVP hiện tại chỉ hỗ trợ exam_type='mcq'")
        return normalized

    @field_validator("question_type")
    @classmethod
    def validate_question_type(cls, value: str) -> str:
        normalized = (value or DEFAULT_QUESTION_TYPE).strip().lower()
        if normalized not in {"mcq", DEFAULT_QUESTION_TYPE}:
            raise ValueError("MVP hiện tại chỉ hỗ trợ trắc nghiệm 1 đáp án đúng")
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
            raise ValueError("difficulty không hợp lệ")
        return normalized

    @model_validator(mode="after")
    def normalize_scope(self):
        if not self.textbook_id:
            if self.document_id:
                self.textbook_id = self.document_id
            elif len(self.document_ids) == 1:
                self.textbook_id = self.document_ids[0]

        if not self.textbook_id and not self.course_id:
            raise ValueError("Provide textbook_id/document_id or course_id")

        if self.num_variants != 1:
            raise ValueError("MVP hiện tại chỉ hỗ trợ 1 exam version cho mỗi lần generate")

        if self.question_distribution.essay.easy or self.question_distribution.essay.medium or self.question_distribution.essay.hard:
            raise ValueError("MVP hiện tại chưa hỗ trợ essay")

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
                raise ValueError("total_questions phải lớn hơn 0")
            self.total_questions = total_mcq

        self.strict_scope = bool(self.strict_scope)
        self.constraints.strict_scope = bool(self.strict_scope)
        self.constraints.strict_grounding = True
        self.constraints.allow_applied_questions = False
        self.constraints.creativity_level = 0.0
        self.gradually_increasing = False
        return self


class MCQOption(BaseModel):
    label: str
    text: str


class SourceEvidenceResponse(BaseModel):
    document_id: Optional[str] = None
    section_id: Optional[str] = None
    chunk_id: str
    chapter_number: Optional[int] = None
    page: Optional[int] = None
    parent_heading: Optional[str] = None
    role: Optional[str] = None
    score: Optional[float] = None
    text_preview: Optional[str] = None


class QuestionResponse(BaseModel):
    id: str
    question_number: int
    blueprint_cell_key: Optional[str] = None
    question_type: str
    bloom_level: str
    difficulty_score: float
    content: str
    options: Optional[list[MCQOption]] = None
    correct_answer: str
    rubric: Optional[dict] = None
    explanation: Optional[str] = None
    source_citations: Optional[list[str]] = None
    source_evidence: Optional[list[SourceEvidenceResponse]] = None
    scope_tags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    verification_status: Optional[str] = None
    is_human_edited: bool = False
    is_locked: bool = False
    is_validated: bool = False
    quality_score_detail: Optional[dict] = None
    grounding_report_detail: Optional[dict] = None

    model_config = {"from_attributes": True}


class BlueprintCellResponse(BaseModel):
    cell_id: str
    section_id: Optional[str] = None
    scope_unit: dict
    question_type: str
    bloom_level: str
    target_count: int
    generated_count: int = 0
    priority: int = 0
    overgenerate_count: int = 0


class ExamSpecResponse(BaseModel):
    course_id: Optional[str] = None
    document_id: Optional[str] = None
    exam_type: str
    question_type: str = DEFAULT_QUESTION_TYPE
    total_questions: int
    time_limit_minutes: Optional[int] = None
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
    textbook_id: str
    course_id: Optional[str] = None
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = Field(default_factory=list)
    variant_number: int
    total_questions: int
    instructions: Optional[str] = None
    output_language: str = DEFAULT_OUTPUT_LANGUAGE
    strict_scope_flag: bool = True
    quality_score: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    questions: list[QuestionResponse] = Field(default_factory=list)
    exam_spec: Optional[dict] = None
    blueprint: Optional[dict] = None
    selected_scope: Optional[list[dict]] = None
    quality_scores: Optional[list[dict]] = None
    grounding_reports: Optional[list[dict]] = None
    duplicate_groups: Optional[list[dict]] = None
    provider_logs: Optional[list[dict]] = None
    edit_impact_level: Optional[str] = None
    edit_history: Optional[list[dict]] = None
    current_version: Optional["ExamVersionResponse"] = None
    versions: Optional[list["ExamVersionResponse"]] = None

    model_config = {"from_attributes": True}


class ExamListResponse(BaseModel):
    id: str
    title: str
    textbook_id: str
    course_id: Optional[str] = None
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = Field(default_factory=list)
    total_questions: int
    strict_scope_flag: bool = True
    quality_score: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class QuestionEditRequest(BaseModel):
    question_ids: list[str] = Field(default_factory=list)
    edit_prompt: Optional[str] = None
    range_start: Optional[int] = None
    range_end: Optional[int] = None
    edit_type: str = "regenerate"
    new_content: Optional[str] = None
    new_options: Optional[list[MCQOption]] = None
    new_correct_answer: Optional[str] = None
    new_bloom_level: Optional[str] = None

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
        if self.edit_type == "edit_answer" and not (self.new_correct_answer and self.new_correct_answer.strip()):
            raise ValueError("new_correct_answer is required when edit_type is 'edit_answer'")
        if self.edit_type == "edit_bloom" and not (self.new_bloom_level and self.new_bloom_level.strip()):
            raise ValueError("new_bloom_level is required when edit_type is 'edit_bloom'")
        return self


class ExamPartialRegenerateRequest(BaseModel):
    exam_id: str
    edits: list[QuestionEditRequest]


class EditOperationResponse(BaseModel):
    id: str
    edit_type: str
    target_question_id: Optional[str] = None
    prompt_used: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExamVersionResponse(BaseModel):
    id: str
    version_number: int
    status: str
    created_by: str
    parent_version_id: Optional[str] = None
    change_summary: Optional[str] = None
    created_at: datetime
    questions: list[QuestionResponse] = Field(default_factory=list)
    edit_operations: list[EditOperationResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


ExamResponse.model_rebuild()


class GenerationStep(BaseModel):
    step: int
    name: str
    status: str
    message: Optional[str] = None
    progress: Optional[float] = None
