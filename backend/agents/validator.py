"""
Validator Agent (Anti-Hallucination)

Responsibilities:
- Verify each generated question is grounded in source material
- Check for hallucinated facts, concepts, or claims
- Validate difficulty alignment with Bloom's taxonomy
- Provide citation links back to source chunks
- Flag problematic questions for human review
"""
import json
import re

from langchain_core.messages import SystemMessage, HumanMessage

from agents.state import GeneratedQuestion


VALIDATION_SYSTEM_PROMPT = """You are a strict exam quality validator. Your job is to verify that generated exam questions are:

1. **Grounded**: Every fact and concept in the question comes from the provided source context
2. **Accurate**: The correct answer is actually correct based on the source
3. **Non-hallucinated**: No information is fabricated or assumed beyond the source
4. **Difficulty-appropriate**: The question matches its intended difficulty and Bloom's level
5. **Well-formed**: The question is clear, unambiguous, and answerable

For each question, analyze:
- Does every claim in the question appear in the source text?
- Is the correct answer supported by the source?
- Are MCQ distractors plausible but clearly wrong per the source?
- Does the difficulty match the intended Bloom's level?

Respond with JSON:
{
  "is_valid": true/false,
  "grounding_score": 0.0-1.0,
  "accuracy_score": 0.0-1.0,
  "difficulty_alignment": 0.0-1.0,
  "hallucination_flags": ["list of specific hallucinated claims, if any"],
  "issues": ["list of issues found"],
  "suggestions": ["list of improvement suggestions"],
  "overall_quality": 0.0-1.0
}"""


class ValidatorAgent:
    """Validates generated questions for grounding, accuracy, and quality."""

    QUALITY_THRESHOLD = 0.7  # minimum quality score to pass

    def __init__(self, llm):
        self.llm = llm

    async def validate_questions(
        self,
        questions: list[GeneratedQuestion],
        strict_grounding: bool = True,
    ) -> tuple[list[GeneratedQuestion], dict]:
        """
        Validate all questions. Returns (validated_questions, summary).
        Questions below threshold are flagged but not removed.
        """
        validated = []
        total_passed = 0
        total_failed = 0
        all_hallucination_flags = []

        for question in questions:
            validated_q, result = await self._validate_single(
                question, strict_grounding
            )
            validated.append(validated_q)

            if validated_q.is_validated:
                total_passed += 1
            else:
                total_failed += 1

            if result.get("hallucination_flags"):
                all_hallucination_flags.extend(result["hallucination_flags"])

        summary = {
            "total": len(questions),
            "passed": total_passed,
            "failed": total_failed,
            "hallucination_flags": all_hallucination_flags,
            "pass_rate": total_passed / len(questions) if questions else 0,
        }

        return validated, summary

    async def _validate_single(
        self,
        question: GeneratedQuestion,
        strict_grounding: bool,
    ) -> tuple[GeneratedQuestion, dict]:
        """Validate a single question against its source material."""

        # Build the validation request
        options_text = ""
        if question.options:
            options_text = "\n".join(
                f"  {opt['label']}: {opt['text']}" for opt in question.options
            )

        user_message = f"""Validate this exam question:

Question Type: {question.question_type.upper()}
Bloom's Level: {question.bloom_level}
Target Difficulty: {question.difficulty_score:.2f}
Strict Grounding Mode: {strict_grounding}

QUESTION:
{question.content}

{"OPTIONS:" if options_text else ""}
{options_text}

CORRECT ANSWER: {question.correct_answer}

EXPLANATION: {question.explanation}

=== SOURCE CONTEXT (the ONLY allowed knowledge source) ===

{chr(10).join(question.source_texts[:3])}

=== END SOURCE ===

Validate this question thoroughly."""

        messages = [
            SystemMessage(content=VALIDATION_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        response = await self.llm.ainvoke(messages)
        result = self._parse_validation(response.content)

        # Update question validation status
        overall_quality = result.get("overall_quality", 0.0)
        question.is_validated = overall_quality >= self.QUALITY_THRESHOLD
        question.validation_notes = json.dumps({
            "grounding_score": result.get("grounding_score", 0),
            "accuracy_score": result.get("accuracy_score", 0),
            "difficulty_alignment": result.get("difficulty_alignment", 0),
            "overall_quality": overall_quality,
            "issues": result.get("issues", []),
            "suggestions": result.get("suggestions", []),
        })

        return question, result

    def _parse_validation(self, response_text: str) -> dict:
        """Parse LLM validation response."""
        text = response_text.strip()

        if not text:
            return {
                "is_valid": False,
                "grounding_score": 0.0,
                "accuracy_score": 0.0,
                "difficulty_alignment": 0.0,
                "hallucination_flags": ["Empty validation response"],
                "issues": ["LLM returned empty response"],
                "suggestions": [],
                "overall_quality": 0.0,
            }

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
        except json.JSONDecodeError:
            # If parsing fails, return a conservative result
            return {
                "is_valid": False,
                "grounding_score": 0.0,
                "accuracy_score": 0.0,
                "difficulty_alignment": 0.0,
                "hallucination_flags": ["Could not validate - response parsing failed"],
                "issues": ["Validation response was not valid JSON"],
                "suggestions": ["Re-run validation"],
                "overall_quality": 0.0,
            }
