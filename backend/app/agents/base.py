"""Agent base classes and shared types."""

from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from enum import Enum
import time
import uuid
from dataclasses import dataclass, field


class AgentStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    RETRY_NEEDED = "retry"


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class AgentBaseOutput(BaseModel):
    status: AgentStatus
    agent_name: str
    execution_time_ms: int = 0
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    warnings: list[str] = Field(default_factory=list)
    trace_id: str = ""


# ── Agent-specific output models ────────────────────────────────────────────────


class RetrievalOutput(AgentBaseOutput):
    """Output from Retrieval Agent."""
    retrieved_chunks: list[dict] = Field(default_factory=list)
    coverage_map: dict[str, list[str]] = Field(default_factory=dict)


class OutlineOutput(AgentBaseOutput):
    """Output from Outline Agent."""
    blueprint: list[dict] = Field(default_factory=list)
    distribution_summary: dict[str, dict[str, int]] = Field(default_factory=dict)


class BuilderOutput(AgentBaseOutput):
    """Output from Builder Agent."""
    questions: list[dict] = Field(default_factory=list)
    topics_used: list[str] = Field(default_factory=list)
    chunks_referenced: list[str] = Field(default_factory=list)


class ValidatorOutput(AgentBaseOutput):
    """Output from Validator Agent."""
    validation_passed: bool = False
    issues: list[dict] = Field(default_factory=list)
    bloom_compliance: dict[str, dict[str, Any]] = Field(default_factory=dict)
    scope_violations: list[str] = Field(default_factory=list)
    approved_for_publish: bool = False


class PlannerOutput(AgentBaseOutput):
    """Output from Planner Agent."""
    plan: list[dict] = Field(default_factory=list)
    estimated_token_cost: int = 0
    hitl_checkpoint_after_step: int | None = None


@dataclass
class AgentMetrics:
    """Metrics for agent operations."""
    start_time: float = field(default_factory=time.time)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def finish(self) -> dict:
        """Calculate final metrics."""
        elapsed_ms = int((time.time() - self.start_time) * 1000)
        total_tokens = self.prompt_tokens + self.completion_tokens
        return {
            "execution_time_ms": elapsed_ms,
            "total_tokens": total_tokens,
        }


class ContentFilterRules:
    """Content filter rules for question validation."""

    @staticmethod
    def check_question(question: dict) -> tuple[bool, str | None]:
        """
        Check if a question passes content filter rules.
        Returns (passed, error_message).
        """
        # Rule 1: Stem must be > 20 chars
        stem = question.get("stem", "")
        if len(stem) < 20:
            return False, "Question stem too short (< 20 characters)"

        # Rule 2: MCQ must have 4 unique options
        if question.get("type") == "mcq":
            options = question.get("options", {})
            if len(options) != 4:
                return False, "MCQ must have exactly 4 options"

            option_values = list(options.values())
            if len(set(option_values)) != 4:
                return False, "MCQ options must be unique"

            # Rule 3: Correct answer must be in options
            correct = question.get("correct_answer", "")
            if correct not in options:
                return False, f"Correct answer '{correct}' not in options"

        # Rule 4: Answer should not be leaked in stem
        if question.get("type") == "mcq":
            correct = question.get("correct_answer", "")
            option_text = options.get(correct, "").lower()
            stem_lower = stem.lower()
            # Check if answer text appears in stem
            if option_text and len(option_text) > 3:
                if option_text in stem_lower:
                    return False, "Answer leaked in question stem"

        return True, None
