"""
Blueprint Agent

Responsibilities:
- Create structured exam blueprint from user configuration
- Map questions to Bloom's taxonomy levels
- Distribute difficulty across the exam
- Plan which chapters/topics each question should cover
"""
import json
import re
import logging

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

from agents.state import ExamBlueprint, QuestionSlot


BLOOM_DIFFICULTY_MAP = {
    "remember": 0.1,
    "understand": 0.25,
    "apply": 0.5,
    "analyze": 0.65,
    "evaluate": 0.8,
    "create": 0.95,
}

BLUEPRINT_SYSTEM_PROMPT = """You are an expert exam blueprint planner. Your job is to create a structured plan for an exam.

Given the user's requirements (chapters, question types, difficulty distribution, Bloom's taxonomy levels), 
produce a JSON blueprint that specifies each question slot.

Each slot must have:
- slot_number: sequential number starting from 1
- question_type: "mcq" or "essay"
- bloom_level: one of "remember", "understand", "apply", "analyze", "evaluate", "create"
- difficulty_score: 0.0 (easiest) to 1.0 (hardest)
- target_chapter: which chapter this question should test
- target_topics: list of 1-3 specific topics/concepts from that chapter

Rules:
1. Match the requested difficulty distribution exactly
2. Spread questions across requested chapters evenly unless told otherwise
3. If "gradually_increasing" is true, order slots from lowest to highest difficulty
4. Map difficulty levels: easy=0.1-0.3, medium=0.4-0.6, hard=0.7-1.0
5. Ensure Bloom's taxonomy levels align with difficulty (remember→easy, create→hard)

Respond ONLY with valid JSON in this format:
{
  "title": "exam title",
  "total_questions": N,
  "slots": [
    {
      "slot_number": 1,
      "question_type": "mcq",
      "bloom_level": "remember",
      "difficulty_score": 0.2,
      "target_chapter": 1,
      "target_topics": ["topic1", "topic2"]
    }
  ]
}"""


class BlueprintAgent:
    """Plans the structural blueprint of an exam before question generation."""

    def __init__(self, llm):
        self.llm = llm

    async def create_blueprint(
        self,
        prompt: str,
        exam_type: str,
        difficulty: str,
        chapters: list[int],
        question_distribution: dict,
        gradually_increasing: bool,
        constraints: dict,
        textbook_metadata: dict,
    ) -> ExamBlueprint:
        """Create an exam blueprint based on user configuration."""

        # Build the request for the LLM
        user_message = self._build_request(
            prompt=prompt,
            exam_type=exam_type,
            difficulty=difficulty,
            chapters=chapters,
            question_distribution=question_distribution,
            gradually_increasing=gradually_increasing,
            constraints=constraints,
            textbook_metadata=textbook_metadata,
        )

        messages = [
            SystemMessage(content=BLUEPRINT_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        response = await self.llm.ainvoke(messages)

        # Parse the JSON response
        blueprint_data = self._parse_blueprint(response.content)

        return self._build_blueprint(blueprint_data)

    def _build_request(
        self,
        prompt: str,
        exam_type: str,
        difficulty: str,
        chapters: list[int],
        question_distribution: dict,
        gradually_increasing: bool,
        constraints: dict,
        textbook_metadata: dict,
    ) -> str:
        """Build the user message for blueprint generation."""

        # Calculate total questions
        mcq_dist = question_distribution.get("mcq", {})
        essay_dist = question_distribution.get("essay", {})
        total_mcq = sum(mcq_dist.values()) if isinstance(mcq_dist, dict) else 0
        total_essay = sum(essay_dist.values()) if isinstance(essay_dist, dict) else 0

        chapter_info = ""
        if textbook_metadata and textbook_metadata.get("chapters"):
            relevant = [
                ch for ch in textbook_metadata["chapters"]
                if ch["chapter_number"] in chapters
            ]
            chapter_info = "\n".join(
                f"- Chapter {ch['chapter_number']}: {ch.get('title', 'N/A')}"
                for ch in relevant
            )

        bloom_levels = constraints.get("bloom_levels", ["remember", "understand", "apply", "analyze"])

        return f"""Create an exam blueprint with these requirements:

User prompt: {prompt}

Exam type: {exam_type}
Overall difficulty: {difficulty}
Chapters to cover: {chapters}
Gradually increasing difficulty: {gradually_increasing}

Question distribution:
- MCQ: easy={mcq_dist.get('easy', 0)}, medium={mcq_dist.get('medium', 0)}, hard={mcq_dist.get('hard', 0)} (total: {total_mcq})
- Essay: easy={essay_dist.get('easy', 0)}, medium={essay_dist.get('medium', 0)}, hard={essay_dist.get('hard', 0)} (total: {total_essay})

Allowed Bloom's taxonomy levels: {bloom_levels}

Available chapters:
{chapter_info}

Constraints:
- Strict grounding (textbook only): {constraints.get('strict_grounding', True)}
- Allow applied questions: {constraints.get('allow_applied_questions', True)}
- Creativity level: {constraints.get('creativity_level', 0.5)}
"""

    def _parse_blueprint(self, response_text: str) -> dict:
        """Parse LLM JSON response, handling markdown code blocks and extra text."""
        text = response_text.strip()
        logger.debug(f"Blueprint LLM raw response (first 500 chars): {text[:500]}")

        if not text:
            logger.warning("Blueprint LLM returned empty response, using fallback")
            return self._fallback_blueprint()

        # 1. Try extracting JSON from ```json ... ``` or ``` ... ``` blocks
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            text = code_block.group(1)

        # 2. Try extracting the outermost {...} block (handles prefix/suffix text)
        if not text.startswith("{"):
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                text = brace_match.group(0)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Blueprint JSON parse failed: {e}. Raw: {text[:300]}")
            return self._fallback_blueprint()

    def _fallback_blueprint(self) -> dict:
        """Return a minimal valid blueprint when LLM output cannot be parsed."""
        return {
            "title": "Generated Exam",
            "total_questions": 5,
            "slots": [
                {
                    "slot_number": i + 1,
                    "question_type": "mcq",
                    "bloom_level": "understand",
                    "difficulty_score": 0.4,
                    "target_chapter": 1,
                    "target_topics": ["general concept"],
                }
                for i in range(5)
            ],
        }

    def _build_blueprint(self, data: dict) -> ExamBlueprint:
        """Convert parsed JSON to ExamBlueprint dataclass."""
        slots = []
        for slot_data in data.get("slots", []):
            slots.append(QuestionSlot(
                slot_number=slot_data["slot_number"],
                question_type=slot_data["question_type"],
                bloom_level=slot_data["bloom_level"],
                difficulty_score=slot_data["difficulty_score"],
                target_chapter=slot_data["target_chapter"],
                target_topics=slot_data.get("target_topics", []),
            ))

        # Compute distributions
        difficulty_dist = {}
        bloom_dist = {}
        for slot in slots:
            # Difficulty buckets
            if slot.difficulty_score <= 0.3:
                bucket = "easy"
            elif slot.difficulty_score <= 0.6:
                bucket = "medium"
            else:
                bucket = "hard"
            difficulty_dist[bucket] = difficulty_dist.get(bucket, 0) + 1

            # Bloom distribution
            bloom_dist[slot.bloom_level] = bloom_dist.get(slot.bloom_level, 0) + 1

        return ExamBlueprint(
            title=data.get("title", "Untitled Exam"),
            total_questions=data.get("total_questions", len(slots)),
            slots=slots,
            difficulty_distribution=difficulty_dist,
            bloom_distribution=bloom_dist,
        )
