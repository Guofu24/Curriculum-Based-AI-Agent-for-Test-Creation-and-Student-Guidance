"""Builder Agent - generates actual questions from blueprint slots."""

import logging
import time
import json
import asyncio
import re
from typing import Any


# ─────────────────────────────────────────────────────────────
# LaTeX escape sanitizer
# ─────────────────────────────────────────────────────────────
# LLM sometimes outputs LaTeX commands with a bare single backslash inside
# JSON string values (e.g. "\circ").  json.loads() interprets a leading
# backslash as a JSON escape sequence and fails because \c is not a valid
# JSON escape (\n, \t, \", \\, \uXXXX are valid).  This function finds
# bare LaTeX commands and doubles the backslash so json.loads sees a valid
# escaped backslash.  JSON escapes (\n, \\, etc.) are left untouched.
_LATEX_CMDS = sorted([
    r"\alpha", r"\beta", r"\gamma", r"\delta", r"\epsilon", r"\zeta",
    r"\eta", r"\theta", r"\iota", r"\kappa", r"\lambda", r"\mu",
    r"\nu", r"\xi", r"\pi", r"\rho", r"\sigma", r"\tau", r"\upsilon",
    r"\phi", r"\chi", r"\psi", r"\omega",
    r"\Gamma", r"\Delta", r"\Theta", r"\Lambda", r"\Xi", r"\Pi",
    r"\Sigma", r"\Upsilon", r"\Phi", r"\Psi", r"\Omega",
    r"\rightarrow", r"\leftarrow", r"\Rightarrow", r"\Leftarrow",
    r"\leftrightarrow", r"\Leftrightarrow", r"\mapsto", r"\to", r"\gets",
    r"\leq", r"\geq", r"\neq", r"\approx", r"\equiv", r"\sim",
    r"\ll", r"\gg", r"\perp", r"\parallel", r"\propto",
    r"\pm", r"\times", r"\div", r"\cdot", r"\star", r"\circ", r"\bullet",
    r"\oplus", r"\otimes", r"\ominus", r"\oslash",
    r"\frac", r"\sqrt", r"\root", r"\infty", r"\partial", r"\nabla",
    r"\sin", r"\cos", r"\tan", r"\cot", r"\sec", r"\csc",
    r"\log", r"\ln", r"\exp", r"\lim", r"\sum", r"\prod",
    r"\int", r"\oint", r"\iint", r"\iiiint",
    r"\text", r"\mathrm", r"\mathbf", r"\mathit", r"\mathsf", r"\mathtt",
    r"\vec", r"\hat", r"\dot", r"\ddot", r"\bar", r"\tilde", r"\breve",
    r"\underline", r"\overline", r"\overbrace", r"\underbrace",
    r"\quad", r"\qquad", r"\space",
    r"\degree", r"\ang", r"\pu", r"\ldots", r"\cdots",
    r"\vdots", r"\ddots", r"\forall", r"\exists",
    r"\in", r"\notin", r"\subset", r"\supset", r"\cup", r"\cap", r"\emptyset",
    r"\mathbb", r"\mathcal", r"\mathfrak",
    r"\_", r"\^",
], key=len, reverse=True)

_LATEX_SANITIZE_RE = re.compile(
    r"(?<!\\)(" + "|".join(re.escape(c) for c in _LATEX_CMDS) + r")"
)


def _sanitize_latex_escapes(json_str: str) -> str:
    """Replace bare LaTeX \\cmd with \\\\cmd so json.loads sees a valid escaped backslash.

    Only matches commands NOT preceded by another backslash.
    Valid JSON escapes (\\n, \\\\, etc.) are untouched.
    """
    return _LATEX_SANITIZE_RE.sub(lambda m: "\\" + m.group(0), json_str)


