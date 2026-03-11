"""
Gemini-Native Question Generator

Uses the `google-genai` SDK directly (not LangChain) to call Gemini with
a File API reference. This lets Gemini process the *entire* uploaded PDF
as context — bypassing the RAG token-limit bottleneck.

Activated when:
  - LLM_PROVIDER = "google"
  - GEMINI_USE_FILE_API = True
  - A valid genai File reference exists in the agent state
"""

import json
import re
import logging
from typing import Optional, Any

from config import settings
from agents.state import GeneratedQuestion, QuestionSlot, RetrievedContext

logger = logging.getLogger(__name__)


# ── Prompt templates (aligned with QuestionGeneratorAgent) ──────────

MCQ_PROMPT = """You are an expert exam question writer.

Generate a MULTIPLE-CHOICE question based on the *attached textbook file*.

STRICT RULES:
1. The question MUST be answerable from the textbook content only
2. Do NOT introduce information not present in the textbook
3. Create exactly 4 options (A, B, C, D) with only ONE correct answer
4. Distractors must be plausible but clearly wrong based on the textbook
5. Match the specified difficulty level and Bloom's taxonomy level

Bloom's Taxonomy Guide:
- remember: Recall facts, definitions, terminology
- understand: Explain concepts, summarize, paraphrase
- apply: Use knowledge in new situations, solve problems
- analyze: Break down information, identify patterns
- evaluate: Judge, critique, assess validity
- create: Design, construct, produce original work

Difficulty Guide (0.0 = easiest, 1.0 = hardest):
- 0.0-0.3: Straightforward recall or basic understanding
- 0.4-0.6: Requires combining concepts
- 0.7-1.0: Complex analysis, multi-step reasoning

Respond ONLY with valid JSON:
{
  "content": "The question text",
  "options": [
    {"label": "A", "text": "option text"},
    {"label": "B", "text": "option text"},
    {"label": "C", "text": "option text"},
    {"label": "D", "text": "option text"}
  ],
  "correct_answer": "A",
  "explanation": "Brief explanation referencing the textbook"
}"""


ESSAY_PROMPT = """You are an expert exam question writer.

Generate an ESSAY/SHORT-ANSWER question based on the *attached textbook file*.

STRICT RULES:
1. The question MUST be answerable from the textbook content only
2. Do NOT introduce information not present in the textbook
3. Match the specified difficulty level and Bloom's taxonomy level
4. Provide a model answer referencing specific textbook content

Respond ONLY with valid JSON:
{
  "content": "The essay question text",
  "correct_answer": "Model answer covering key points from the textbook",
  "explanation": "Grading rubric or key evaluation points"
}"""


class GeminiNativeQuestionGenerator:
    """
    Generates exam questions by sending the uploaded PDF file directly
    to Gemini via the google-genai SDK.

    This class mirrors the interface of QuestionGeneratorAgent but uses
    the native SDK instead of LangChain, allowing File objects.
    """

    def __init__(self):
        from google import genai
        self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self._model = settings.GOOGLE_MODEL

    async def generate_questions(
        self,
        slots: list[QuestionSlot],
        gemini_file: Any,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """
        Generate all questions in one or more Gemini calls,
        passing the file reference as context.
        """
        questions: list[GeneratedQuestion] = []

        for slot in slots:
            question = await self._generate_single(slot, gemini_file, constraints)
            questions.append(question)

        return questions

    async def _generate_single(
        self,
        slot: QuestionSlot,
        gemini_file: Any,
        constraints: dict,
    ) -> GeneratedQuestion:
        """Generate a single question using the uploaded file + slot specs."""

        system_prompt = MCQ_PROMPT if slot.question_type == "mcq" else ESSAY_PROMPT

        # Add strict grounding reminder
        if constraints.get("strict_grounding", True):
            system_prompt += (
                "\n\nCRITICAL: STRICT GROUNDING mode. "
                "Every fact, concept, and piece of information in the question "
                "MUST come directly from the attached textbook. "
                "Do NOT use any external knowledge."
            )

        user_message = (
            f"From the attached textbook, generate a {slot.question_type.upper()} question:\n\n"
            f"Chapter: {slot.target_chapter}\n"
            f"Topics: {', '.join(slot.target_topics) if slot.target_topics else 'General'}\n"
            f"Bloom's Level: {slot.bloom_level}\n"
            f"Difficulty: {slot.difficulty_score:.2f} (scale 0.0-1.0)\n"
            f"Question Number: {slot.slot_number}\n\n"
            f"Generate the question now."
        )

        # Call Gemini with the file reference + text prompt
        import asyncio
        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self._model,
            contents=[system_prompt + "\n\n" + user_message, gemini_file],
        )

        question_data = self._parse_response(response.text)

        # Build GeneratedQuestion
        options = None
        if slot.question_type == "mcq" and "options" in question_data:
            options = question_data["options"]

        return GeneratedQuestion(
            slot_number=slot.slot_number,
            question_type=slot.question_type,
            bloom_level=slot.bloom_level,
            difficulty_score=slot.difficulty_score,
            content=question_data.get("content", ""),
            options=options,
            correct_answer=question_data.get("correct_answer", ""),
            explanation=question_data.get("explanation", ""),
            source_chunks=[],  # No RAG chunks — whole file is the source
            source_texts=[],
        )

    def _parse_response(self, response_text: str) -> dict:
        """Parse Gemini JSON response, handling markdown fences."""
        text = response_text.strip()
        logger.debug(f"GeminiNative LLM raw (first 300): {text[:300]}")

        if not text:
            return {}

        # Extract from ```json ... ``` block
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            text = code_block.group(1)
        elif not text.startswith("{"):
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                text = brace_match.group(0)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"GeminiNative JSON parse failed: {e}. Raw: {text[:200]}")
            return {}
