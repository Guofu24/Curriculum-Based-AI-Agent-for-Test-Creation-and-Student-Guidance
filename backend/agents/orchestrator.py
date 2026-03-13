"""
Orchestrator — LangGraph State Graph

This is the central coordination layer. It defines the multi-agent workflow
as a directed graph where each node is an agent and edges are conditional
transitions based on state.

Full Generation Flow (micro-prompting + quality pipeline):
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  [Start] → [Parse Textbook] → [Create Blueprint (deterministic)] │
  │              ↓                      ↓                            │
  │         [Assign Chunks] ← ────────┘                             │
  │              ↓                                                   │
  │         [Generate From Chunks (micro-prompting)]                 │
  │              ↓                                                   │
  │         [Validate Questions (rule-based)]                        │
  │              ↓                                                   │
  │         ┌─ pass? ─┐                                              │
  │         │ Yes     │ No → [Retry Generation] ─┐                   │
  │         ↓         └─────────────────────────┘                   │
  │         [Quality Judge (multi-rubric)]                           │
  │              ↓                                                   │
  │         [Dedup Filter (similarity)]                              │
  │              ↓                                                   │
  │         [Prune & Select]                                         │
  │              ↓                                                   │
  │         [Finalize] → [End]                                       │
  │                                                                  │
  │  Partial Edit Flow:                                              │
  │  [Start] → [Reviewer] → [Validate] → [QualityJudge]             │
  │            → [DedupFilter] → [Prune(skip)] → [Finalize] → [End] │
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
from agents.quality_judge import QualityJudgeAgent
from agents.dedup_filter import DedupFilterAgent
from agents.review_impact import ReviewImpactAnalyzer

logger = logging.getLogger(__name__)


def _serialize_chunk_assignment(assignment: ChunkAssignment) -> dict:
    """Serialize chunk assignment metadata for cross-node state propagation.

    Backward-compatible with both old and new ChunkAssignment shapes.
    """
    supporting_chunks = []
    if hasattr(assignment, "get_supporting_chunks"):
        supporting_chunks = assignment.get_supporting_chunks()
    else:
        supporting_chunks = getattr(assignment, "context_chunks", []) or []

    primary_chunk = getattr(assignment, "primary_chunk", None) or {
        "chunk_id": assignment.chunk_id,
        "chunk_text": assignment.chunk_text,
    }

    if hasattr(assignment, "get_source_chunk_ids"):
        source_chunks = assignment.get_source_chunk_ids()
    else:
        source_chunks = [assignment.chunk_id]
        for chunk in supporting_chunks:
            chunk_id = chunk.get("chunk_id")
            if chunk_id and chunk_id not in source_chunks:
                source_chunks.append(chunk_id)

    inferred_chunk_mode = getattr(assignment, "chunk_mode", None)
    if not inferred_chunk_mode:
        inferred_chunk_mode = "multi" if supporting_chunks else "single"

    inferred_bundle_strategy = getattr(assignment, "bundle_strategy", None)
    if not inferred_bundle_strategy:
        inferred_bundle_strategy = "single" if inferred_chunk_mode == "single" else "local_multi"

    return {
        "slot_numbers": [a.get("slot_number") for a in assignment.assignments],
        "chunk_mode": inferred_chunk_mode,
        "bundle_strategy": inferred_bundle_strategy,
        "primary_chunk": primary_chunk,
        "supporting_chunks": supporting_chunks,
        "source_chunks": source_chunks,
        "bundle_score": float(getattr(assignment, "bundle_score", 0.0) or 0.0),
        "assignment_reason": getattr(assignment, "assignment_reason", "") or "",
        "evidence_roles": getattr(assignment, "evidence_roles", {}) or {},
    }


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

    chunk_assignment_payloads = [
        _serialize_chunk_assignment(assignment)
        for assignment in chunk_assignments
    ]

    return {
        "chunk_assignments": chunk_assignments,
        "chunk_assignment_payloads": chunk_assignment_payloads,
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

    # Build slot-level metadata trace so downstream nodes can inspect bundle plan.
    by_slot: dict[int, dict] = {}
    for assignment in chunk_assignments:
        serialized = _serialize_chunk_assignment(assignment)
        for slot_number in serialized["slot_numbers"]:
            if isinstance(slot_number, int):
                by_slot[slot_number] = serialized

    question_chunk_metadata: list[dict] = []
    for question in questions:
        slot_meta = by_slot.get(question.slot_number, {})
        question_chunk_metadata.append({
            "slot_number": question.slot_number,
            "chunk_mode": slot_meta.get("chunk_mode", "single"),
            "bundle_strategy": slot_meta.get("bundle_strategy", "single"),
            "primary_chunk": slot_meta.get("primary_chunk", {
                "chunk_id": question.source_chunks[0] if question.source_chunks else None,
                "chunk_text": question.source_texts[0] if question.source_texts else None,
            }),
            "supporting_chunks": slot_meta.get("supporting_chunks", []),
            "source_chunks": question.source_chunks,
            "bundle_score": slot_meta.get("bundle_score", 0.0),
            "assignment_reason": slot_meta.get("assignment_reason", ""),
        })

    return {
        "generated_questions": questions,
        "question_chunk_metadata": question_chunk_metadata,
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


async def quality_judge_node(state: AgentState) -> dict:
    """Node: Deep quality assessment on validated questions."""
    logger.info("Step 5.5/7: Quality judging...")

    judge: QualityJudgeAgent = state["_quality_judge"]
    questions = state.get("validated_questions", [])

    judged, scores, grounding_reports = await judge.judge_questions(questions)

    return {
        "judged_questions": judged,
        "quality_scores": scores,
        "grounding_reports": grounding_reports,
        "current_step": "quality_judging",
        "step_progress": 0.8,
    }


async def dedup_filter_node(state: AgentState) -> dict:
    """Node: Remove near-duplicate questions, keep best representative."""
    logger.info("Step 5.7/7: Deduplicating...")

    dedup: DedupFilterAgent = state["_dedup_filter"]
    judged = state.get("judged_questions", state.get("validated_questions", []))
    scores = state.get("quality_scores", [])

    filtered, duplicate_groups = dedup.filter_duplicates(
        questions=judged,
        quality_scores=scores,
    )

    # Write back to validated_questions so pruning picks it up unchanged
    return {
        "validated_questions": filtered,
        "duplicate_groups": duplicate_groups,
        "current_step": "deduplicating",
        "step_progress": 0.85,
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
    """Node: Finalize the exam — prepare output and drain provider logs."""
    logger.info("Step 7/7: Finalizing exam...")

    # Drain LLM provider logs if the backend supports it
    provider_logs: list[dict] = []
    try:
        llm = state["_question_generator"].llm
        if hasattr(llm, "drain_logs"):
            provider_logs = llm.drain_logs()
    except Exception:
        pass

    return {
        "current_step": "finalizing",
        "step_progress": 1.0,
        "provider_logs": provider_logs,
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


async def analyze_impact_node(state: AgentState) -> dict:
    """Node: Classify edit requests by semantic impact before regeneration."""
    logger.info("Analyzing edit impact...")

    analyzer = ReviewImpactAnalyzer()
    existing = state.get("validated_questions", [])
    edit_requests = state.get("edit_requests", [])

    impact = analyzer.classify(edit_requests, existing)

    return {
        "edit_impact_level": impact,
        "current_step": "analyzing_impact",
        "step_progress": 0.55,
    }


async def retrieval_refresh_node(state: AgentState) -> dict:
    """Node: Re-retrieve source context for questions that underwent strong edits.

    After strong semantic changes, the original source_texts may no longer
    match the regenerated content. This node fetches fresh context based on
    the NEW question content so that the validator can properly ground-check.
    """
    logger.info("Retrieval refresh for strong edits...")

    retrieval: RetrievalAgent = state["_retrieval_agent"]
    questions = state["generated_questions"]
    edit_requests = state.get("edit_requests", [])

    # Identify edited slot numbers
    edited_slots: set[int] = set()
    for req in edit_requests:
        if req.get("question_ids"):
            for qid in req["question_ids"]:
                try:
                    edited_slots.add(int(qid))
                except (ValueError, TypeError):
                    pass
        start = req.get("range_start")
        end = req.get("range_end")
        if start is not None and end is not None:
            for n in range(int(start), int(end) + 1):
                edited_slots.add(n)

    refreshed_contexts = []
    for q in questions:
        if q.slot_number not in edited_slots:
            continue

        # Re-retrieve using the NEW question content as query
        context = await retrieval.retrieve_for_single_question(
            query=q.content,
            textbook_id=state["textbook_id"],
            chapter=0,
        )

        # Update source references on the question
        q.source_chunks = [c["id"] for c in context.chunks]
        q.source_texts = [c["text"] for c in context.chunks]
        refreshed_contexts.append(context)

    logger.info(
        f"Retrieval refresh: updated source for {len(refreshed_contexts)} "
        f"questions (slots={sorted(edited_slots)})"
    )

    return {
        "generated_questions": questions,
        "refreshed_contexts": refreshed_contexts,
        "current_step": "retrieval_refresh",
        "step_progress": 0.65,
    }


# ──────────────────────────────────────────────
# Routing functions
# ──────────────────────────────────────────────

def should_route_to_edit_or_generate(state: AgentState) -> Literal["analyze_impact", "create_blueprint"]:
    """Route: Full generation or partial edit? Partial edits go to impact analysis first."""
    if state.get("is_partial_edit") and state.get("edit_requests"):
        return "analyze_impact"
    return "create_blueprint"


async def mark_retry_node(state: AgentState) -> dict:
    """Node: Mark that a retry has been attempted to prevent infinite loops."""
    logger.warning(f"Low pass rate, retrying question generation (once)...")
    return {"_retry_attempted": True}


def should_retry_or_judge(state: AgentState) -> Literal["quality_judge", "mark_retry"]:
    """Route: If too many questions failed validation, retry once.
    Otherwise proceed to quality judging.
    Partial edits skip retry (retry targets generate_from_chunks which is
    not part of the partial edit flow)."""
    if state.get("is_partial_edit"):
        return "quality_judge"

    summary = state.get("validation_summary", {})
    pass_rate = summary.get("pass_rate", 1.0)

    if pass_rate < 0.6 and not state.get("_retry_attempted"):
        return "mark_retry"
    return "quality_judge"


def route_after_partial_edit(
    state: AgentState,
) -> Literal["retrieval_refresh", "validate_questions"]:
    """Route after partial edit: strong impact → retrieval refresh first."""
    if state.get("edit_impact_level") == "strong":
        return "retrieval_refresh"
    return "validate_questions"


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
    graph.add_node("quality_judge", quality_judge_node)
    graph.add_node("dedup_filter", dedup_filter_node)
    graph.add_node("prune", prune_node)
    graph.add_node("finalize", finalize_node)
    # Partial edit nodes (Phase 4)
    graph.add_node("analyze_impact", analyze_impact_node)
    graph.add_node("partial_edit", partial_edit_node)
    graph.add_node("retrieval_refresh", retrieval_refresh_node)

    # Set entry point
    graph.set_entry_point("parse_textbook")

    # Edges
    # After parsing, decide: full generation or partial edit
    graph.add_conditional_edges(
        "parse_textbook",
        should_route_to_edit_or_generate,
        {
            "create_blueprint": "create_blueprint",
            "analyze_impact": "analyze_impact",
        },
    )

    # Full generation flow (micro-prompting pipeline)
    graph.add_edge("create_blueprint", "assign_chunks")
    graph.add_edge("assign_chunks", "generate_from_chunks")
    graph.add_edge("generate_from_chunks", "validate_questions")

    # After validation: quality judge or retry once
    graph.add_conditional_edges(
        "validate_questions",
        should_retry_or_judge,
        {
            "quality_judge": "quality_judge",
            "mark_retry": "mark_retry",
        },
    )
    graph.add_edge("mark_retry", "generate_from_chunks")

    # Quality judge -> dedup -> prune -> finalize
    graph.add_edge("quality_judge", "dedup_filter")
    graph.add_edge("dedup_filter", "prune")
    graph.add_edge("prune", "finalize")

    # Partial edit flow (Phase 4):
    # analyze_impact → partial_edit → conditional(strong→refresh, else→validate)
    graph.add_edge("analyze_impact", "partial_edit")
    graph.add_conditional_edges(
        "partial_edit",
        route_after_partial_edit,
        {
            "retrieval_refresh": "retrieval_refresh",
            "validate_questions": "validate_questions",
        },
    )
    graph.add_edge("retrieval_refresh", "validate_questions")

    # End
    graph.add_edge("finalize", END)

    return graph.compile()
