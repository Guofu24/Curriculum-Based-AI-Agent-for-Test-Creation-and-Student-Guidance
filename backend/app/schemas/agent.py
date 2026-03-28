"""Agent schemas for multi-agent system."""

from pydantic import BaseModel, Field
from uuid import UUID
from typing import Any, Literal, Optional

# Re-export base types from agents.base to keep schemas self-contained
from app.agents.base import AgentStatus, TokenUsage, AgentBaseOutput


# ── Retrieval Agent ───────────────────────────────────────────────────────────

class RetrievedChunk(BaseModel):
    """Schema for a retrieved knowledge chunk."""
    chunk_id: str
    chapter: str
    section: str | None = None
    content: str
    content_type: Literal["text", "formula", "image_description"] = "text"
    relevance_score: float = Field(ge=0.0, le=1.0)
    latex_repr: str | None = None


class RetrievalInput(BaseModel):
    """Input schema for Retrieval Agent."""
    document_id: UUID
    scope_chapters: list[str]
    bloom_targets: list[str] = []
    query_hints: list[str] = []


class RetrievalOutput(AgentBaseOutput):
    """Output schema for Retrieval Agent."""
    retrieved_chunks: list[RetrievedChunk] = []
    coverage_map: dict[str, list[str]] = {}  # chapter -> sections


# ── Outline Agent ─────────────────────────────────────────────────────────────

class OutlineInput(BaseModel):
    """Input schema for Outline Agent."""
    retrieved_context: list[RetrievedChunk]
    exam_config: dict  # From exam_schema


class OutlineOutput(AgentBaseOutput):
    """Output schema for Outline Agent."""
    blueprint: list[dict]  # List of blueprint slots
    distribution_summary: dict


# ── Builder Agent ─────────────────────────────────────────────────────────────

class BuilderInput(BaseModel):
    """Input schema for Builder Agent."""
    blueprint: list[dict]
    retrieved_context: list[RetrievedChunk]
    topics_used: list[str] = []
    allowed_concepts: list[str] = []
    web_search_quota: int = 0
    prefer_applied_problems: bool = False


class BuilderOutput(AgentBaseOutput):
    """Output schema for Builder Agent."""
    questions: list[dict]  # MCQQuestion | EssayQuestion
    topics_used: list[str] = []
    chunks_referenced: list[str] = []


# ── Validator Agent ───────────────────────────────────────────────────────────

class ValidationIssue(BaseModel):
    """Schema for a validation issue."""
    question_id: str
    issue_type: Literal["wrong_answer", "bloom_mismatch", "scope_violation", "duplicate"]
    detail: str
    suggestion: str


class ValidatorInput(BaseModel):
    """Input schema for Validator Agent."""
    questions: list[dict]
    exam_config: dict
    retrieved_context: list[RetrievedChunk] = []


class ValidatorOutput(AgentBaseOutput):
    """Output schema for Validator Agent."""
    validation_passed: bool
    issues: list[ValidationIssue] = []
    score_attempt: dict[str, dict] = {}
    bloom_compliance: dict[str, dict] = {}
    scope_violations: list[str] = []
    approved_for_publish: bool = False


# ── Planner Agent ─────────────────────────────────────────────────────────────

class PlanStep(BaseModel):
    """Schema for a single plan step."""
    step: int
    tool: str
    params_override: dict = {}
    note: str = ""


class PlannerInput(BaseModel):
    """Input schema for Planner Agent."""
    user_request_parsed: str
    exam_config: dict
    available_tools: list[str]
    constraints: dict


class PlannerOutput(AgentBaseOutput):
    """Output schema for Planner Agent."""
    plan: list[PlanStep]
    estimated_token_cost: int = 0
    hitl_checkpoint_after_step: int | None = None


# ── Orchestrator ─────────────────────────────────────────────────────────────

class OrchestratorInput(BaseModel):
    """Input schema for Orchestrator Agent."""
    user_id: UUID
    document_id: UUID
    scope: list[str]
    exam_type: Literal["mcq", "essay", "mixed"] = "mixed"
    mcq_count: int = 40
    essay_count: int = 5
    bloom_distribution: dict[str, int]
    user_prompt: str | None = None
    extra_instructions: str | None = None


class OrchestratorOutput(BaseModel):
    """Output schema for Orchestrator Agent."""
    exam_id: UUID
    questions: list[dict]
    blueprint: dict | None = None
    cost_report: dict | None = None
    status: AgentStatus
    warnings: list[str] = []


# ── Memory Layer ──────────────────────────────────────────────────────────────

class SessionMemory(BaseModel):
    """Short-term session memory stored in Redis."""
    exam_id: str
    user_id: str
    exam_config_original: dict
    topics_used: list[str] = []
    conversation_history: list[dict[str, str]] = []  # [{role, content}]
    retry_count: int = 0


class TeacherPreferences(BaseModel):
    """Long-term teacher preferences from PostgreSQL."""
    preferred_bloom_distribution: dict[str, int] | None = None
    preferred_exam_types: dict[str, float] | None = None
    subject_focus: str | None = None
    style_notes: str | None = None


# ── Skill Inputs/Outputs ──────────────────────────────────────────────────────

class BloomClassifierInput(BaseModel):
    """Input for bloom classifier skill."""
    question_stem: str
    question_type: Literal["mcq", "essay"]
    subject: str = "general"


class BloomClassifierOutput(BaseModel):
    """Output from bloom classifier skill."""
    bloom_level: Literal["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class ScopeCheckerInput(BaseModel):
    """Input for scope checker skill."""
    question_stem: str
    retrieved_context_ids: list[str]
    scope_chapters: list[str]


class ScopeCheckerOutput(BaseModel):
    """Output from scope checker skill."""
    in_scope: bool
    violation_type: str | None = None
    evidence_chunk_ids: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)


class DedupCheckerInput(BaseModel):
    """Input for deduplication checker skill."""
    new_question_topic: str
    existing_topics: list[str]


class DedupCheckerOutput(BaseModel):
    """Output from deduplication checker skill."""
    is_duplicate: bool
    duplicate_with: str | None = None
    similarity_score: float = Field(ge=0.0, le=1.0)
    suggestion: str | None = None
