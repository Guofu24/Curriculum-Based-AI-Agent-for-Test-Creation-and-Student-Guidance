"""LangGraph node functions for the exam generation pipeline."""

from app.agents.graph.nodes.initialize import initialize
from app.agents.graph.nodes.clarification_check import clarification_check
from app.agents.graph.nodes.load_long_term_memory import load_long_term_memory
from app.agents.graph.nodes.decide_plan import decide_plan
from app.agents.graph.nodes.plan_complex import plan_complex
from app.agents.graph.nodes.retrieve_knowledge import retrieve_knowledge
from app.agents.graph.nodes.handle_retrieval_failure import handle_retrieval_failure
from app.agents.graph.nodes.create_outline import create_outline
from app.agents.graph.nodes.handle_outline_failure import handle_outline_failure
from app.agents.graph.nodes.emit_checkpoint_1 import emit_checkpoint_1
from app.agents.graph.nodes.wait_for_blueprint_approval import wait_for_blueprint_approval
from app.agents.graph.nodes.build_questions import build_questions
from app.agents.graph.nodes.handle_builder_failure import handle_builder_failure
from app.agents.graph.nodes.validate_questions import validate_questions
from app.agents.graph.nodes.check_validation_result import check_validation_result
from app.agents.graph.nodes.retry_builder import retry_builder
from app.agents.graph.nodes.handle_max_retries_exceeded import handle_max_retries_exceeded
from app.agents.graph.nodes.emit_checkpoint_2 import emit_checkpoint_2
from app.agents.graph.nodes.wait_for_review import wait_for_review
from app.agents.graph.nodes.save_teacher_preferences import save_teacher_preferences
from app.agents.graph.nodes.emit_checkpoint_3 import emit_checkpoint_3
from app.agents.graph.nodes.finalize_with_feedback import finalize_with_feedback
from app.agents.graph.nodes.finalize_output import finalize_output
from app.agents.graph.nodes.handle_timeout import handle_timeout
from app.agents.graph.nodes.emit_clarification import emit_clarification
from app.agents.graph.nodes.merge_plan_retrieval import merge_plan_retrieval
from app.agents.graph.nodes.dispatch_tasks import dispatch_tasks

# fanout_complex: passthrough node — two outgoing edges trigger parallel execution in LangGraph
async def fanout_complex(state):
    return state

ALL_NODES = [
    ("initialize", initialize),
    ("clarification_check", clarification_check),
    ("load_long_term_memory", load_long_term_memory),
    ("decide_plan", decide_plan),
    ("plan_complex", plan_complex),
    ("retrieve_knowledge", retrieve_knowledge),
    ("handle_retrieval_failure", handle_retrieval_failure),
    ("create_outline", create_outline),
    ("handle_outline_failure", handle_outline_failure),
    ("emit_checkpoint_1", emit_checkpoint_1),
    ("wait_for_blueprint_approval", wait_for_blueprint_approval),
    ("build_questions", build_questions),
    ("handle_builder_failure", handle_builder_failure),
    ("validate_questions", validate_questions),
    ("check_validation_result", check_validation_result),
    ("retry_builder", retry_builder),
    ("handle_max_retries_exceeded", handle_max_retries_exceeded),
    ("emit_checkpoint_2", emit_checkpoint_2),
    ("wait_for_review", wait_for_review),
    ("save_teacher_preferences", save_teacher_preferences),
    ("emit_checkpoint_3", emit_checkpoint_3),
    ("finalize_with_feedback", finalize_with_feedback),
    ("finalize_output", finalize_output),
    ("handle_timeout", handle_timeout),
    ("emit_clarification", emit_clarification),
    ("merge_plan_retrieval", merge_plan_retrieval),
    ("dispatch_tasks", dispatch_tasks),
    ("fanout_complex", fanout_complex),
]

__all__ = [n[0] for n in ALL_NODES] + ["ALL_NODES"]
