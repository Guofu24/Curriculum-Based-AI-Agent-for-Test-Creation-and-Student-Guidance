"""
Orchestrator — LangGraph State Graph

This is the central coordination layer. It defines the multi-agent workflow
as a directed graph where each node is an agent and edges are conditional
transitions based on state.

Flow:
  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │  [Start] → [Parse Textbook] → [Create Blueprint]        │
  │              ↓                      ↓                    │
  │         [Retrieve Context] ← ──────┘                    │
  │              ↓                                           │
  │         [Generate Questions]                             │
  │              ↓                                           │
  │         [Validate Questions]                             │
  │              ↓                                           │
  │         ┌─ pass? ─┐                                      │
  │         │ Yes     │ No → [Regenerate Failed] ─┐          │
  │         ↓         └───────────────────────────┘          │
  │         [Finalize] → [End]                               │
  │                                                          │
  │  Partial Edit Flow:                                      │
  │  [Start] → [Reviewer] → [Validate] → [Finalize] → [End] │
  └──────────────────────────────────────────────────────────┘
"""
import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from agents.state import (
    AgentState,
    ExamBlueprint,
    GeneratedQuestion,
    RetrievedContext,
)
from agents.document_processor import DocumentProcessorAgent
from agents.retrieval import RetrievalAgent
from agents.blueprint import BlueprintAgent
from agents.question_generator import QuestionGeneratorAgent
from agents.validator import ValidatorAgent
from agents.reviewer import ReviewerAgent

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Node Functions (each wraps an agent call)
# ──────────────────────────────────────────────

async def parse_textbook_node(state: AgentState) -> dict:
    """Node: Verify textbook is processed and load metadata."""
    logger.info("Step 1/5: Parsing textbook...")
    return {
        "current_step": "parsing",
        "step_progress": 0.2,
        "processing_status": "ready",
    }


async def create_blueprint_node(state: AgentState) -> dict:
    """Node: Create exam blueprint from user configuration."""
    logger.info("Step 2/5: Creating exam blueprint...")

    blueprint_agent: BlueprintAgent = state["_blueprint_agent"]

    blueprint = await blueprint_agent.create_blueprint(
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
        "current_step": "blueprint",
        "step_progress": 0.4,
    }


async def retrieve_context_node(state: AgentState) -> dict:
    """Node: Retrieve relevant textbook content for each question slot."""
    logger.info("Step 3/5: Retrieving knowledge...")

    retrieval_agent: RetrievalAgent = state["_retrieval_agent"]
    blueprint: ExamBlueprint = state["blueprint"]

    contexts = await retrieval_agent.retrieve_for_blueprint(
        blueprint=blueprint,
        textbook_id=state["textbook_id"],
        chapters=state["chapters"],
        constraints=state["constraints"],
    )

    return {
        "retrieved_contexts": contexts,
        "current_step": "retrieving",
        "step_progress": 0.6,
    }


async def generate_questions_node(state: AgentState) -> dict:
    """Node: Generate questions based on blueprint and context."""
    logger.info("Step 4/5: Generating questions...")

    generator: QuestionGeneratorAgent = state["_question_generator"]
    blueprint: ExamBlueprint = state["blueprint"]
    contexts: list[RetrievedContext] = state["retrieved_contexts"]

    questions = await generator.generate_questions(
        slots=blueprint.slots,
        contexts=contexts,
        constraints=state["constraints"],
    )

    return {
        "generated_questions": questions,
        "current_step": "generating",
        "step_progress": 0.8,
    }


async def validate_questions_node(state: AgentState) -> dict:
    """Node: Validate all questions for grounding and quality."""
    logger.info("Step 5/5: Validating constraints...")

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
        "step_progress": 0.9,
    }


async def finalize_node(state: AgentState) -> dict:
    """Node: Finalize the exam — prepare output."""
    logger.info("Finalizing exam...")
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


def should_retry_or_finalize(state: AgentState) -> Literal["finalize", "mark_retry"]:
    """Route: If too many questions failed validation, retry once."""
    summary = state.get("validation_summary", {})
    pass_rate = summary.get("pass_rate", 1.0)

    if pass_rate < 0.6 and not state.get("_retry_attempted"):
        return "mark_retry"
    return "finalize"


# ──────────────────────────────────────────────
# Graph Construction
# ──────────────────────────────────────────────

def create_exam_generation_graph() -> StateGraph:
    """
    Build the LangGraph state graph for exam generation.

    Returns a compiled graph that can be invoked with an AgentState.
    """
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("parse_textbook", parse_textbook_node)
    graph.add_node("create_blueprint", create_blueprint_node)
    graph.add_node("retrieve_context", retrieve_context_node)
    graph.add_node("generate_questions", generate_questions_node)
    graph.add_node("validate_questions", validate_questions_node)
    graph.add_node("mark_retry", mark_retry_node)
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

    # Full generation flow
    graph.add_edge("create_blueprint", "retrieve_context")
    graph.add_edge("retrieve_context", "generate_questions")
    graph.add_edge("generate_questions", "validate_questions")

    # After validation: finalize or retry once
    graph.add_conditional_edges(
        "validate_questions",
        should_retry_or_finalize,
        {
            "finalize": "finalize",
            "mark_retry": "mark_retry",
        },
    )
    graph.add_edge("mark_retry", "generate_questions")

    # Partial edit also goes through validation
    graph.add_edge("partial_edit", "validate_questions")

    # End
    graph.add_edge("finalize", END)

    return graph.compile()
