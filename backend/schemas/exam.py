from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# --- Generation Request ---

class DifficultyDistribution(BaseModel):
    easy: int = 0
    medium: int = 0
    hard: int = 0


class QuestionDistribution(BaseModel):
    mcq: DifficultyDistribution = DifficultyDistribution()
    essay: DifficultyDistribution = DifficultyDistribution()


class AdvancedConstraints(BaseModel):
    strict_grounding: bool = True  # Only textbook knowledge
    allow_applied_questions: bool = True
    grade_level_scope: Optional[str] = None
    creativity_level: float = Field(default=0.5, ge=0.0, le=1.0)
    bloom_levels: list[str] = ["remember", "understand", "apply", "analyze"]


class ExamGenerationRequest(BaseModel):
    textbook_id: str
    chapters: list[int] = []  # chapter numbers (empty = use entire textbook)
    prompt: str  # e.g. "Generate midterm exam for chapters 1-3"
    exam_type: str  # mcq, essay, mixed
    difficulty: str  # basic, advanced, application, high_application, custom
    question_distribution: QuestionDistribution
    num_variants: int = Field(default=1, ge=1, le=10)
    gradually_increasing: bool = False
    constraints: AdvancedConstraints = AdvancedConstraints()


# --- Question Schema ---

class MCQOption(BaseModel):
    label: str  # A, B, C, D
    text: str


class QuestionResponse(BaseModel):
    id: str
    question_number: int
    question_type: str
    bloom_level: str
    difficulty_score: float
    content: str
    options: Optional[list[MCQOption]] = None
    correct_answer: str
    explanation: Optional[str] = None
    source_citations: Optional[list[str]] = None
    is_validated: bool = False
    quality_score_detail: Optional[dict] = None     # per-question quality rubric
    grounding_report_detail: Optional[dict] = None  # per-question grounding analysis

    model_config = {"from_attributes": True}


# --- Exam Response ---

class ExamResponse(BaseModel):
    id: str
    title: str
    textbook_id: str
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = []
    variant_number: int
    total_questions: int
    quality_score: Optional[float] = None
    created_at: datetime
    questions: list[QuestionResponse] = []
    # Phase 1-5 aggregate data
    quality_scores: Optional[list[dict]] = None       # per-question quality rubric scores
    grounding_reports: Optional[list[dict]] = None     # per-question grounding analysis
    duplicate_groups: Optional[list[dict]] = None      # dedup clusters
    provider_logs: Optional[list[dict]] = None         # LLM call logs
    edit_impact_level: Optional[str] = None            # cosmetic, moderate, strong

    model_config = {"from_attributes": True}


class ExamListResponse(BaseModel):
    id: str
    title: str
    textbook_id: str
    exam_type: str
    difficulty: str
    status: str
    chapters: list[int] = []
    total_questions: int
    quality_score: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Edit Request ---

class QuestionEditRequest(BaseModel):
    question_ids: list[str]  # IDs of questions to regenerate
    edit_prompt: Optional[str] = None  # optional guidance for regeneration
    range_start: Optional[int] = None  # question number start
    range_end: Optional[int] = None  # question number end
    edit_type: str = "regenerate"  # regenerate, edit_text
    new_content: Optional[str] = None  # for direct text edits


class ExamPartialRegenerateRequest(BaseModel):
    exam_id: str
    edits: list[QuestionEditRequest]


# --- Generation Status (SSE) ---

class GenerationStep(BaseModel):
    step: int
    name: str
    status: str  # pending, running, completed, failed
    message: Optional[str] = None
    progress: Optional[float] = None  # 0.0 to 1.0
