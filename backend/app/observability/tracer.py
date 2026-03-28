"""Observability: LangFuse tracing and cost tracking."""

from typing import Any, Optional
from uuid import UUID
import time
import hashlib

from app.core.config import get_settings

settings = get_settings()


class LangFuseTracer:
    """
    LangFuse tracing wrapper for multi-agent observability.
    Emits structured spans for each agent call.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and settings.LANGFUSE_ENABLED
        self._client = None

        if self.enabled:
            try:
                from langfuse import Langfuse
                self._client = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_HOST,
                )
            except ImportError:
                self.enabled = False
            except Exception:
                self.enabled = False

    def create_trace(self, name: str, exam_id: str) -> Optional[Any]:
        """Create a new trace for an exam generation."""
        if not self.enabled:
            return None

        try:
            trace = self._client.trace(
                name=name,
                metadata={
                    "exam_id": exam_id,
                    "user_id": None,
                }
            )
            return trace
        except Exception:
            return None

    def create_span(
        self,
        trace: Any,
        name: str,
        agent: str,
        input_data: dict | None = None,
        metadata: dict | None = None,
    ) -> Optional[Any]:
        """Create a span within a trace."""
        if not self.enabled or trace is None:
            return None

        try:
            span = trace.span(
                name=name,
                metadata={
                    "agent": agent,
                    **(metadata or {}),
                }
            )
            return span
        except Exception:
            return None

    def emit_llm_call(
        self,
        span: Any,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        cost_usd: float,
        status: str = "success",
    ) -> None:
        """Emit an LLM call within a span."""
        if not self.enabled or span is None:
            return

        try:
            span.generation(
                model=model,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                latency=latency_ms / 1000,
                usage_amount=cost_usd,
                status=status,
            )
        except Exception:
            pass

    def emit_event(
        self,
        span: Any,
        name: str,
        metadata: dict | None = None,
    ) -> None:
        """Emit an event within a span."""
        if not self.enabled or span is None:
            return

        try:
            span.event(
                name=name,
                metadata=metadata or {},
            )
        except Exception:
            pass

    def finalize_span(
        self,
        span: Any,
        output: Any = None,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        """Finalize a span."""
        if not self.enabled or span is None:
            return

        try:
            if error:
                span.level = "ERROR"
            span.end()
        except Exception:
            pass

    def finalize_trace(self, trace: Any) -> None:
        """Finalize and flush a trace."""
        if not self.enabled or trace is None:
            return

        try:
            trace.flush()
        except Exception:
            pass


# Singleton
_tracer: LangFuseTracer | None = None


def get_tracer() -> LangFuseTracer:
    """Get the singleton tracer."""
    global _tracer
    if _tracer is None:
        _tracer = LangFuseTracer()
    return _tracer


# ── Cost Tracking ────────────────────────────────────────────────────────────

class ExamCostTracker:
    """
    Tracks token usage and cost for each exam generation.
    Aggregates data from all agents.
    """

    def __init__(self):
        self.agents: dict[str, dict] = {}
        self.total_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.models_used: dict[str, str] = {}

    def record_agent(
        self,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_ms: int,
    ) -> None:
        """Record token usage for an agent."""
        self.agents[agent_name] = {
            "tokens": prompt_tokens + completion_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": cost_usd,
            "latency_ms": latency_ms,
            "model": model,
        }
        self.total_tokens += prompt_tokens + completion_tokens
        self.total_cost_usd += cost_usd
        self.models_used[agent_name] = model

    def get_report(self) -> dict:
        """Get the cost report for the exam."""
        breakdown = {}
        for agent, data in self.agents.items():
            breakdown[agent] = {
                "tokens": data["tokens"],
                "cost": round(data["cost"], 6),
                "model": data["model"],
                "latency_ms": data["latency_ms"],
            }

        return {
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "breakdown": breakdown,
            "model_used": self.models_used,
        }

    @staticmethod
    def hash_input(data: dict) -> str:
        """Create a hash of input data for deduplication."""
        import json
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
