"""
Question Generator Agent — Micro-Prompting

Responsibilities:
- Generate exam questions from blueprint slots + retrieved context (legacy)
- NEW: Generate questions from individual chunks (micro-prompting)
  Each LLM call receives only ONE chunk (~500-1500 chars) and produces 1-2 questions
  This keeps input+output tokens minimal, avoiding token overflow
- Support MCQ and Essay question types
- Ground all content in retrieved textbook material
- Produce structured JSON output per question
- Respect difficulty scores and Bloom's taxonomy levels
"""
import json
import re
import logging
import asyncio
import time

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

from config import settings
from agents.state import GeneratedQuestion, QuestionSlot, RetrievedContext, ChunkAssignment


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# System prompts — legacy (per-slot generation)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Micro-prompting system prompt — Bloom's Taxonomy integrated
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MICRO_PROMPT_SYSTEM = """Đóng vai trò là một chuyên gia ra đề thi. Bạn sẽ nhận được MỘT đoạn văn bản ngắn từ sách giáo khoa và yêu cầu sinh câu hỏi.

QUY TẮC TUYỆT ĐỐI:
1. Chỉ dựa DUY NHẤT vào đoạn văn bản được cung cấp
2. KHÔNG thêm thông tin ngoài đoạn văn bản
3. Mỗi câu hỏi phải có đáp án đúng và giải thích

CÁC MỨC ĐỘ BLOOM:
- Dễ (Easy) = Nhớ (Remember) & Hiểu (Understand): Hỏi về định nghĩa, khái niệm, liệt kê, giải thích ý nghĩa
- Trung bình (Medium) = Vận dụng (Apply) & Phân tích (Analyze): Hỏi cách giải quyết vấn đề, so sánh, phân loại, tìm mối quan hệ
- Khó (Hard) = Đánh giá (Evaluate) & Sáng tạo (Create): Nhận định ưu/nhược điểm, thiết kế giải pháp mới, phản biện

ĐỊNH DẠNG TRẢ VỀ — JSON array:
[
  {
    "question_type": "mcq" hoặc "essay",
    "difficulty": "easy" / "medium" / "hard",
    "bloom_level": "remember" / "understand" / "apply" / "analyze" / "evaluate" / "create",
    "content": "Nội dung câu hỏi",
    "options": [{"label": "A", "text": "..."}, {"label": "B", "text": "..."}, {"label": "C", "text": "..."}, {"label": "D", "text": "..."}],
    "correct_answer": "A (cho MCQ) hoặc câu trả lời mẫu (cho essay)",
    "explanation": "Giải thích ngắn gọn"
  }
]

Lưu ý: Nếu question_type là "essay" thì KHÔNG cần trường "options".
Chỉ trả về JSON, không thêm text nào khác."""


