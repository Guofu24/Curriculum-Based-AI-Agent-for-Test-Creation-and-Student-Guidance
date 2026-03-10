"""
Orchestrator — LangGraph State Graph

This is the central coordination layer. It defines the multi-agent workflow
as a directed graph where each node is an agent and edges are conditional
transitions based on state.

Full Generation Flow (NEW — micro-prompting):
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  [Start] → [Parse Textbook] → [Create Blueprint (deterministic)] │
  │              ↓                      ↓                            │
  │         [Assign Chunks] ← ────────┘                             │
  │              ↓                                                   │
  │         [Generate From Chunks (parallel micro-prompting)]        │
  │              ↓                                                   │
  │         [Validate Questions]                                     │
  │              ↓                                                   │
  │         ┌─ pass? ─┐                                              │
  │         │ Yes     │ No → [Retry Generation] ─┐                   │
  │         ↓         └─────────────────────────┘                   │
  │         [Prune & Select]                                         │
  │              ↓                                                   │
  │         [Finalize] → [End]                                       │
  │                                                                  │
  │  Partial Edit Flow:                                              │
  │  [Start] → [Reviewer] → [Validate] → [Finalize] → [End]        │
  └──────────────────────────────────────────────────────────────────┘
"""
import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from agents.state import (
    AgentState,
    ExamBlueprint,
    GeneratedQuestion,
    RetrievedContext,
    ChunkAssignment,
)
from agents.document_processor import DocumentProcessorAgent
from agents.retrieval import RetrievalAgent
from agents.blueprint import BlueprintAgent, assign_chunks_to_slots
from agents.question_generator import QuestionGeneratorAgent
from agents.validator import ValidatorAgent
from agents.reviewer import ReviewerAgent
from agents.pruning import PruningAgent

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Node Functions (each wraps an agent call)
# ──────────────────────────────────────────────

async def parse_textbook_node(state: AgentState) -> dict:
    """Node: Verify textbook is processed and load metadata."""
    logger.info("Step 1/7: Parsing textbook...")
    return {
        "current_step": "parsing",
        "step_progress": 0.1,
        "processing_status": "ready",
    }


async def create_blueprint_node(state: AgentState) -> dict:
    """Node: Create exam blueprint deterministically (no LLM call)."""
    logger.info("Step 2/7: Creating deterministic blueprint...")

    blueprint_agent: BlueprintAgent = state["_blueprint_agent"]

    blueprint, original_quota = await blueprint_agent.create_blueprint(
        prompt=state["prompt"],
        exam_type=state["exam_type"],
        difficulty=state["difficulty"],
        chapters=state["chapters"],
        question_distribution=state["question_distribution"],
        gradually_increasing=state["gradually_increasing"],
        constraints=state["constraints"],
        textbook_metadata=state.get("textbook_metadata", {}),
    )

    return {
        "blueprint": blueprint,
        "original_quota": original_quota,
        "current_step": "blueprint",
        "step_progress": 0.2,
    }


async def assign_chunks_node(state: AgentState) -> dict:
    """Node: Assign specific chunks to question generation tasks."""
    logger.info("Step 3/7: Assigning chunks for micro-prompting...")

    blueprint: ExamBlueprint = state["blueprint"]
    db_session = state["_db_session"]

    chunk_assignments = await assign_chunks_to_slots(
        blueprint=blueprint,
        textbook_id=state["textbook_id"],
        db_session=db_session,
    )

    return {
        "chunk_assignments": chunk_assignments,
        "current_step": "assigning_chunks",
        "step_progress": 0.35,
    }


async def generate_from_chunks_node(state: AgentState) -> dict:
    """Node: Generate questions via micro-prompting (sequential, rate-limit aware)."""
    logger.info("Step 4/7: Generating questions (micro-prompting, sequential)...")

    generator: QuestionGeneratorAgent = state["_question_generator"]
    chunk_assignments: list[ChunkAssignment] = state["chunk_assignments"]

    questions = await generator.generate_from_chunks_parallel(
        chunk_assignments=chunk_assignments,
        constraints=state["constraints"],
    )

    return {
        "generated_questions": questions,
        "current_step": "generating",
        "step_progress": 0.6,
    }


async def validate_questions_node(state: AgentState) -> dict:
    """Node: Validate all questions for grounding and quality."""
    logger.info("Step 5/7: Validating constraints...")

    validator: ValidatorAgent = state["_validator"]
    questions = state["generated_questions"]
    strict = state["constraints"].get("strict_grounding", True)

    validated, summary = await validator.validate_questions(
        questions=questions,
        strict_grounding=strict,
    )

    return {
        "validated_questions": validated,
        "validation_summary": summary,
        "current_step": "validating",
        "step_progress": 0.75,
    }


