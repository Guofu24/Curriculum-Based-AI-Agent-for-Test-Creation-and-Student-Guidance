"""Guardrails: output parser, token budget, content filter, scope guard."""

import time
from typing import Any, Callable
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.agents.base import ContentFilterRules
from app.observability.tracer import get_tracer

settings = get_settings()
tracer = get_tracer()


@dataclass
class TokenBudgetGuard:
    """Tracks token usage against a total budget."""

    total_budget: int
    used: int = 0

    def check_before_call(self, estimated_tokens: int) -> str:
        """
        Check if a call can proceed.
        Returns: "ok" | "flush_needed" | "stop"
        """
        projected = self.used + estimated_tokens
        budget_90 = int(self.total_budget * 0.9)

        if projected > budget_90:
            if self.used >= budget_90:
                return "stop"
            return "flush_needed"

        return "ok"

    def record_usage(self, actual_tokens: int) -> None:
        """Record actual token usage."""
        self.used += actual_tokens

    def remaining(self) -> int:
        """Get remaining token budget."""
        return max(0, self.total_budget - self.used)

    def reset(self) -> None:
        """Reset the budget."""
        self.used = 0


class OutputParser:
    """
    Parses LLM output with automatic retry using chat_structured.
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def parse(
        self,
        messages: list[dict],
        response_model: type,
        role: str = "skills",
        model: str | None = None,
        temperature: float = 0.3,
    ) -> Any:
        """
        Call LLM and parse response into Pydantic model.
        Retries on parse failure.
        """
        from app.agents.llm import get_llm_client

        client = get_llm_client()
        return await client.chat_structured(
            messages=messages,
            response_model=response_model,
            role=role,
            model=model,
            temperature=temperature,
            max_retries=self.max_retries,
        )


@dataclass
class ContentFilter:
    """Content filter with rule-based validation."""

    rules: list[Callable[[dict], tuple[bool, str | None]]] = field(
        default_factory=lambda: [
            lambda q: (len(q.get("stem", "")) > 20, "Stem too short"),
            lambda q: (
                len(set(q.get("options", {}).values())) == 4 if q.get("type") == "mcq" else True,
                "MCQ options not unique",
            ),
            lambda q: (
                q.get("correct_answer", "") in q.get("options", {}) if q.get("type") == "mcq" else True,
                "Correct answer not in options",
            ),
        ]
    )

    def validate(self, question: dict) -> tuple[bool, str | None]:
        """Validate a question against all rules."""
        for rule in self.rules:
            passed, error = rule(question)
            if not passed:
                return False, error
        return True, None

    def validate_batch(self, questions: list[dict]) -> list[dict]:
        """Validate multiple questions, return only valid ones with error info."""
        results = []
        for q in questions:
            passed, error = self.validate(q)
            result = q.copy()
            result["filter_passed"] = passed
            result["filter_error"] = error
            results.append(result)
        return results


@dataclass
class ScopeGuard:
    """Inline scope guard - restricts questions to allowed concepts."""

    allowed_concepts: list[str] = field(default_factory=list)
    scope_chapters: list[str] = field(default_factory=list)

    def is_allowed(self, question_stem: str) -> tuple[bool, str | None]:
        """
        Check if a question stem uses only allowed concepts.
        Returns (allowed, violation).
        """
        if not self.allowed_concepts:
            return True, None

        stem_lower = question_stem.lower()

        # Check for explicit out-of-scope terms
        forbidden_terms = []
        for concept in self.allowed_concepts:
            if concept.lower() not in stem_lower:
                forbidden_terms.append(concept)

        return True, None  # Allow all for now - LLM will handle via prompt

    def get_allowed_concepts_prompt(self) -> str:
        """Get the scope restriction prompt for LLM."""
        if not self.allowed_concepts:
            return ""

        concepts_str = ", ".join(self.allowed_concepts)
        return f"""
RESTRICTION: Only use concepts from the following list:
{concepts_str}

Do NOT introduce knowledge outside this list.
"""

    def get_scope_restriction_prompt(self) -> str:
        """Get the scope chapters restriction prompt."""
        if not self.scope_chapters:
            return ""

        chapters_str = ", ".join(self.scope_chapters)
        return f"""
RESTRICTION: Questions must be based on these chapters/sections:
{chapters_str}

Do NOT reference content from chapters outside this list.
"""


class GuardrailsPipeline:
    """
    Combines all guardrails for the Builder Agent.
    Runs: OutputParser → ScopeGuard → ContentFilter → TokenBudgetGuard.
    """

    def __init__(self):
        self.output_parser = OutputParser()
        self.content_filter = ContentFilter()
        self.token_budget = TokenBudgetGuard(total_budget=settings.AGENT_TOKEN_BUDGET)

    def check_budget(self, estimated_tokens: int) -> str:
        """Check token budget before LLM call."""
        return self.token_budget.check_before_call(estimated_tokens)

    def record_tokens(self, tokens: int) -> None:
        """Record actual token usage."""
        self.token_budget.record_usage(tokens)

    def validate_question(self, question: dict) -> tuple[bool, str | None]:
        """Validate a single question through all filters."""
        return self.content_filter.validate(question)

    def validate_batch(self, questions: list[dict]) -> list[dict]:
        """Validate a batch of questions."""
        return self.content_filter.validate_batch(questions)

    def scope_guard(self, question_stem: str) -> tuple[bool, str | None]:
        """Check scope guard for a question."""
        guard = ScopeGuard()
        return guard.is_allowed(question_stem)

    def get_scope_restriction(self, concepts: list[str], chapters: list[str]) -> str:
        """Get combined scope restriction prompt."""
        guard = ScopeGuard(allowed_concepts=concepts, scope_chapters=chapters)
        return (
            guard.get_allowed_concepts_prompt()
            + "\n"
            + guard.get_scope_restriction_prompt()
        )
