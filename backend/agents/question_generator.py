"""
Question Generator Agent — Micro-Prompting

Responsibilities:
- Generate exam questions from blueprint slots + retrieved context (legacy)
- Generate questions from individual chunks (micro-prompting)
- Support MCQ and Essay question types
- Ground all content in retrieved textbook material
- Produce structured JSON output per question
- Respect difficulty scores and Bloom's taxonomy levels
"""

import asyncio
import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import ChunkAssignment, GeneratedQuestion, QuestionSlot, RetrievedContext
from config import settings
from agents.prompts.generate_prompt import QUESTION_GENERATOR_SUPER_PROMPT

logger = logging.getLogger(__name__)


VALID_BLOOM_LEVELS = {
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
}

VALID_DIFFICULTIES = {"easy", "medium", "hard"}

VALID_QUESTION_TYPES = {"mcq", "essay"}

BLOOM_GUIDANCE = {
    "remember": "kiểm tra nhớ lại định nghĩa, thuật ngữ, dữ kiện, công thức, quy tắc",
    "understand": "kiểm tra giải thích ý nghĩa, diễn đạt lại, tóm tắt, phân biệt trực tiếp",
    "apply": "kiểm tra áp dụng quy tắc/công thức/quy trình vào trường hợp mới cùng bản chất",
    "analyze": "kiểm tra so sánh, chỉ ra quan hệ, phát hiện lỗi, phân tích cấu trúc",
    "evaluate": "kiểm tra đánh giá, lựa chọn và biện minh bằng tiêu chí từ ngữ liệu",
    "create": "kiểm tra thiết kế, xây dựng, đề xuất phương án mới trong phạm vi ngữ liệu",
}

MICRO_PROMPT_USER_TEMPLATE = """Dựa DUY NHẤT vào ngữ liệu dưới đây, hãy sinh CHÍNH XÁC {num_questions} câu hỏi.

DANH SÁCH SLOT CẦN SINH:
{task_list}

=== NGỮ LIỆU NGUỒN ===
{chunk_text}
=== HẾT NGỮ LIỆU ===

RÀNG BUỘC:
- Mỗi slot_number phải xuất hiện đúng một lần trong output.
- Chỉ dùng thông tin có trong ngữ liệu.
- Nếu Bloom hoặc difficulty yêu cầu vượt quá khả năng thật sự của ngữ liệu, hãy tự động hạ về mức hợp lệ gần nhất và phản ánh trung thực trong output.
- Với apply: bắt buộc phải có thao tác áp dụng thật sự.
- Với apply hard: phải có nhiều bước hoặc phải chọn đúng phương pháp/quy tắc trước khi áp dụng.
- MCQ: đúng 4 lựa chọn A, B, C, D; đúng 1 đáp án đúng.
- Essay: correct_answer phải đủ làm đáp án mẫu chấm điểm.
- Trả về JSON array chứa đúng {num_questions} phần tử, không thêm gì khác.
"""

LEGACY_PROMPT_USER_TEMPLATE = """Hãy sinh 1 câu hỏi duy nhất từ ngữ liệu dưới đây.

THÔNG TIN SLOT:
- slot_number: {slot_number}
- question_type: {question_type}
- target_bloom: {bloom_level}
- target_difficulty_score: {difficulty_score:.2f}
- target_chapter: {target_chapter}
- target_topics: {target_topics}

=== NGỮ LIỆU NGUỒN ===
{context_text}
=== HẾT NGỮ LIỆU ===

RÀNG BUỘC:
- Chỉ dùng thông tin trong ngữ liệu.
- Nếu Bloom hoặc difficulty yêu cầu vượt quá khả năng thật sự của ngữ liệu, hãy tự động hạ về mức hợp lệ gần nhất và phản ánh trung thực trong output.
- Nếu là MCQ: đúng 4 lựa chọn A-D và đúng 1 đáp án đúng.
- Nếu là Essay: đáp án mẫu phải đủ chấm.

Trả về JSON array gồm đúng 1 phần tử.
"""