async def prune_node(state: AgentState) -> dict:
    """Node: Prune over-generated pool to match original quota.
    Skips pruning for partial edits (where original_quota is empty).
    """
    original_quota = state.get("original_quota", {})

    # Skip pruning for partial edits or when no quota specified
    if not original_quota or all(v == 0 for v in original_quota.values()):
        logger.info("Pruning skipped (partial edit or no quota)")
        return {
            "current_step": "pruning",
            "step_progress": 0.9,
        }

    logger.info("Step 6/7: Pruning to match quota...")

    pruning_agent: PruningAgent = state["_pruning_agent"]
    validated = state.get("validated_questions", [])

    selected = pruning_agent.prune_and_select(
        pool=validated,
        original_quota=original_quota,
    )

    return {
        "validated_questions": selected,
        "current_step": "pruning",
        "step_progress": 0.9,
    }


async def finalize_node(state: AgentState) -> dict:
    """Node: Finalize the exam — prepare output."""
    logger.info("Step 7/7: Finalizing exam...")
    return {
        "current_step": "finalizing",
        "step_progress": 1.0,
    }


async def partial_edit_node(state: AgentState) -> dict:
    """Node: Handle partial regeneration of specific questions."""
    logger.info("Running partial edit...")

    reviewer: ReviewerAgent = state["_reviewer"]

    updated_questions = await reviewer.partial_regenerate(
        existing_questions=state["validated_questions"],
        edit_requests=state["edit_requests"],
        textbook_id=state["textbook_id"],
        constraints=state["constraints"],
    )

    return {
        "generated_questions": updated_questions,
        "current_step": "editing",
        "step_progress": 0.7,
    }


# ──────────────────────────────────────────────
# Routing functions
# ──────────────────────────────────────────────

def should_route_to_edit_or_generate(state: AgentState) -> Literal["partial_edit", "create_blueprint"]:
    """Route: Full generation or partial edit?"""
    if state.get("is_partial_edit") and state.get("edit_requests"):
        return "partial_edit"
    return "create_blueprint"


async def mark_retry_node(state: AgentState) -> dict:
    """Node: Mark that a retry has been attempted to prevent infinite loops."""
    logger.warning(f"Low pass rate, retrying question generation (once)...")
    return {"_retry_attempted": True}


def should_retry_or_prune(state: AgentState) -> Literal["prune", "mark_retry"]:
    """Route: If too many questions failed validation, retry once."""
    summary = state.get("validation_summary", {})
    pass_rate = summary.get("pass_rate", 1.0)

    if pass_rate < 0.6 and not state.get("_retry_attempted"):
        return "mark_retry"
    return "prune"


# ──────────────────────────────────────────────
# Graph Construction
# ──────────────────────────────────────────────

def create_exam_generation_graph() -> StateGraph:
    """
    Build the LangGraph state graph for exam generation.

    New flow with micro-prompting:
    Parse → Blueprint(deterministic) → AssignChunks → GenerateFromChunks(parallel)
    → Validate → Prune → Finalize

    Returns a compiled graph that can be invoked with an AgentState.
    """
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("parse_textbook", parse_textbook_node)
    graph.add_node("create_blueprint", create_blueprint_node)
    graph.add_node("assign_chunks", assign_chunks_node)
    graph.add_node("generate_from_chunks", generate_from_chunks_node)
    graph.add_node("validate_questions", validate_questions_node)
    graph.add_node("mark_retry", mark_retry_node)
    graph.add_node("prune", prune_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("partial_edit", partial_edit_node)

    # Set entry point
    graph.set_entry_point("parse_textbook")

    # Edges
    # After parsing, decide: full generation or partial edit
    graph.add_conditional_edges(
        "parse_textbook",
        should_route_to_edit_or_generate,
        {
            "create_blueprint": "create_blueprint",
            "partial_edit": "partial_edit",
        },
    )

    # Full generation flow (micro-prompting pipeline)
    graph.add_edge("create_blueprint", "assign_chunks")
    graph.add_edge("assign_chunks", "generate_from_chunks")
    graph.add_edge("generate_from_chunks", "validate_questions")

    # After validation: prune or retry once
    graph.add_conditional_edges(
        "validate_questions",
        should_retry_or_prune,
        {
            "prune": "prune",
            "mark_retry": "mark_retry",
        },
    )
    graph.add_edge("mark_retry", "generate_from_chunks")

    # After pruning, finalize
    graph.add_edge("prune", "finalize")

    # Partial edit also goes through validation then finalize (no pruning)
    graph.add_edge("partial_edit", "validate_questions")

    # End
    graph.add_edge("finalize", END)

    return graph.compile()
