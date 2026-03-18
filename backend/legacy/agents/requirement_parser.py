"""
Requirement Parser Agent — Normalize free-text prompts into ExamSpec.

Takes a user's natural language prompt and produces a structured ExamSpec
with exam_type, question_mix, bloom_distribution, selected_scope, etc.

This agent is critical for the "prompt-first" workflow where a lecturer
simply describes what they want instead of filling every form field.

Spec reference: §6.5 — Requirement Parsing & Specification Agent
"""
import json
import logging
from typing import Any

from agents.state import AgentState, ExamSpec, ScopeUnit

logger = logging.getLogger(__name__)


DEFAULT_BLOOM_DISTRIBUTION = {
    "remember": 20,
    "understand": 25,
    "apply": 25,
    "analyze": 15,
    "evaluate": 10,
    "create": 5,
}

EXAM_SPEC_SCHEMA = """
{
  "exam_type": "mcq | essay | mixed",
  "total_questions": <int>,
  "time_limit_minutes": <int | null>,
  "output_language": "vi | en",
  "instructions": "<exam header instructions>",
  "strict_scope_flag": true,
  "bloom_distribution": {"remember": <pct>, "understand": <pct>, "apply": <pct>, "analyze": <pct>, "evaluate": <pct>, "create": <pct>},
  "question_mix": {"mcq": <count>, "essay": <count>},
  "source_prompt": "<original user prompt>"
}
"""


class RequirementParserAgent:
    """
    Parses free-text generation prompts into structured ExamSpec.

    Two modes:
    1. LLM-assisted: Use language model to understand ambiguous prompts.
    2. Rule-based fallback: Extract structured info from request fields.
    """

    def __init__(self, llm=None):
        self.llm = llm

    async def parse(self, state: AgentState) -> ExamSpec:
        """
        Generate ExamSpec from AgentState.

        Priority order:
        1. Explicit request fields (exam_type, question_distribution, etc.)
        2. LLM parsing of prompt (if prompt is provided and fields are missing)
        3. Sensible defaults
        """
        prompt = state.get("prompt", "")
        exam_type = state.get("exam_type", "mixed")
        question_dist = state.get("question_distribution", {})
        constraints = state.get("constraints", {})
        scope = state.get("scope", [])
        chapters = state.get("chapters", [])

        # ── Build question mix from distribution ──
        question_mix = self._compute_question_mix(exam_type, question_dist)
        total_questions = sum(question_mix.values())

        # ── Build bloom distribution ──
        bloom_dist = state.get("bloom_distribution", {})
        if not bloom_dist:
            bloom_levels = constraints.get("bloom_levels", [])
            if bloom_levels and len(bloom_levels) < 6:
                # User selected specific levels, distribute evenly
                pct = 100 // len(bloom_levels)
                bloom_dist = {level: pct for level in bloom_levels}
            else:
                bloom_dist = dict(DEFAULT_BLOOM_DISTRIBUTION)

        # ── Build scope units ──
        selected_scope = self._build_scope_units(scope, chapters)

        # ── Build ExamSpec ──
        spec = ExamSpec(
            exam_type=exam_type,
            total_questions=total_questions,
            time_limit_minutes=state.get("time_limit_minutes"),
            output_language=state.get("output_language", "vi"),
            instructions=state.get("instructions", ""),
            strict_scope_flag=state.get("strict_scope", constraints.get("strict_scope", True)),
            selected_scope=selected_scope,
            bloom_distribution=bloom_dist,
            question_mix=question_mix,
            formatting_preferences=state.get("formatting_preferences", {}),
            source_prompt=prompt,
        )

        logger.info(
            f"[REQ_PARSER] ExamSpec built: {spec.exam_type}, "
            f"{spec.total_questions} questions, "
            f"{len(spec.selected_scope)} scope units"
        )

        return spec

    async def parse_from_prompt(self, prompt: str) -> dict[str, Any]:
        """
        Use LLM to parse a free-text prompt into ExamSpec fields.

        Used when the user provides a prompt like:
        "Tạo đề kiểm tra 15 phút, chương 3-4, 20 câu trắc nghiệm, mức hiểu và vận dụng"
        """
        if not self.llm:
            logger.warning("[REQ_PARSER] No LLM available, using defaults")
            return {}

        system_prompt = f"""You are an exam specification parser. Extract structured exam parameters from the user's prompt.

Output ONLY valid JSON matching this schema:
{EXAM_SPEC_SCHEMA}

Rules:
- If info is missing, use sensible defaults.
- exam_type: "mcq", "essay", or "mixed"
- bloom_distribution percentages should sum to 100
- Detect language from prompt (Vietnamese → "vi", English → "en")
- total_questions defaults to 30 for mcq, 5 for essay, 35 for mixed
"""

        try:
            response = await self.llm.ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ])

            content = response.content if hasattr(response, "content") else str(response)

            # Extract JSON from response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(content[json_start:json_end])
                logger.info(f"[REQ_PARSER] LLM parsed prompt into: {list(parsed.keys())}")
                return parsed
        except Exception as e:
            logger.warning(f"[REQ_PARSER] LLM parsing failed: {e}")

        return {}

    def _compute_question_mix(
        self,
        exam_type: str,
        question_dist: dict,
    ) -> dict[str, int]:
        """Compute total mcq/essay counts from distribution."""
        mcq_dist = question_dist.get("mcq", {})
        essay_dist = question_dist.get("essay", {})

        if isinstance(mcq_dist, dict):
            mcq_total = sum(int(v) for v in mcq_dist.values())
        else:
            mcq_total = int(mcq_dist or 0)

        if isinstance(essay_dist, dict):
            essay_total = sum(int(v) for v in essay_dist.values())
        else:
            essay_total = int(essay_dist or 0)

        if exam_type == "mcq":
            return {"mcq": max(mcq_total, 10), "essay": 0}
        elif exam_type == "essay":
            return {"mcq": 0, "essay": max(essay_total, 3)}
        else:
            return {"mcq": max(mcq_total, 10), "essay": max(essay_total, 2)}

    def _build_scope_units(
        self,
        scope: list[dict],
        chapters: list[int],
    ) -> list[ScopeUnit]:
        """Convert raw scope payload into ScopeUnit dataclasses."""
        units: list[ScopeUnit] = []

        for item in scope:
            units.append(ScopeUnit(
                scope_id=item.get("scope_id", ""),
                scope_type=item.get("scope_type", "chapter"),
                title=item.get("title", ""),
                chapter_number=int(item.get("chapter_number", 0)),
                page_from=item.get("page_from"),
                page_to=item.get("page_to"),
                tags=item.get("tags", []),
            ))

        if not units and chapters:
            for ch in chapters:
                units.append(ScopeUnit(
                    scope_id=f"chapter:{ch}",
                    scope_type="chapter",
                    title=f"Chapter {ch}",
                    chapter_number=ch,
                    tags=[f"chapter:{ch}"],
                ))

        return units