def _extract_json_brackets(text: str) -> str | None:
    """Extract the outermost JSON object or array from text using bracket counting.

    Handles cases where the LLM embeds the JSON inside prose (e.g. markdown fences,
    explanatory text) by scanning for the first '{' or '[' and counting brackets
    until a matching close is found.
    """
    start = None
    for i, ch in enumerate(text):
        if ch in ("{", "["):
            start = i
            break
    if start is None:
        return None

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    i = start
    escaped = False

    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\":
            escaped = True
            i += 1
            continue
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        elif ch == opener:
            depth += 1
        i += 1

    return None

from app.agents.base import AgentBaseOutput, AgentStatus, AgentMetrics, TokenUsage, BuilderOutput
from app.agents.llm import get_llm_client
from app.agents.guardrails import GuardrailsPipeline, ScopeGuard
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.dedup_checker import DedupCheckerSkill
from app.agents.skills.difficulty_estimator import DifficultyEstimatorSkill
from app.agents.skills.latex_renderer import LatexRendererSkill
from app.observability.tracer import get_tracer
from app.utils.search import search_similar_problems
from app.core.config import get_settings

settings = get_settings()
tracer = get_tracer()
logger = logging.getLogger("app.agents.builder")


class BuilderAgent:
    """
    Agent 3: Builder Agent

    Role: Generate actual questions from blueprint slots.
    Produces MCQ and Essay questions with full details.

    Flow:
    1. Generate in chunks: 5-10 questions per LLM call
    2. Each question: bloom_classifier → dedup_checker → content_filter
    3. van_dung_cao: web_search tool → adapt into scope
    4. Formula: text + LaTeX parallel output
    5. Append topics_used to Redis

    Rules:
    - MCQ: 4 options, 1 correct, 3 distractors with logic
    - Essay: must have grading rubric
    """

    BUILDER_SYSTEM_PROMPT = """Bạn là chuyên gia sinh câu hỏi kiểm tra chất lượng cao.

Nhiệm vụ:
1. Sinh câu hỏi MCQ và Essay từ blueprint slots
2. Đảm bảo câu hỏi đúng mức Bloom đã khai báo
3. MCQ: 4 lựa chọn, 1 đáp án đúng, 3 mồi nhử có logic (không lộ liễu)
4. Essay: có rubric chấm điểm rõ ràng
5. Công thức: output dạng text + LaTeX song song
6. Không trùng lặp chủ đề với câu đã sinh
7. Chỉ dùng kiến thức trong phạm vi cho phép

MCQ Format:
{
  "question_id": "MCQ_001",
  "type": "mcq",
  "stem": "Câu hỏi...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_answer": "B",
  "explanation": "Giải thích ngắn gọn...",
  "bloom_level": "thong_hieu",
  "chapter": "Chương 1",
  "section": "1.2 Định luật Newton",
  "latex_content": "F = ma"
}

Essay Format:
{
  "question_id": "ESSAY_001",
  "type": "essay",
  "stem": "Câu hỏi tự luận...",
  "rubric": [
    {"score": 4, "description": "Hoàn toàn đúng..."},
    {"score": 3, "description": "Đúng nhưng thiếu..."},
    {"score": 2, "description": "Sai sót..."},
    {"score": 1, "description": "Sai nhiều..."}
  ],
  "bloom_level": "van_dung_cao",
  "chapter": "Chương 2",
  "estimated_solve_time_minutes": 10
}

Trả về JSON:
{
  "questions": [q1, q2, ...]
}"""

    # Chunk size: questions per LLM call (1 = generate one slot at a time for reliability)
    CHUNK_SIZE = 1

    def __init__(self, redis_client=None):
        self.llm = get_llm_client()
        self.guardrails = GuardrailsPipeline()
        self.bloom_skill = BloomClassifierSkill()
        self.dedup_skill = DedupCheckerSkill()
        self.difficulty_skill = DifficultyEstimatorSkill()
        self.latex_skill = LatexRendererSkill()
        self.redis = redis_client

    @tracer.agent_span("builder_agent")
    async def build(
        self,
        blueprint: list[dict],
        retrieved_context: list[dict],
        topics_used: list[str] | None = None,
        allowed_concepts: list[str] | None = None,
        scope_chapters: list[str] | None = None,
        trace_id: str = "",
    ) -> BuilderOutput:
        """Build questions from blueprint."""
        start_time = time.time()
        trace_id = trace_id or str(time.time())
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []
        topics_used = topics_used or []
        all_questions: list[dict] = []
        chunks_referenced: list[str] = []
        logger.info(f"Builder received {len(blueprint)} slots")
        logger.info(f"Builder received {len(retrieved_context)} chunks")

        try:
            # Build context for generation
            context_for_llm = self._build_context_for_llm(retrieved_context)
            reduced_context_for_llm = self._build_context_for_llm(retrieved_context[:1])

            # Get scope restriction prompt
            scope_guard = ScopeGuard(
                allowed_concepts=allowed_concepts or [],
                scope_chapters=scope_chapters or [],
            )
            scope_restriction = (
                scope_guard.get_allowed_concepts_prompt()
                + "\n"
                + scope_guard.get_scope_restriction_prompt()
            )

            # Process blueprint in chunks
            blueprint_chunks = [
                blueprint[i:i + self.CHUNK_SIZE]
                for i in range(0, len(blueprint), self.CHUNK_SIZE)
            ]

            flush_mode = False

            for i, chunk in enumerate(blueprint_chunks):
                slot_start_index = i * self.CHUNK_SIZE
                # Check token budget
                budget_status = self.guardrails.check_budget(8000)
                if budget_status == "stop":
                    warnings.append("Token budget exhausted. Stopping generation.")
                    break
                if budget_status == "flush_needed":
                    warnings.append(
                        f"Token budget flush needed at chunk {i}, continuing with reduced context"
                    )
                    flush_mode = True

                # Generate questions for this chunk (one slot at a time)
                questions, chunk_warnings = await self._generate_chunk(
                    chunk=chunk,
                    context=reduced_context_for_llm if flush_mode else context_for_llm,
                    scope_restriction=scope_restriction,
                    topics_used=topics_used,
                    slot_start_index=slot_start_index,
                    total_slots=len(blueprint),
                )

                warnings.extend(chunk_warnings)

                # Validate each question
                validated = self.guardrails.validate_batch(questions)

                for q in validated:
                    if not q.get("filter_passed", True):
                        warnings.append(
                            f"Question {q.get('question_id')} failed filter: {q.get('filter_error')}"
                        )
                        continue

                    # Map evidence_chunks sang source_evidence nếu chưa có
                    if not q.get("source_evidence") and q.get("evidence_chunks"):
                        q["source_evidence"] = [
                            {
                                "chunk_id": chunk.get("chunk_id", ""),
                                "content": chunk.get("text", chunk.get("content", "")),
                                "page_number": chunk.get("page_number"),
                                "section": chunk.get("section_id", ""),
                                "relevance_score": chunk.get("score", 1.0),
                            }
                            for chunk in q.get("evidence_chunks", [])
                            if isinstance(chunk, dict)
                        ]

                    all_questions.append(q)

                    # Track topics
                    if q.get("topic_hint"):
                        topics_used.append(q["topic_hint"])

                    # Track referenced chunks
                    if q.get("evidence_chunks"):
                        chunks_referenced.extend(q["evidence_chunks"])

                # Record token usage
                metrics.completion_tokens += len(questions) * 50  # Estimate

            # Build output
            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = metrics.prompt_tokens + metrics.completion_tokens
            status = AgentStatus.SUCCESS
            if blueprint and not all_questions:
                warnings.append("Builder produced 0 questions from a non-empty blueprint.")
                status = AgentStatus.PARTIAL

            logger.info(f"Builder finished: {len(all_questions)} questions")
            return BuilderOutput(
                status=status,
                agent_name="builder",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(
                    prompt_tokens=metrics.prompt_tokens,
                    completion_tokens=metrics.completion_tokens,
                    total_tokens=usage,
                ),
                warnings=warnings,
                trace_id=trace_id,
                questions=all_questions,
                topics_used=topics_used,
                chunks_referenced=chunks_referenced,
            )

        except Exception as e:
            warnings.append(f"Builder failed: {str(e)}")

            logger.info(f"Builder finished: {len(all_questions)} questions")
            return BuilderOutput(
                status=AgentStatus.PARTIAL,
                agent_name="builder",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                questions=all_questions,
                topics_used=topics_used,
                chunks_referenced=chunks_referenced,
            )

    async def _generate_chunk(
        self,
        chunk: list[dict],
        context: str,
        scope_restriction: str,
        topics_used: list[str],
        slot_start_index: int = 0,
        total_slots: int = 0,
    ) -> tuple[list[dict], list[str]]:
        """Generate questions for a single blueprint chunk (one slot at a time)."""
        warnings = []
        all_questions: list[dict] = []

        for offset, slot in enumerate(chunk):
            slot_number = slot_start_index + offset + 1
            question, q_warnings = await self._generate_single_slot(
                slot=slot,
                context=context[:8000],
                scope_restriction=scope_restriction,
                topics_used=topics_used,
                slot_number=slot_number,
            )
            warnings.extend(q_warnings)
            if question:
                all_questions.append(question)
                topics_used.append(question.get("topic_hint", ""))

        return all_questions, warnings

    async def _generate_single_slot(
        self,
        slot: dict,
        context: str,
        scope_restriction: str,
        topics_used: list[str],
        slot_number: int = 0,
    ) -> tuple[dict | None, list[str]]:
        """
        Generate a single question for one blueprint slot.
        Retries up to 2 times on JSON parse failure, then falls back to a demo question.
        """
        warnings: list[str] = []

        # G4: For van_dung_cao slots, fetch web search context
        search_context = ""
        if slot.get("bloom_level") == "van_dung_cao":
            topic = slot.get("topic_hint", "")
            if topic:
                try:
                    results = await search_similar_problems(
                        query=f"{topic} bài toán vận dụng cao vật lý",
                        subject="physics",
                        num_results=2,
                    )
                    if results:
                        search_context = "\n".join(
                            f"- {r['title']}: {r['snippet']}" for r in results
                        )
                except Exception:
                    pass

        q_id = slot.get("question_id", f"Q_{slot_number}")
        q_type = slot.get("type", "mcq")
        bloom = slot.get("bloom_level", "thong_hieu")
        chapter = slot.get("chapter", "")
        topic_hint = slot.get("topic_hint", "")
        difficulty = slot.get("estimated_difficulty", 0.5)

        # Prompt asks for exactly ONE question (JSON array with 1 item)
        user_prompt = f"""Sinh để trả lời đúng một câu hỏi cho blueprint slot sau:

```json
{json.dumps(slot, ensure_ascii=False, indent=2)}
```

## Kiến thức nền (chỉ dùng kiến thức từ đây, không bịa đặt):
{context}
{search_context and f"\n## Bối cảnh mở rộng:\n{search_context}" or ""}

## Ràng buộc:
{scope_restriction}

## Yêu cầu:
- Sinh đúng MỘT câu hỏi duy nhất theo blueprint slot trên
- Câu hỏi phải thuộc mức Bloom: {bloom}
- Chỉ dùng kiến thức trong phạm vi đã cho
- Trả lời đúng một JSON array chứa đúng một object câu hỏi, không thêm gì khác

Đây là JSON array MỘT câu hỏi:"""

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = await self.llm.chat(
                    messages=[
                        {"role": "system", "content": self.BUILDER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    role="builder",
                    max_tokens=4000,
                    temperature=0.7,
                )

                if not response or not response.strip():
                    warnings.append(f"Slot {slot_number}: LLM returned empty response (attempt {attempt + 1})")
                    continue

                # Parse response — strip markdown fence first
                clean = response.strip()
                if clean.startswith("`"):
                    lines = clean.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    clean = "\n".join(lines).strip()

                # Try to extract JSON using bracket matching (reliable for LLM output)
                json_str = _extract_json_brackets(clean)
                if not json_str:
                    warnings.append(f"Slot {slot_number}: No JSON found in response (attempt {attempt + 1})")
                    continue

                # Fix bare LaTeX backslash escapes (e.g. \circ -> \\circ) so json.loads can parse
                json_str = _sanitize_latex_escapes(json_str)

                try:
                    data = json.loads(json_str, strict=False)
                except json.JSONDecodeError as je:
                    warnings.append(f"Slot {slot_number}: JSON parse error after sanitize")
                    logger.warning(f"[DEBUG] Slot {slot_number} JSONDecodeError at char {je.pos}: {je.msg} | snippet: {json_str[max(0,je.pos-20):je.pos+40]!r}")
                    continue

                # Normalize: data can be {"questions": [...]} or [...]
                questions_raw: list = []
                if isinstance(data, list):
                    questions_raw = data
                elif isinstance(data, dict):
                    questions_raw = data.get("questions", [data])

                if not questions_raw:
                    warnings.append(f"Slot {slot_number}: No questions in parsed JSON (attempt {attempt + 1})")
                    continue

                q = questions_raw[0]
                # Normalize field names for consistency
                if "question_id" not in q:
                    q["question_id"] = q_id
                if "type" not in q:
                    q["type"] = q_type
                if "bloom_level" not in q:
                    q["bloom_level"] = bloom
                if "chapter" not in q:
                    q["chapter"] = chapter
                q["estimated_difficulty"] = difficulty

                # Build options for MCQ
                if q_type == "mcq" and "options" not in q:
                    q["options"] = {
                        "A": "Đáp án A",
                        "B": "Đáp án B",
                        "C": "Đáp án C",
                        "D": "Đáp án D",
                    }
                    q["correct_answer"] = "A"
                    q["explanation"] = "Đáp án đúng là A."

                # Build rubric for Essay
                if q_type == "essay" and "rubric" not in q:
                    q["rubric"] = [
                        {"score": 10, "description": "Hoàn toàn chính xác"},
                        {"score": 7, "description": "Đúng nhưng thiếu chi tiết"},
                        {"score": 4, "description": "Sai sót một phần"},
                        {"score": 0, "description": "Sai hoàn toàn"},
                    ]
                    q["estimated_solve_time_minutes"] = 15

                # Apply skill pipeline (non-blocking)
                await self._apply_skill_pipeline(q, topics_used)

                logger.info(f"Slot {slot_number} generated ok (attempt {attempt + 1})")
                return q, warnings

            except json.JSONDecodeError as e:
                warnings.append(f"Slot {slot_number}: JSON parse error (attempt {attempt + 1}): {e}")
                if attempt == max_retries:
                    break

            except Exception as e:
                warnings.append(f"Slot {slot_number}: LLM error (attempt {attempt + 1}): {e}")
                if attempt == max_retries:
                    break

        # ── All retries exhausted — emit a demo question so the pipeline doesn't stall ──
        logger.warning(f"Slot {slot_number}: All LLM retries failed — using demo question")
        warnings.append(f"Slot {slot_number}: LLM failed after {max_retries + 1} attempts, using demo question")

        demo_q = self._build_demo_question(slot, context)
        return demo_q, warnings

    async def _apply_skill_pipeline(self, q: dict, topics_used: list[str]) -> None:
        """Run skill pipeline on a question (non-blocking, errors are swallowed)."""
        try:
            bloom_result = await self.bloom_skill.run(
                question_stem=q.get("stem", ""),
                question_type=q.get("type", "mcq"),
            )
            q["bloom_classified"] = bloom_result.get("bloom_level")
        except Exception:
            pass

        try:
            diff_result = await self.difficulty_skill.run(
                question_stem=q.get("stem", ""),
                bloom_level=q.get("bloom_level", "thong_hieu"),
            )
            q["difficulty_score"] = diff_result.get("difficulty_score", 0.5)
        except Exception:
            pass

        try:
            dedup_result = await self.dedup_skill.run(
                new_question_topic=q.get("stem", ""),
                existing_topics=topics_used,
            )
            if dedup_result.get("is_duplicate"):
                q["dedup_warning"] = dedup_result.get("suggestion")
        except Exception:
            pass

        if q.get("latex_content"):
            try:
                latex_result = self.latex_skill.run(raw_formula=q["latex_content"])
                q["latex_rendered"] = latex_result
            except Exception:
                pass

    def _build_demo_question(self, slot: dict, context: str = "") -> dict:
        """Build a reasonable demo question from a blueprint slot when LLM fails.

        Extracts real content from the retrieved context to create a meaningful
        stem and options instead of placeholder text.
        Bug-020 fix: fall back to chapter name from slot when context is empty.
        """
        q_id = slot.get("question_id", "DEMO_Q")
        q_type = slot.get("type", "mcq")
        bloom = slot.get("bloom_level", "thong_hieu")
        chapter = slot.get("chapter", "Chương không xác định")
        content_type = slot.get("content_type", "text")
        topic_hint = slot.get("topic_hint", "")

        # Extract real content snippets from context for this chapter
        real_snippets = self._extract_snippets_for_chapter(context, chapter)
        snippet = real_snippets[0] if real_snippets else ""
        second_snippet = real_snippets[1] if len(real_snippets) > 1 else ""

        # Bug-020 fix: use chapter + topic_hint from slot as fallback content
        if not snippet:
            snippet = f"{topic_hint} ({chapter})" if topic_hint else chapter

        demo_q: dict[str, Any] = {
            "question_id": q_id,
            "type": q_type,
            "bloom_level": bloom,
            "chapter": chapter,
            "topic_hint": slot.get("topic_hint", ""),
            "content_type": content_type,
            "estimated_difficulty": slot.get("estimated_difficulty", 0.5),
            "is_demo_question": True,
            "warning": "Câu hỏi demo do LLM không phản hồi. Vui lòng tạo lại đề.",
        }

        if q_type == "mcq":
            # Build real MCQ from context content
            if snippet:
                # Extract a concept from the snippet for the stem
                concept = self._extract_concept(snippet, bloom)
                # Try to extract options from multiple snippets
                if len(real_snippets) >= 4:
                    # Great — we have enough real content for options
                    demo_q["stem"] = f" Theo nội dung đã học: {concept}"
                    demo_q["options"] = {
                        "A": real_snippets[0][:120] if len(real_snippets[0]) > 120 else real_snippets[0],
                        "B": real_snippets[1][:120] if len(real_snippets[1]) > 120 else real_snippets[1],
                        "C": real_snippets[2][:120] if len(real_snippets[2]) > 120 else real_snippets[2],
                        "D": real_snippets[3][:120] if len(real_snippets[3]) > 120 else real_snippets[3],
                    }
                    demo_q["explanation"] = f"Đáp án đúng dựa trên nội dung Chương: {chapter}."
                elif second_snippet:
                    # We have 2 snippets — use them for A and B, generate similar for C and D
                    demo_q["stem"] = f" Theo nội dung đã học: {concept}"
                    demo_q["options"] = {
                        "A": second_snippet[:120] if len(second_snippet) > 120 else second_snippet,
                        "B": snippet[:120] if len(snippet) > 120 else snippet,
                        "C": "Phát biểu khác với nội dung đã học.",
                        "D": "Không có phát biểu nào đúng.",
                    }
                    demo_q["explanation"] = f"Đáp án đúng dựa trên nội dung Chương: {chapter}."
                else:
                    # Only 1 snippet or none — use concept as stem, generic options
                    demo_q["stem"] = f" {concept}"
                    demo_q["options"] = {
                        "A": snippet[:120] if snippet else "Phát biểu A đúng theo nội dung.",
                        "B": "Phát biểu B khác với nội dung đã học.",
                        "C": "Phát biểu C không liên quan đến chủ đề.",
                        "D": "Phát biểu D sai hoàn toàn.",
                    }
                    demo_q["explanation"] = f"Đáp án đúng dựa trên nội dung Chương: {chapter}."
            else:
                # No context — use chapter name
                demo_q["stem"] = f" Theo nội dung Chương {chapter}:"
                demo_q["options"] = {
                    "A": f"Nội dung A liên quan đến {chapter}",
                    "B": f"Nội dung B liên quan đến {chapter}",
                    "C": f"Nội dung C liên quan đến {chapter}",
                    "D": f"Nội dung D liên quan đến {chapter}",
                }
                demo_q["explanation"] = f"Đáp án đúng dựa trên nội dung Chương: {chapter}."
            demo_q["correct_answer"] = "A"

        if q_type == "essay":
            if snippet:
                concept = self._extract_concept(snippet, bloom)
                demo_q["stem"] = f" {concept}"
            else:
                demo_q["stem"] = f"Bài toán liên quan đến {chapter}"
            demo_q["rubric"] = [
                {"score": 10, "description": "Hoàn toàn chính xác và đầy đủ"},
                {"score": 7, "description": "Đúng nhưng thiếu một số chi tiết"},
                {"score": 4, "description": "Sai sót một phần"},
                {"score": 0, "description": "Sai hoàn toàn"},
            ]
            demo_q["estimated_solve_time_minutes"] = 15

        return demo_q

    def _extract_snippets_for_chapter(self, context: str, chapter: str) -> list[str]:
        """Extract meaningful content snippets from retrieved context for a chapter."""
        if not context:
            return []
        lines = context.split("\n")
        snippets: list[str] = []
        for line in lines:
            stripped = line.strip()
            # Collect bullet points or non-header lines
            if stripped and not stripped.startswith("#") and not stripped.startswith("###"):
                # Skip very short lines
                if len(stripped) < 20:
                    continue
                # Clean up the snippet
                clean = stripped.lstrip("-*: ").strip()
                if len(clean) > 15:
                    snippets.append(clean)
                if len(snippets) >= 4:
                    break
        return snippets

    def _extract_concept(self, snippet: str, bloom: str) -> str:
        """Extract a meaningful concept/stem from a content snippet based on Bloom level."""
        # Try to find meaningful content — first 150 chars of snippet
        content = snippet[:150].strip()
        if not content:
            content = "nội dung đã học"

        bloom_prefixes = {
            "nhan_biet": "Hiện tượng / khái niệm nào liên quan đến:",
            "thong_hieu": "Chọn phát biểu đúng về:",
            "van_dung": "Áp dụng kiến thức: Tính toán hoặc phân tích:",
            "van_dung_cao": "Bài toán tổng hợp: Phân tích sâu và đánh giá:",
        }
        prefix = bloom_prefixes.get(bloom, "")
        return f"{prefix} {content}" if prefix else content

    def _build_context_for_llm(self, retrieved_context: list[dict]) -> str:
        """Build a context string for the LLM prompt."""
        parts = []

        # Group by chapter
        by_chapter: dict[str, list[str]] = {}
        for chunk in retrieved_context:
            chapter = chunk.get("chapter", "Unknown")
            if chapter not in by_chapter:
                by_chapter[chapter] = []
            content = chunk.get("content", "")
            latex = chunk.get("latex_repr")
            if latex:
                content = f"{content}\n[Formula: {latex}]"
            by_chapter[chapter].append(content)

        for chapter, contents in by_chapter.items():
            parts.append(f"### {chapter}")
            for c in contents[:5]:  # Max 5 excerpts per chapter
                parts.append(f"- {c[:500]}")
            parts.append("")

        return "\n".join(parts)
