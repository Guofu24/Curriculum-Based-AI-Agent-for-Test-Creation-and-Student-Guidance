"""
Question Generator Agent

Responsibilities:
- Generate exam questions from blueprint slots + retrieved context
- Support MCQ and Essay question types
- Ground all content in retrieved textbook material
- Produce structured JSON output per question
- Respect difficulty scores and Bloom's taxonomy levels
"""
import json
import re
import logging

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

from agents.state import GeneratedQuestion, QuestionSlot, RetrievedContext


MCQ_SYSTEM_PROMPT = """You are an expert exam question writer. Generate a multiple-choice question based on the provided textbook context.

STRICT RULES:
1. The question MUST be answerable from the provided context only
2. Do NOT introduce information not present in the context
3. Create exactly 4 options (A, B, C, D) with only ONE correct answer
4. Distractors (wrong options) must be plausible but clearly wrong based on the context
5. Match the specified difficulty level and Bloom's taxonomy level

Bloom's Taxonomy Guide:
- remember: Recall facts, definitions, terminology
- understand: Explain concepts, summarize, paraphrase  
- apply: Use knowledge in new situations, solve problems
- analyze: Break down information, identify patterns, compare/contrast
- evaluate: Judge, critique, assess validity
- create: Design, construct, produce original work

Difficulty Guide (0.0 = easiest, 1.0 = hardest):
- 0.0-0.3: Straightforward recall or basic understanding
- 0.4-0.6: Requires combining concepts, applying to scenarios
- 0.7-1.0: Complex analysis, subtle distinctions, multi-step reasoning

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
  "explanation": "Brief explanation of why the answer is correct, referencing the source material"
}"""


ESSAY_SYSTEM_PROMPT = """You are an expert exam question writer. Generate an essay/short-answer question based on the provided textbook context.

STRICT RULES:
1. The question MUST be answerable from the provided context only
2. Do NOT introduce information not present in the context
3. Match the specified difficulty level and Bloom's taxonomy level
4. For applied questions, create realistic scenarios that use ONLY concepts from the context
5. Provide a model answer that references specific content from the context

Bloom's Taxonomy Guide:
- remember: Recall and list specific facts
- understand: Explain concepts in own words
- apply: Use concepts to solve a practical problem
- analyze: Compare, contrast, examine relationships
- evaluate: Assess, critique, justify positions
- create: Design solutions, propose new approaches

Respond ONLY with valid JSON:
{
  "content": "The essay question text",
  "correct_answer": "Model answer that demonstrates what a complete response should cover",
  "explanation": "Grading rubric or key points to look for"
}"""


APPLIED_QUESTION_PROMPT = """Additionally, this is an APPLIED question. Create a realistic real-world scenario 
that requires applying the concepts from the context. The scenario should:
- Be practical and relatable
- Only require knowledge that EXISTS in the provided context
- NOT use concepts from topics beyond what is covered in the context
- Test the student's ability to transfer textbook knowledge to new situations"""


class QuestionGeneratorAgent:
    """Generates exam questions grounded in retrieved textbook content."""

    def __init__(self, llm):
        self.llm = llm

    async def generate_questions(
        self,
        slots: list[QuestionSlot],
        contexts: list[RetrievedContext],
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """Generate all questions for the exam based on blueprint and context."""
        questions = []

        for slot, context in zip(slots, contexts):
            question = await self._generate_single(slot, context, constraints)
            questions.append(question)

        return questions

    async def _generate_single(
        self,
        slot: QuestionSlot,
        context: RetrievedContext,
        constraints: dict,
    ) -> GeneratedQuestion:
        """Generate a single question for a blueprint slot."""

        if slot.question_type == "mcq":
            system_prompt = MCQ_SYSTEM_PROMPT
        else:
            system_prompt = ESSAY_SYSTEM_PROMPT

        # Add applied question guidance if difficulty is high
        if constraints.get("allow_applied_questions") and slot.difficulty_score >= 0.6:
            system_prompt += "\n\n" + APPLIED_QUESTION_PROMPT

        # Add strict grounding reminder
        if constraints.get("strict_grounding", True):
            system_prompt += (
                "\n\nCRITICAL: You are in STRICT GROUNDING mode. "
                "Every fact, concept, and piece of information in the question "
                "MUST come directly from the provided context. "
                "Do NOT use any external knowledge."
            )

        user_message = f"""Generate a {slot.question_type.upper()} question with these specifications:

Chapter: {slot.target_chapter}
Topics: {', '.join(slot.target_topics) if slot.target_topics else 'General'}
Bloom's Level: {slot.bloom_level}
Difficulty: {slot.difficulty_score:.2f} (scale 0.0-1.0)
Question Number: {slot.slot_number}

=== TEXTBOOK CONTEXT (use ONLY this information) ===

{context.combined_text}

=== END CONTEXT ===

Generate the question now."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]

        response = await self.llm.ainvoke(messages)
        question_data = self._parse_response(response.content)

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
            source_chunks=[c["id"] for c in context.chunks],
            source_texts=[c["text"] for c in context.chunks],
        )

    def _parse_response(self, response_text: str) -> dict:
        """Parse LLM JSON response, handling markdown and extra text."""
        text = response_text.strip()
        logger.debug(f"QuestionGen LLM raw (first 300): {text[:300]}")

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
            logger.warning(f"QuestionGen JSON parse failed: {e}. Raw: {text[:200]}")
            return {}

    async def regenerate_single(
        self,
        original_question: GeneratedQuestion,
        context: RetrievedContext,
        constraints: dict,
        edit_prompt: str = "",
    ) -> GeneratedQuestion:
        """Regenerate a single question, preserving its slot specifications."""
        slot = QuestionSlot(
            slot_number=original_question.slot_number,
            question_type=original_question.question_type,
            bloom_level=original_question.bloom_level,
            difficulty_score=original_question.difficulty_score,
            target_chapter=0,  # will use existing context
            target_topics=[],
        )

        if edit_prompt:
            # Add specific edit guidance
            constraints = {**constraints, "_edit_prompt": edit_prompt}

        return await self._generate_single(slot, context, constraints)
