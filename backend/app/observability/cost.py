"""Cost tracking for exam generation.

Centralized cost model for all agents and LLM calls.
Prices are per 1M tokens (matching OpenAI 2024 pricing).
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


# ── Model Pricing (USD per 1M tokens — OpenAI 2024) ───────────────────────────

MODEL_PRICING: dict[str, dict[str, float]] = {
    # GPT-4o family
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # GPT-4-Turbo
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4-turbo-2024-04-09": {"input": 10.0, "output": 30.0},
    # Legacy GPT-4
    "gpt-4": {"input": 30.0, "output": 60.0},
    # Embeddings
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
) -> float:
    """
    Calculate estimated cost in USD for a model call.

    Uses MODEL_PRICING dict — NOT hardcoded values.
    Falls back to gpt-4o-mini pricing for unknown models.

    Formula: (prompt_tokens / 1_000_000) * input_price
           + (completion_tokens / 1_000_000) * output_price
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-4o-mini"])
    cost = (
        (prompt_tokens / 1_000_000) * pricing["input"]
        + (completion_tokens / 1_000_000) * pricing["output"]
    )
    return round(cost, 6)


# ── Per-Exam Cost Report ────────────────────────────────────────────────────────


class AgentCostItem(BaseModel):
    """Cost breakdown for a single agent."""
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    model: str = ""


class ExamCostReport(BaseModel):
    """
    Full cost report for an exam generation session.
    Aggregated per-agent with totals.

    Saved to exams.cost_report (JSONB) after generation completes.
    """
    exam_id: str = ""
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    breakdown: dict[str, AgentCostItem] = Field(default_factory=dict)
    model_used: dict[str, str] = Field(default_factory=dict)

    def add_agent(
        self,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_ms: int,
    ) -> None:
        """Accumulate cost data for an agent."""
        tokens = prompt_tokens + completion_tokens
        self.total_tokens += tokens
        self.total_cost_usd = round(self.total_cost_usd + cost_usd, 6)

        item = AgentCostItem(
            tokens=tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost_usd, 6),
            latency_ms=latency_ms,
            model=model,
        )
        self.breakdown[agent_name] = item
        self.model_used[agent_name] = model

    def to_dict(self) -> dict:
        """Serialize to dict for JSONB storage."""
        return {
            "exam_id": self.exam_id,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "breakdown": {
                name: item.model_dump()
                for name, item in self.breakdown.items()
            },
            "model_used": self.model_used,
        }
