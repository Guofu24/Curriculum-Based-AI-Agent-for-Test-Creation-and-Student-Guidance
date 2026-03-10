"""
Shared state definitions for the LangGraph multi-agent system.

The AgentState flows through the graph, accumulating results from each agent.
Each agent reads what it needs and writes its outputs to the state.
"""
from typing import TypedDict, Optional, Annotated, Any
from dataclasses import dataclass, field


# --- Blueprint structures ---

@dataclass
class QuestionSlot:
    """A planned slot in the exam blueprint."""
    slot_number: int
    question_type: str  # mcq, essay
    bloom_level: str  # remember, understand, apply, analyze, evaluate, create
    difficulty_score: float  # 0.0 to 1.0
    target_chapter: int
    target_topics: list[str] = field(default_factory=list)


@dataclass
class ExamBlueprint:
    """The structural plan for an exam, created by the BlueprintAgent."""
    title: str
    total_questions: int
    slots: list[QuestionSlot] = field(default_factory=list)
    difficulty_distribution: dict = field(default_factory=dict)
    bloom_distribution: dict = field(default_factory=dict)


# --- Generated question structure ---

@dataclass
class GeneratedQuestion:
    """A fully generated exam question."""
    slot_number: int
    question_type: str
    bloom_level: str
    difficulty_score: float
    content: str
    options: Optional[list[dict]] = None  # MCQ: [{label, text}, ...]
    correct_answer: str = ""
    explanation: str = ""
    source_chunks: list[str] = field(default_factory=list)  # chunk IDs for citation
    source_texts: list[str] = field(default_factory=list)  # actual source texts
    is_validated: bool = False
    validation_notes: str = ""


# --- Retrieval context ---

@dataclass
class RetrievedContext:
    """Context retrieved from the textbook for a specific question slot."""
    slot_number: int
    chunks: list[dict] = field(default_factory=list)  # {id, text, metadata, score}
    combined_text: str = ""


# --- Chunk assignment for micro-prompting ---

@dataclass
class ChunkAssignment:
    """Maps a single chunk to its question generation assignments.
    Used by micro-prompting: each chunk generates 1-2 questions."""
    chunk_id: str
    chunk_text: str
    chapter: int  # 0 = no chapter
    assignments: list[dict] = field(default_factory=list)  # [{difficulty, bloom_level, question_type}]


# --- LangGraph Agent State ---

class AgentState(TypedDict):
    """
    The shared state that flows through the LangGraph workflow.

    Each agent reads its needed inputs and appends its outputs.
    """
    # --- Input (from user request) ---
    user_id: str
    textbook_id: str
    chapters: list[int]
    prompt: str
    exam_type: str  # mcq, essay, mixed
    difficulty: str
    question_distribution: dict  # {mcq: {easy, medium, hard}, essay: {...}}
    num_variants: int
    gradually_increasing: bool
    constraints: dict  # {strict_grounding, allow_applied, creativity_level, bloom_levels, ...}

    # --- Document Processor output ---
    textbook_metadata: dict  # {title, chapters: [...], total_chunks}
    processing_status: str  # ready, processing, error

    # --- Blueprint Agent output ---
    blueprint: Optional[ExamBlueprint]

    # --- Retrieval Agent output ---
    retrieved_contexts: list[RetrievedContext]

    # --- Question Generator output ---
    generated_questions: list[GeneratedQuestion]

    # --- Validator Agent output ---
    validated_questions: list[GeneratedQuestion]
    validation_summary: dict  # {total, passed, failed, hallucination_flags}

    # --- Current step tracking ---
    current_step: str  # parsing, retrieving, generating, validating, finalizing
    step_progress: float  # 0.0 to 1.0
    error: Optional[str]

    # --- Micro-prompting (chunk-level question generation) ---
    chunk_assignments: list[ChunkAssignment]
    original_quota: dict  # {easy: N, medium: N, hard: N} — original target before over-generation

    # --- Partial regeneration (Reviewer) ---
    edit_requests: Optional[list[dict]]  # [{question_ids, prompt, range_start, range_end}]
    is_partial_edit: bool

    # --- Agent instances (injected at graph entry, not serialized to DB) ---
    _retrieval_agent: Optional[Any]
    _blueprint_agent: Optional[Any]
    _question_generator: Optional[Any]
    _validator: Optional[Any]
    _reviewer: Optional[Any]
    _pruning_agent: Optional[Any]
    _db_session: Optional[Any]
    _retry_attempted: Optional[bool]