class QuestionGeneratorAgent:
    """Generates exam questions grounded in retrieved textbook content."""

    def __init__(self, llm):
        self.llm = llm

    # ──────────────────────────────────────────────────────────────
    # Public APIs
    # ──────────────────────────────────────────────────────────────

    async def generate_from_chunk(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """
        Generate questions from a single chunk using micro-prompting.

        Each LLM call receives only ONE chunk of text and generates 1..N questions
        according to the provided assignments for that chunk.
        """
        assignments = chunk_assignment.assignments
        if not assignments:
            return []

        max_chars = getattr(settings, "MAX_CHUNK_CHARS", 1500)
        chunk_text = self._truncate_text(chunk_assignment.chunk_text, max_chars)

        task_descriptions = [self._build_task_description(a) for a in assignments]
        task_list = "\n".join(task_descriptions)

        user_message = MICRO_PROMPT_USER_TEMPLATE.format(
            num_questions=len(assignments),
            task_list=task_list,
            chunk_text=chunk_text,
        )

        messages = [
            SystemMessage(content=self._build_system_prompt(constraints)),
            HumanMessage(content=user_message),
        ]

        cleaned_questions = await self._invoke_and_validate(
            messages=messages,
            request_id=f"chunk-{chunk_assignment.chunk_id}",
            assignments=assignments,
        )

        generated: list[GeneratedQuestion] = []
        for q_data in cleaned_questions:
            options = q_data.get("options") if q_data["question_type"] == "mcq" else None

            generated.append(
                GeneratedQuestion(
                    slot_number=q_data["slot_number"],
                    question_type=q_data["question_type"],
                    bloom_level=q_data["bloom_level"],
                    difficulty_score=q_data["difficulty_score"],
                    content=q_data["content"],
                    options=options,
                    correct_answer=q_data["correct_answer"],
                    explanation=q_data["explanation"],
                    source_chunks=[chunk_assignment.chunk_id],
                    source_texts=[chunk_assignment.chunk_text[:500]],
                )
            )

        logger.debug(
            "Chunk %s: generated %s/%s valid questions",
            chunk_assignment.chunk_id,
            len(generated),
            len(assignments),
        )
        return generated

    async def generate_from_chunks_parallel(
        self,
        chunk_assignments: list[ChunkAssignment],
        constraints: dict,
        max_concurrency: int = 1,
    ) -> list[GeneratedQuestion]:
        """
        Generate questions from multiple chunks with bounded concurrency.

        - max_concurrency=1 behaves sequentially.
        - Request starts are spaced by settings.LLM_REQUEST_DELAY seconds to reduce
          rate-limit pressure while still allowing bounded overlap when concurrency > 1.
        """
        if not chunk_assignments:
            return []

        delay = max(0.0, float(getattr(settings, "LLM_REQUEST_DELAY", 0)))
        semaphore = asyncio.Semaphore(max(1, max_concurrency))
        request_spacing_lock = asyncio.Lock()
        last_request_start = 0.0

        logger.info(
            "Starting chunk generation: chunks=%s, max_concurrency=%s, delay=%ss",
            len(chunk_assignments),
            max_concurrency,
            delay,
        )

        async def _worker(index: int, ca: ChunkAssignment) -> list[GeneratedQuestion]:
            nonlocal last_request_start

            async with semaphore:
                async with request_spacing_lock:
                    if delay > 0:
                        loop = asyncio.get_running_loop()
                        now = loop.time()
                        elapsed = now - last_request_start
                        if elapsed < delay:
                            await asyncio.sleep(delay - elapsed)
                        last_request_start = loop.time()

                logger.info(
                    "Generating chunk %s/%s (chunk_id=%s..., tasks=%s)",
                    index + 1,
                    len(chunk_assignments),
                    str(ca.chunk_id)[:16],
                    len(ca.assignments),
                )
                return await self.generate_from_chunk(ca, constraints)

        tasks = [_worker(idx, ca) for idx, ca in enumerate(chunk_assignments)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_questions: list[GeneratedQuestion] = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Chunk generation error at index %s: %s", idx, result)
                continue
            all_questions.extend(result)

        logger.info(
            "Chunk generation complete: %s questions from %s chunks",
            len(all_questions),
            len(chunk_assignments),
        )
        return all_questions

    async def generate_questions(
        self,
        slots: list[QuestionSlot],
        contexts: list[RetrievedContext],
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """Generate all questions for the exam based on blueprint slots and contexts."""
        if len(slots) != len(contexts):
            logger.warning(
                "generate_questions received mismatched lengths: slots=%s, contexts=%s. "
                "Only the zipped pairs will be processed.",
                len(slots),
                len(contexts),
            )

        questions: list[GeneratedQuestion] = []
        for slot, context in zip(slots, contexts):
            question = await self._generate_single(slot, context, constraints)
            questions.append(question)

        return questions

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
            target_chapter=0,
            target_topics=[],
        )

        if edit_prompt:
            constraints = {**constraints, "_edit_prompt": edit_prompt}

        return await self._generate_single(slot, context, constraints)

    # ──────────────────────────────────────────────────────────────
    # Legacy generation
    # ──────────────────────────────────────────────────────────────

    async def _generate_single(
        self,
        slot: QuestionSlot,
        context: RetrievedContext,
        constraints: dict,
    ) -> GeneratedQuestion:
        """Generate a single question for a blueprint slot."""
        assignment = self._assignment_from_slot(slot)

        user_message = LEGACY_PROMPT_USER_TEMPLATE.format(
            slot_number=slot.slot_number,
            question_type=slot.question_type,
            bloom_level=slot.bloom_level,
            difficulty_score=slot.difficulty_score,
            target_chapter=slot.target_chapter,
            target_topics=", ".join(slot.target_topics) if slot.target_topics else "General",
            context_text=context.combined_text,
        )

        edit_prompt = constraints.get("_edit_prompt", "").strip()
        if edit_prompt:
            user_message += f"\n\nYÊU CẦU CHỈNH SỬA THÊM:\n{edit_prompt}"

        messages = [
            SystemMessage(content=self._build_system_prompt(constraints)),
            HumanMessage(content=user_message),
        ]

        cleaned_questions = await self._invoke_and_validate(
            messages=messages,
            request_id=f"slot-{slot.slot_number}",
            assignments=[assignment],
        )

        if not cleaned_questions:
            logger.error("Failed to generate valid question for slot %s", slot.slot_number)
            return GeneratedQuestion(
                slot_number=slot.slot_number,
                question_type=slot.question_type,
                bloom_level=slot.bloom_level,
                difficulty_score=slot.difficulty_score,
                content="",
                options=None,
                correct_answer="",
                explanation="",
                source_chunks=[c["id"] for c in context.chunks],
                source_texts=[c["text"] for c in context.chunks],
            )

        q_data = cleaned_questions[0]
        options = q_data.get("options") if q_data["question_type"] == "mcq" else None

        return GeneratedQuestion(
            slot_number=slot.slot_number,
            question_type=q_data["question_type"],
            bloom_level=q_data["bloom_level"],
            difficulty_score=q_data["difficulty_score"],
            content=q_data["content"],
            options=options,
            correct_answer=q_data["correct_answer"],
            explanation=q_data["explanation"],
            source_chunks=[c["id"] for c in context.chunks],
            source_texts=[c["text"] for c in context.chunks],
        )

    # ──────────────────────────────────────────────────────────────
    # Prompt building helpers
    # ──────────────────────────────────────────────────────────────

    def _build_system_prompt(self, constraints: dict) -> str:
        """Build the system prompt from the shared super prompt."""
        system_prompt = QUESTION_GENERATOR_SUPER_PROMPT

        if constraints.get("strict_grounding", True):
            system_prompt += (
                "\n\nSTRICT GROUNDING MODE = ON. "
                "Không được dùng bất kỳ kiến thức nào ngoài ngữ liệu."
            )

        return system_prompt

    def _build_task_description(self, assignment: dict) -> str:
        """Build a stable slot description for micro-prompting."""
        slot_number = assignment.get("slot_number", 0)
        q_type = self._normalize_question_type(
            assignment.get("question_type", "essay")
        )
        bloom = self._normalize_bloom_level(
            assignment.get("bloom_level", "understand")
        )
        difficulty = self._assignment_difficulty_label(assignment)

        q_type_desc = (
            "trắc nghiệm MCQ (4 lựa chọn A-D)"
            if q_type == "mcq"
            else "tự luận"
        )
        bloom_desc = BLOOM_GUIDANCE.get(bloom, "")

        return (
            f'- slot_number={slot_number}; '
            f'question_type="{q_type}" ({q_type_desc}); '
            f'target_bloom="{bloom}" ({bloom_desc}); '
            f'target_difficulty="{difficulty}"'
        )

    def _assignment_from_slot(self, slot: QuestionSlot) -> dict:
        """Convert a QuestionSlot to a normalized assignment dict."""
        return {
            "slot_number": slot.slot_number,
            "question_type": self._normalize_question_type(slot.question_type),
            "bloom_level": self._normalize_bloom_level(slot.bloom_level),
            "difficulty": self._score_to_difficulty(slot.difficulty_score),
            "difficulty_score": float(slot.difficulty_score),
        }

    # ──────────────────────────────────────────────────────────────
    # LLM invocation + repair
    # ──────────────────────────────────────────────────────────────

    async def _invoke_and_validate(
        self,
        messages: list,
        request_id: str,
        assignments: list[dict],
    ) -> list[dict]:
        """
        Call the model, parse JSON, validate/normalize output, and optionally try one repair pass
        if output is incomplete or invalid.
        """
        raw_questions = await self._invoke_with_retry(messages, request_id)
        cleaned = self._normalize_and_validate_questions(raw_questions, assignments)

        if len(cleaned) == len(assignments):
            return cleaned

        expected_slots = {self._safe_int(a.get("slot_number")) for a in assignments}
        got_slots = {self._safe_int(q.get("slot_number")) for q in cleaned}
        missing_slots = sorted(s for s in expected_slots if s is not None and s not in got_slots)

        logger.warning(
            "Request %s returned incomplete/invalid output: valid=%s/%s, missing_slots=%s",
            request_id,
            len(cleaned),
            len(assignments),
            missing_slots,
        )

        repair_instruction = (
            "Kết quả trước chưa hợp lệ hoặc chưa đủ slot theo schema yêu cầu. "
            f"Hãy sinh lại TOÀN BỘ {len(assignments)} câu hỏi dưới dạng JSON array hợp lệ. "
            "Mỗi phần tử phải có đúng slot_number đã yêu cầu, đúng question_type đã yêu cầu, "
            "đúng schema, không thêm giải thích ngoài JSON."
        )

        repair_messages = messages + [HumanMessage(content=repair_instruction)]
        repaired_raw = await self._invoke_with_retry(
            repair_messages,
            f"{request_id}-repair",
            max_retries=2,
        )
        repaired = self._normalize_and_validate_questions(repaired_raw, assignments)

        if repaired:
            return repaired

        return cleaned

    async def _invoke_with_retry(
        self,
        messages: list,
        request_id: str,
        max_retries: int = 4,
    ) -> list[dict]:
        """
        Invoke the LLM with retry on rate-limit errors.
        Also performs one in-band JSON repair attempt if the model response is not parseable JSON.
        """
        last_raw = ""

        for attempt in range(max_retries):
            try:
                response = await self.llm.ainvoke(messages)
                content = str(getattr(response, "content", response))
                last_raw = content

                parsed = self._parse_array_response(content)
                if parsed:
                    return parsed

                logger.warning(
                    "Request %s returned non-parseable JSON on attempt %s; trying JSON repair",
                    request_id,
                    attempt + 1,
                )

                repair_messages = messages + [
                    HumanMessage(
                        content=(
                            "Kết quả trước chưa phải JSON array hợp lệ. "
                            "Hãy trả lại duy nhất JSON array hợp lệ theo đúng schema yêu cầu, "
                            "không thêm markdown, không thêm giải thích."
                        )
                    )
                ]
                repair_response = await self.llm.ainvoke(repair_messages)
                repair_content = str(getattr(repair_response, "content", repair_response))
                repaired = self._parse_array_response(repair_content)
                if repaired:
                    return repaired

                if attempt == max_retries - 1:
                    logger.error(
                        "Request %s failed to produce parseable JSON after %s attempts. Raw: %s",
                        request_id,
                        max_retries,
                        last_raw[:500],
                    )
                    return []

            except Exception as e:
                error_str = str(e)
                is_rate_limit = (
                    "429" in error_str
                    or "rate" in error_str.lower()
                    or "quota" in error_str.lower()
                )

                if is_rate_limit and attempt < max_retries - 1:
                    wait = 8 * (2 ** attempt)
                    logger.warning(
                        "Rate limit hit for %s, retry %s/%s in %ss",
                        request_id,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "LLM invocation failed for %s (attempt %s/%s): %s | Raw=%s",
                        request_id,
                        attempt + 1,
                        max_retries,
                        e,
                        last_raw[:300],
                    )
                    return []

        return []

    # ──────────────────────────────────────────────────────────────
    # Parsing
    # ──────────────────────────────────────────────────────────────

    def _extract_json_payload(self, response_text: str) -> str:
        """Extract raw JSON payload from a model response, removing markdown if present."""
        text = response_text.strip()
        if not text:
            return ""

        code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if code_block:
            return code_block.group(1).strip()

        return text

    def _parse_array_response(self, response_text: str) -> list[dict]:
        """Parse an LLM JSON array response, with tolerant recovery."""
        text = self._extract_json_payload(response_text)
        logger.debug("QuestionGen LLM raw (first 300): %s", text[:300])

        if not text:
            return []

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
            return []
        except json.JSONDecodeError:
            pass

        bracket_match = re.search(r"(\[[\s\S]*\])", text)
        if bracket_match:
            candidate = bracket_match.group(1)
            try:
                data = json.loads(candidate)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                pass

        brace_match = re.search(r"(\{[\s\S]*\})", text)
        if brace_match:
            candidate = brace_match.group(1)
            try:
                data = json.loads(candidate)
                return [data] if isinstance(data, dict) else []
            except json.JSONDecodeError:
                pass

        logger.warning("JSON parse failed. Raw: %s", text[:300])
        return []

    # ──────────────────────────────────────────────────────────────
    # Normalization + validation
    # ──────────────────────────────────────────────────────────────

    def _normalize_and_validate_questions(
        self,
        questions_data: list[dict],
        assignments: list[dict],
    ) -> list[dict]:
        """Validate model outputs against requested assignments and normalize them."""
        if not questions_data or not assignments:
            return []

        assignment_by_slot: dict[int, dict] = {}
        for a in assignments:
            slot_number = self._safe_int(a.get("slot_number"))
            if slot_number is not None:
                assignment_by_slot[slot_number] = a

        single_slot_number = None
        if len(assignment_by_slot) == 1:
            single_slot_number = next(iter(assignment_by_slot.keys()))

        validated: list[dict] = []
        seen_slots: set[int] = set()

        for q_data in questions_data:
            if not isinstance(q_data, dict):
                continue

            slot_number = self._safe_int(q_data.get("slot_number"))
            if slot_number is None and single_slot_number is not None:
                slot_number = single_slot_number
                q_data = {**q_data, "slot_number": slot_number}

            if slot_number is None:
                continue
            if slot_number not in assignment_by_slot:
                continue
            if slot_number in seen_slots:
                continue

            cleaned = self._validate_question_payload(
                q_data=q_data,
                assignment=assignment_by_slot[slot_number],
            )
            if cleaned:
                validated.append(cleaned)
                seen_slots.add(slot_number)

        return validated

    def _validate_question_payload(self, q_data: dict, assignment: dict) -> dict | None:
        """Validate and normalize a single question payload."""
        if not isinstance(q_data, dict):
            return None

        slot_number = self._safe_int(q_data.get("slot_number", assignment.get("slot_number")))
        if slot_number is None:
            return None

        requested_question_type = self._normalize_question_type(
            assignment.get("question_type", "essay")
        )
        model_question_type = self._normalize_question_type(
            q_data.get("question_type", requested_question_type)
        )

        # Question type should not drift from the requested slot.
        if model_question_type != requested_question_type:
            return None

        bloom_level = self._normalize_bloom_level(
            q_data.get("bloom_level", assignment.get("bloom_level", "understand"))
        )
        difficulty = self._normalize_difficulty_label(
            q_data.get("difficulty", self._assignment_difficulty_label(assignment))
        )

        difficulty_score = q_data.get("difficulty_score")
        if not isinstance(difficulty_score, (int, float)):
            difficulty_score = self._difficulty_to_score(difficulty)
        difficulty_score = self._clamp(float(difficulty_score), 0.0, 1.0)

        content = str(q_data.get("content", "")).strip()
        correct_answer = str(q_data.get("correct_answer", "")).strip()
        explanation = str(q_data.get("explanation", "")).strip()

        if not content or not correct_answer or not explanation:
            return None

        result = {
            "slot_number": slot_number,
            "question_type": requested_question_type,
            "difficulty": difficulty,
            "difficulty_score": difficulty_score,
            "bloom_level": bloom_level,
            "content": content,
            "correct_answer": correct_answer,
            "explanation": explanation,
        }

        if requested_question_type == "mcq":
            options = self._normalize_mcq_options(q_data.get("options"))
            if not options:
                return None

            correct_label = self._normalize_mcq_correct_answer(correct_answer, options)
            if not correct_label:
                return None

            result["options"] = options
            result["correct_answer"] = correct_label
        else:
            # Essay should not carry invalid MCQ options.
            result.pop("options", None)

        return result

    def _normalize_question_type(self, value: str) -> str:
        if not value:
            return "essay"

        value = str(value).strip().lower()
        mapping = {
            "mcq": "mcq",
            "multiple_choice": "mcq",
            "multiple-choice": "mcq",
            "multiple choice": "mcq",
            "essay": "essay",
            "short_answer": "essay",
            "short-answer": "essay",
            "short answer": "essay",
        }
        normalized = mapping.get(value, "essay")
        return normalized if normalized in VALID_QUESTION_TYPES else "essay"

    def _normalize_bloom_level(self, value: str) -> str:
        if not value:
            return "understand"

        value = str(value).strip().lower()
        mapping = {
            "remember": "remember",
            "knowledge": "remember",
            "understand": "understand",
            "comprehend": "understand",
            "comprehension": "understand",
            "apply": "apply",
            "application": "apply",
            "analyze": "analyze",
            "analysis": "analyze",
            "evaluate": "evaluate",
            "evaluation": "evaluate",
            "create": "create",
            "creation": "create",
        }
        normalized = mapping.get(value, "understand")
        return normalized if normalized in VALID_BLOOM_LEVELS else "understand"

    def _normalize_difficulty_label(self, value: str) -> str:
        if not value:
            return "medium"

        value = str(value).strip().lower()
        mapping = {
            "easy": "easy",
            "medium": "medium",
            "hard": "hard",
            "dễ": "easy",
            "trung bình": "medium",
            "trung_bình": "medium",
            "khó": "hard",
        }
        normalized = mapping.get(value, "medium")
        return normalized if normalized in VALID_DIFFICULTIES else "medium"

    def _normalize_mcq_options(self, options) -> list[dict] | None:
        """Normalize MCQ options to exactly 4 entries with labels A-D."""
        if not isinstance(options, list):
            return None

        expected_labels = ["A", "B", "C", "D"]
        normalized: list[dict] = []

        for idx, raw_opt in enumerate(options[:4]):
            if isinstance(raw_opt, dict):
                text = str(raw_opt.get("text", "")).strip()
            else:
                text = str(raw_opt).strip()

            if not text:
                return None

            normalized.append(
                {
                    "label": expected_labels[idx],
                    "text": text,
                }
            )

        if len(normalized) != 4:
            return None

        return normalized

    def _normalize_mcq_correct_answer(self, correct_answer: str, options: list[dict]) -> str:
        """Normalize MCQ answer to label A/B/C/D."""
        if not correct_answer:
            return ""

        text = str(correct_answer).strip()

        # Match leading label like "A", "A.", "A)", "A - ..."
        match = re.match(r"^\s*([A-Da-d])(?:[\.\)\:\-\s]|$)", text)
        if match:
            return match.group(1).upper()

        upper = text.upper()
        if upper in {"A", "B", "C", "D"}:
            return upper

        # Fallback: if model returned the exact option text
        for opt in options:
            if text == opt["text"]:
                return opt["label"]

        return ""

    def _assignment_difficulty_label(self, assignment: dict) -> str:
        """Get normalized difficulty label from an assignment."""
        if "difficulty" in assignment and assignment["difficulty"] is not None:
            return self._normalize_difficulty_label(assignment["difficulty"])

        score = assignment.get("difficulty_score", 0.5)
        try:
            return self._score_to_difficulty(float(score))
        except (TypeError, ValueError):
            return "medium"

    # ──────────────────────────────────────────────────────────────
    # Utility helpers
    # ──────────────────────────────────────────────────────────────

    def _difficulty_to_score(self, difficulty: str) -> float:
        """Convert difficulty label to score."""
        difficulty = self._normalize_difficulty_label(difficulty)
        return {
            "easy": 0.2,
            "medium": 0.5,
            "hard": 0.85,
        }.get(difficulty, 0.5)

    def _score_to_difficulty(self, score: float) -> str:
        """Convert a numeric difficulty score to a label."""
        score = self._clamp(float(score), 0.0, 1.0)
        if score <= 0.30:
            return "easy"
        if score <= 0.60:
            return "medium"
        return "hard"

    def _truncate_text(self, text: str, max_chars: int) -> str:
        """Truncate text safely at word boundary when possible."""
        text = text or ""
        if len(text) <= max_chars:
            return text

        truncated = text[:max_chars]
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        return truncated + "..."

    def _safe_int(self, value) -> int | None:
        """Safely coerce a value to int."""
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clamp(self, value: float, low: float, high: float) -> float:
        """Clamp numeric value to [low, high]."""
        return max(low, min(high, value))