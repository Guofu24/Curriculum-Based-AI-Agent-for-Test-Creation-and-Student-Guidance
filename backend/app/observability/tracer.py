"""Observability: LangFuse tracing and cost tracking.

Phase 15 — LangFuse Tracing + Cost Tracking
============================================
This module provides:
- LangfuseClient singleton (lazy init, graceful fallback)
- CurriculumTracer: trace context manager + agent/skill/llm decorators
- ExamCostTracker: per-exam cost aggregation
- Hash helpers for input/output deduplication

Design principles:
- ALWAYS calls span.end() in finally block — no span leaks
- LangFuse is non-critical: if init fails, all tracing methods become no-ops
- Cost calculation uses MODEL_PRICING dict — never hardcoded numbers
- Root trace is created once per exam in exam_task.py
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Optional
from contextlib import contextmanager

from app.core.config import get_settings

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Hash helpers ────────────────────────────────────────────────────────────────

def hash_input(data: dict) -> str:
    """Short hash of input dict for span metadata."""
    try:
        content = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    except Exception:
        return hashlib.sha256(str(data).encode()).hexdigest()[:16]


def hash_output(data: Any) -> str:
    """Short hash of output for span metadata."""
    try:
        content = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    except Exception:
        return hashlib.sha256(str(data).encode()).hexdigest()[:16]


# ── LangfuseClient accessor ────────────────────────────────────────────────────

def _get_lf() -> Optional[Any]:
    """Get Langfuse client (lazy import, no error if not configured)."""
    try:
        from langfuse import Langfuse
        from app.core.config import get_settings
        s = get_settings()

        if not s.LANGFUSE_ENABLED:
            return None
        if not s.LANGFUSE_PUBLIC_KEY or not s.LANGFUSE_SECRET_KEY:
            return None

        return Langfuse(
            public_key=s.LANGFUSE_PUBLIC_KEY,
            secret_key=s.LANGFUSE_SECRET_KEY,
            host=s.LANGFUSE_HOST,
        )
    except ImportError:
        logger.debug("langfuse not installed — tracing disabled")
        return None
    except Exception as e:
        logger.debug(f"Langfuse init failed: {e}")
        return None


# ── CurriculumTracer ───────────────────────────────────────────────────────────

class CurriculumTracer:
    """
    LangFuse tracing wrapper for the multi-agent exam generation pipeline.

    Wraps every agent call, LLM call, and skill call as a LangFuse span.
    Provides a trace context manager for root exam-level traces.

    Non-critical: all methods safely no-op when LangFuse is unavailable.
    """

    def __init__(self, enabled: Optional[bool] = None):
        self._lf: Optional[Any] = None
        self._enabled: bool = (enabled is not False) and settings.LANGFUSE_ENABLED

    @property
    def enabled(self) -> bool:
        if not self._enabled:
            return False
        if self._lf is None:
            self._lf = _get_lf()
        return self._lf is not None

    # ── Root trace context manager ─────────────────────────────────────────────

    @contextmanager
    def trace(self, exam_id: str, metadata: Optional[dict] = None):
        """
        Root trace context manager for an entire exam generation session.

        Usage:
            tracer = get_tracer()
            with tracer.trace(exam_id="...", metadata={...}):
                # all agent spans are children of this trace
                ...

        Ensures trace.flush() is called on exit.
        """
        trace_obj: Any = None

        if self.enabled:
            try:
                trace_obj = self._lf.trace(
                    name=f"exam_generate_{exam_id}",
                    id=exam_id,
                    metadata={
                        "exam_id": exam_id,
                        **(metadata or {}),
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to create Langfuse trace: {e}")

        try:
            yield trace_obj
        finally:
            if trace_obj is not None:
                try:
                    trace_obj.flush()
                except Exception as e:
                    logger.warning(f"Langfuse trace flush failed: {e}")

    # ── Agent span decorator ───────────────────────────────────────────────────

    def agent_span(self, agent_name: str) -> Callable:
        """
        Decorator that wraps an async agent method with a LangFuse span.

        The decorated method must return an AgentBaseOutput (or dict with
        'token_usage' and 'status' keys). The span metadata is updated
        after the method returns with token_usage and cost data.

        Usage:
            @tracer.agent_span("outline_agent")
            async def create_outline(self, ...) -> OutlineOutput:
                ...
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs) -> Any:
                start_time = time.time()
                status = "success"
                error_msg: Optional[str] = None
                span: Any = None

                if self.enabled:
                    try:
                        span = self._lf.span(
                            name=f"agent:{agent_name}",
                            metadata={
                                "agent": agent_name,
                                "type": "agent",
                                "input_hash": hash_input({"args": str(args[:3]), "kwargs": list(kwargs.keys())}),
                            },
                        )
                    except Exception as e:
                        logger.debug(f"Failed to create agent span: {e}")

                try:
                    result = await func(*args, **kwargs)

                    # Extract token_usage from result for cost tracking
                    token_usage_data: dict[str, Any] = {}
                    if hasattr(result, "token_usage"):
                        tu = result.token_usage
                        if hasattr(tu, "model_dump"):
                            token_usage_data = tu.model_dump()
                        else:
                            token_usage_data = {"prompt_tokens": 0, "completion_tokens": 0}
                    elif isinstance(result, dict):
                        tu = result.get("token_usage", {})
                        token_usage_data = {
                            "prompt_tokens": tu.get("prompt_tokens", 0),
                            "completion_tokens": tu.get("completion_tokens", 0),
                            "total_tokens": tu.get("total_tokens", 0),
                            "estimated_cost_usd": tu.get("estimated_cost_usd", 0.0),
                        }

                    # Compute cost
                    from app.observability.cost import calculate_cost
                    model = kwargs.get("model", settings.LLM_MODEL_STRONG)
                    cost_usd = calculate_cost(
                        model,
                        token_usage_data.get("prompt_tokens", 0),
                        token_usage_data.get("completion_tokens", 0),
                    )

                    elapsed_ms = int((time.time() - start_time) * 1000)

                    if span is not None:
                        try:
                            span.update(
                                metadata={
                                    "latency_ms": elapsed_ms,
                                    "token_usage": token_usage_data,
                                    "estimated_cost_usd": cost_usd,
                                    "status": status,
                                    "agent_status": getattr(result, "status", None),
                                }
                            )
                        except Exception as e:
                            logger.debug(f"Failed to update agent span: {e}")

                    return result

                except Exception as exc:
                    status = "error"
                    error_msg = str(exc)

                    if span is not None:
                        try:
                            span.update(
                                level="ERROR",
                                status_message=error_msg,
                            )
                        except Exception:
                            pass
                    raise

                finally:
                    if span is not None:
                        try:
                            span.end()
                        except Exception:
                            pass

            return wrapper
        return decorator

    # ── Skill span decorator ─────────────────────────────────────────────────

    def skill_span(self, skill_name: str) -> Callable:
        """
        Decorator that wraps a skill method (sync or async) with a LangFuse span.

        Usage:
            @tracer.skill_span("bloom_classifier")
            async def classify(self, ...) -> dict:
                ...
        """
        def decorator(func: Callable) -> Callable:
            import inspect as _inspect

            common_span_setup = lambda: (
                self._lf.span(
                    name=f"skill:{skill_name}",
                    metadata={
                        "skill_name": skill_name,
                        "type": "skill",
                    },
                )
                if self.enabled
                else None
            )

            common_span_update = lambda span, result, elapsed_ms, status, exc_msg=None: (
                (
                    span.update(
                        metadata={
                            "latency_ms": elapsed_ms,
                            "output_hash": hash_output(result),
                            "status": status,
                        }
                        if status == "success"
                        else None,
                        level="ERROR" if exc_msg else None,
                        status_message=exc_msg,
                    )
                )
                if span is not None
                else None
            )

            common_span_end = lambda span: (
                (span.end(), None) if span is not None else None
            )

            if _inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def wrapper(*args, **kwargs) -> Any:
                    start_time = time.time()
                    span = None

                    if self.enabled:
                        try:
                            span = common_span_setup()
                        except Exception:
                            pass

                    try:
                        result = await func(*args, **kwargs)
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        if span is not None:
                            try:
                                common_span_update(span, result, elapsed_ms, "success")
                            except Exception:
                                pass
                        return result

                    except Exception as exc:
                        if span is not None:
                            try:
                                common_span_update(span, None, 0, "error", str(exc))
                            except Exception:
                                pass
                        raise

                    finally:
                        if span is not None:
                            try:
                                span.end()
                            except Exception:
                                pass

                return wrapper
            else:
                @functools.wraps(func)
                def wrapper(*args, **kwargs) -> Any:
                    start_time = time.time()
                    span = None

                    if self.enabled:
                        try:
                            span = common_span_setup()
                        except Exception:
                            pass

                    try:
                        result = func(*args, **kwargs)
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        if span is not None:
                            try:
                                common_span_update(span, result, elapsed_ms, "success")
                            except Exception:
                                pass
                        return result

                    except Exception as exc:
                        if span is not None:
                            try:
                                common_span_update(span, None, 0, "error", str(exc))
                            except Exception:
                                pass
                        raise

                    finally:
                        if span is not None:
                            try:
                                span.end()
                            except Exception:
                                pass

                return wrapper

        return decorator

    # ── LLM generation span helper ────────────────────────────────────────────

    def generation(
        self,
        span: Any,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        cost_usd: float,
        status: str = "success",
    ) -> None:
        """
        Emit an LLM generation span within a parent span.

        Usage:
            tracer.generation(
                parent_span,
                model="gpt-4o",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                cost_usd=0.001,
            )
        """
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
        except Exception as e:
            logger.debug(f"Failed to emit LLM generation: {e}")

    # ── Generic span helpers ─────────────────────────────────────────────────

    def event(
        self,
        span: Any,
        name: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Emit a named event within a span."""
        if not self.enabled or span is None:
            return
        try:
            span.event(name=name, metadata=metadata or {})
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracer: Optional[CurriculumTracer] = None


def get_tracer() -> CurriculumTracer:
    """Get the singleton CurriculumTracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = CurriculumTracer()
    return _tracer


# ── ExamCostTracker (kept for compatibility) ──────────────────────────────────

class ExamCostTracker:
    """
    Deprecated: prefer ExamCostReport from app/observability/cost.py.
    Kept for any existing code that imports from here.
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
        return {
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "breakdown": {
                name: {
                    "tokens": d["tokens"],
                    "cost": round(d["cost"], 6),
                    "model": d["model"],
                    "latency_ms": d["latency_ms"],
                }
                for name, d in self.agents.items()
            },
            "model_used": self.models_used,
        }