class QuestionGeneratorAgent:
    """Generates exam questions grounded in retrieved textbook content."""

    def __init__(self, llm):
        self.llm = llm

    # ─── Micro-prompting: generate from a single chunk ──────────────

    async def generate_from_chunk(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """
        Generate questions from a single chunk using micro-prompting.

        Each LLM call receives only ONE chunk of text and generates 1-2 questions.
        Includes retry with exponential backoff for rate limit errors (429).
        """
        assignments = chunk_assignment.assignments
        if not assignments:
            return []

        # Truncate chunk text to keep token usage low
        max_chars = settings.MAX_CHUNK_CHARS
        chunk_text = chunk_assignment.chunk_text
        if len(chunk_text) > max_chars:
            chunk_text = chunk_text[:max_chars] + "..."
            logger.debug(
                f"Chunk {chunk_assignment.chunk_id} truncated: "
                f"{len(chunk_assignment.chunk_text)} -> {max_chars} chars"
            )

        # Build the micro-prompt
        task_descriptions = []
        for a in assignments:
            diff = a["difficulty"]
            q_type = a["question_type"]

            if diff == "easy":
                bloom_desc = "kiểm tra mức độ ghi nhớ/hiểu: định nghĩa, khái niệm, liệt kê"
            elif diff == "medium":
                bloom_desc = "kiểm tra mức độ vận dụng/phân tích: giải quyết vấn đề, so sánh, phân loại"
            else:
                bloom_desc = "kiểm tra mức độ đánh giá/sáng tạo: nhận định ưu/nhược, thiết kế giải pháp"

            type_desc = "trắc nghiệm (MCQ, 4 lựa chọn A-D)" if q_type == "mcq" else "tự luận (essay)"
            task_descriptions.append(
                f"- 1 câu hỏi {type_desc}, mức độ {diff.upper()} ({bloom_desc})"
            )

        task_list = "\n".join(task_descriptions)

        user_message = f"""Dựa duy nhất vào đoạn văn bản dưới đây, hãy sinh ra chính xác {len(assignments)} câu hỏi:

{task_list}

=== ĐOẠN VĂN BẢN ===

{chunk_text}

=== HẾT VĂN BẢN ===

Trả về JSON array chứa đúng {len(assignments)} câu hỏi."""

        # Add strict grounding if enabled
        extra = ""
        if constraints.get("strict_grounding", True):
            extra = (
                "\n\nLƯU Ý QUAN TRỌNG: Bạn đang ở chế độ STRICT GROUNDING. "
                "Mọi thông tin trong câu hỏi PHẢI có trong đoạn văn bản trên. "
                "KHÔNG sử dụng kiến thức bên ngoài."
            )

        messages = [
            SystemMessage(content=MICRO_PROMPT_SYSTEM + extra),
            HumanMessage(content=user_message),
        ]

        # Retry with exponential backoff on rate limit errors
        questions_data = await self._invoke_with_retry(messages, chunk_assignment.chunk_id)

        # Convert to GeneratedQuestion objects
        generated = []
        for i, q_data in enumerate(questions_data):
            if i >= len(assignments):
                break

            a = assignments[i]
            options = q_data.get("options") if q_data.get("question_type", a["question_type"]) == "mcq" else None

            generated.append(GeneratedQuestion(
                slot_number=a.get("slot_number", 0),
                question_type=q_data.get("question_type", a["question_type"]),
                bloom_level=q_data.get("bloom_level", a["bloom_level"]),
                difficulty_score=self._difficulty_to_score(
                    q_data.get("difficulty", a["difficulty"])
                ),
                content=q_data.get("content", ""),
                options=options,
                correct_answer=q_data.get("correct_answer", ""),
                explanation=q_data.get("explanation", ""),
                source_chunks=[chunk_assignment.chunk_id],
                source_texts=[chunk_assignment.chunk_text[:500]],
            ))

        logger.debug(
            f"Chunk {chunk_assignment.chunk_id}: generated {len(generated)}/{len(assignments)} questions"
        )

        return generated

    async def _invoke_with_retry(
        self,
        messages: list,
        chunk_id: str,
        max_retries: int = 4,
    ) -> list[dict]:
        """Invoke LLM with exponential backoff on rate limit (429) errors."""
        for attempt in range(max_retries):
            try:
                response = await self.llm.ainvoke(messages)
                return self._parse_array_response(response.content)
            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "rate" in error_str.lower()

                if is_rate_limit and attempt < max_retries - 1:
                    # Exponential backoff: 8s, 16s, 32s, 64s
                    wait = 8 * (2 ** attempt)
                    logger.warning(
                        f"Rate limit hit for chunk {chunk_id}, "
                        f"retry {attempt + 1}/{max_retries} in {wait}s"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"Micro-prompting failed for chunk {chunk_id} "
                        f"(attempt {attempt + 1}): {e}"
                    )
                    return []
        return []

    async def generate_from_chunks_parallel(
        self,
        chunk_assignments: list[ChunkAssignment],
        constraints: dict,
        max_concurrency: int = 1,
    ) -> list[GeneratedQuestion]:
        """
        Generate questions from chunks sequentially with rate-limit delays.

        Processes one chunk at a time with a configurable delay between calls
        to stay within API rate limits (e.g., Groq free tier: 12K TPM).
        """
        delay = settings.LLM_REQUEST_DELAY
        all_questions = []

        logger.info(
            f"Starting sequential generation: {len(chunk_assignments)} chunks, "
            f"delay={delay}s between calls"
        )

        for idx, ca in enumerate(chunk_assignments):
            logger.info(
                f"Generating chunk {idx + 1}/{len(chunk_assignments)} "
                f"(chunk_id={ca.chunk_id[:16]}..., "
                f"tasks={len(ca.assignments)})"
            )

            try:
                questions = await self.generate_from_chunk(ca, constraints)
                all_questions.extend(questions)
            except Exception as e:
                logger.error(f"Chunk generation error: {e}")

            # Wait between requests to respect rate limits
            if idx < len(chunk_assignments) - 1:
                logger.debug(f"Rate-limit delay: waiting {delay}s...")
                await asyncio.sleep(delay)

        logger.info(
            f"Sequential generation complete: {len(all_questions)} questions "
            f"from {len(chunk_assignments)} chunks"
        )

        return all_questions

    # ─── Legacy: generate from blueprint slot + context ────────────

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

    # ─── Response parsing ──────────────────────────────────────────

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

    def _parse_array_response(self, response_text: str) -> list[dict]:
        """Parse LLM JSON array response (for micro-prompting)."""
        text = response_text.strip()
        logger.debug(f"MicroPrompt LLM raw (first 300): {text[:300]}")

        if not text:
            return []

        # Extract from ```json ... ``` block (array)
        code_block = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if code_block:
            text = code_block.group(1)
        elif not text.startswith("["):
            # Try to find array
            bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
            if bracket_match:
                text = bracket_match.group(0)
            else:
                # Maybe it's a single object, wrap in array
                brace_match = re.search(r"\{.*\}", text, re.DOTALL)
                if brace_match:
                    text = f"[{brace_match.group(0)}]"

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return [result]
            return result if isinstance(result, list) else []
        except json.JSONDecodeError as e:
            logger.warning(f"MicroPrompt JSON parse failed: {e}. Raw: {text[:200]}")
            return []

    def _difficulty_to_score(self, difficulty: str) -> float:
        """Convert difficulty label to score."""
        return {
            "easy": 0.2,
            "medium": 0.5,
            "hard": 0.85,
        }.get(difficulty, 0.5)

    # ─── Legacy: regenerate single ─────────────────────────────────

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
