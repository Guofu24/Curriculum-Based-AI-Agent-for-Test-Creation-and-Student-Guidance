"""Builder Agent - generates actual questions from blueprint slots."""

import logging
import time
import json
import asyncio
from typing import Any

# Domain 9: Prompt versioning
BUILDER_PROMPT_VERSION = "v2.1"

# ─────────────────────────────────────────────────────────────
# LaTeX escape sanitizer
# ─────────────────────────────────────────────────────────────
# LLM output often contains LaTeX inside JSON string values, e.g.:
#   "stem": "Vật có $m = 5 \, \text{kg}$"
# JSON only allows these escape sequences: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
# Any other \X is illegal and causes json.loads to raise JSONDecodeError.
# The fix: inside every JSON string value, replace bare backslashes (not already
# doubled) with double-backslash.  This is done via a state-machine that tracks
# whether the current character is inside a JSON string.

# Unambiguously safe single-char JSON escape sequences (never LaTeX):
# NOTE: b/f/n/r/t are intentionally EXCLUDED — \b/\f/\n/\r/\t followed by an
# alphabetic char almost certainly means a LaTeX command (\beta, \frac,
# \nabla, \rho, \theta …), not a JSON control-character escape.
_SAFE_JSON_ESCAPES = frozenset('"\\/ u')
# The ambiguous single-char JSON escapes that overlap with LaTeX prefixes:
_AMBIGUOUS_JSON_ESCAPES = frozenset('bfnrt')


def _sanitize_latex_escapes(json_str: str) -> str:
    """Fix illegal JSON backslash escapes produced by LLMs writing LaTeX.

    Walks the raw JSON text character-by-character tracking whether we are
    inside a JSON string literal.  Any backslash inside a string that is
    NOT followed by a valid JSON escape character is doubled so that
    json.loads can parse it correctly.

    Special handling for ambiguous escapes (\\b, \\f, \\n, \\r, \\t):
    - If the character AFTER the escape letter is alphabetic (e.g. \\frac,
      \\beta, \\nabla, \\rho, \\theta), treat as LaTeX → double the backslash.
    - Otherwise treat as a real JSON control-character escape → keep as-is.
    """
    result: list[str] = []
    in_string = False
    i = 0
    n = len(json_str)

    while i < n:
        ch = json_str[i]

        if in_string:
            if ch == '\\':
                next_ch = json_str[i + 1] if i + 1 < n else ''

                if next_ch in _SAFE_JSON_ESCAPES:
                    # Unambiguously safe escape (\" \\\\ \/ \uXXXX) — keep as-is
                    result.append(ch)
                    result.append(next_ch)
                    i += 2

                elif next_ch in _AMBIGUOUS_JSON_ESCAPES:
                    # Could be JSON ctrl-char OR LaTeX prefix.
                    # Peek at the character after the escape letter.
                    after_next = json_str[i + 2] if i + 2 < n else ''
                    if after_next.isalpha():
                        # e.g. \frac, \beta, \nabla → LaTeX, double the backslash
                        result.append('\\\\')
                        i += 1  # leave next_ch to be re-processed
                    else:
                        # e.g. \n followed by space/digit/{ → real JSON escape
                        result.append(ch)
                        result.append(next_ch)
                        i += 2

                else:
                    # Bare LaTeX backslash (\alpha, \vec, \, \! …) — double it
                    result.append('\\\\')
                    i += 1  # do NOT skip next_ch

            elif ch == '"':
                in_string = False
                result.append(ch)
                i += 1
            else:
                result.append(ch)
                i += 1
        else:
            if ch == '"':
                in_string = True
            result.append(ch)
            i += 1

    return ''.join(result)


def _repair_json_string(json_str: str) -> str:
    """Attempt to repair malformed JSON from LLM output.

    Handles the most common failure: unescaped double-quotes inside string
    values.  Example:
        "explanation": "Đề bài giả thiết "quả cầu dừng lại" là ..."
    becomes:
        "explanation": "Đề bài giả thiết 'quả cầu dừng lại' là ..."

    Strategy: try json.loads; on failure, find the offending position and
    replace the inner quote with a single-quote, then retry.
    """
    # First try — maybe it already works
    try:
        json.loads(json_str, strict=False)
        return json_str
    except json.JSONDecodeError:
        pass

    # Heuristic repair: replace inner quotes with single quotes.
    # Walk through the string tracking JSON structure.
    chars = list(json_str)
    i = 0
    n = len(chars)
    in_string = False
    string_start = -1

    while i < n:
        ch = chars[i]

        if not in_string:
            if ch == '"':
                in_string = True
                string_start = i
            i += 1
            continue

        # Inside a string
        if ch == '\\':
            i += 2  # skip escaped char
            continue

        if ch == '"':
            # Is this the real end of the string, or an unescaped inner quote?
            # Look ahead: real string-end is followed by , } ] : or whitespace
            rest = json_str[i + 1:].lstrip()
            if rest and rest[0] in ',:}]':
                # This is the real closing quote
                in_string = False
                i += 1
                continue
            else:
                # This is an unescaped inner quote — replace with single quote
                chars[i] = "'"
                i += 1
                continue

        i += 1

    repaired = ''.join(chars)

    # Validate the repair worked
    try:
        json.loads(repaired, strict=False)
        return repaired
    except json.JSONDecodeError:
        # Repair didn't fully fix it — return original (caller will handle)
        return json_str


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
    1. Generate in chunks: 5 questions per LLM call (parallelized)
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

## QUY TẮC LATEX BẮT BUỘC:
- Mọi ký hiệu toán học / công thức PHẢI được bao bằng dấu dollar:
  - Inline (trong câu): $...$ — ví dụ: "Tính $\\frac{kx}{m}$ khi..."
  - Display (chiếm dòng riêng): $$...$$ — ví dụ: "$$a = \\frac{kx}{m} - g(\\sin\\alpha + \\mu_k \\cos\\alpha)$$"
- KHÔNG viết công thức LaTeX ra ngoài dấu dollar dưới bất kỳ hình thức nào
- Ví dụ ĐÚNG: "stem": "Vật có khối lượng $m$ trượt trên mặt phẳng nghiêng góc $\\alpha$..."
- Ví dụ SAI: "stem": "Vật có khối lượng m trượt trên mặt phẳng nghiêng góc α..."
- Trong JSON, backslash LaTeX phải được viết kép: \\frac, \\sin, \\alpha, \\mu_k

## QUY TẮC JSON NGHIÊM NGẶT (BẮT BUỘC):
- CHỈ trả về JSON thuần túy — KHÔNG thêm bất kỳ văn bản, giải thích, hay suy nghĩ nào trước/sau JSON
- KHÔNG dùng dấu nháy kép (") bên trong giá trị string — thay bằng dấu nháy đơn (') nếu cần
- Ví dụ SAI: "stem": "Theo 'nguyên lý "bảo toàn năng lượng"', tính..."
- Ví dụ ĐÚNG: "stem": "Theo nguyên lý bảo toàn năng lượng, tính..."
- Không viết nhận xét kiểu 'Để tuân thủ yêu cầu...' hay chain-of-thought trong JSON

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

Trả về JSON array (không có key bọc ngoài):
[câu_hỏi_1]"""

    # Bloom-level-specific question generation guides
    BLOOM_TEMPLATES = {
        "nhan_biet": """## Hướng dẫn cho câu hỏi Nhận biết (nhan_biet)
- Câu hỏi yêu cầu nhớ lại định nghĩa, sự kiện, hoặc quy trình cụ thể
- Câu hỏi bắt đầu bằng: "Định nghĩa là gì", "Nêu", "Liệt kê", "Cho biết", "Kể tên", "Trình bày"
- KHÔNG yêu cầu suy luận — chỉ cần nhớ lại kiến thức đã học
- Ví dụ stem: "Định luật 2 Newton được phát biểu là gì?"
- Options MCQ: đáp án đúng là định nghĩa/chính xác; 3 distractors là những phát biểu sai phổ biến hoặc gần đúng""",

        "thong_hieu": """## Hướng dẫn cho câu hỏi Thông hiểu (thong_hieu)
- Câu hỏi yêu cầu giải thích, so sánh, hoặc diễn giải
- KHÔNG phải copy-paste — phải hiểu bản chất mới trả lời được
- Câu hỏi bắt đầu bằng: "Giải thích", "So sánh", "Phân biệt", "Mô tả", "Tại sao"
- Áp dụng công thức đơn giản 1 bước nếu có tính toán
- Ví dụ stem: "Tại sao vật chuyển động tròn đều có gia tốc hướng tâm?"
- Options MCQ: đáp án đúng giải thích đúng; distractors có thể giải thích sai bản chất""",

        "van_dung": """## Hướng dẫn cho câu hỏi Vận dụng (van_dung)
- Câu hỏi yêu cầu tính toán 2-3 bước hoặc có điều kiện ràng buộc
- Phải kết hợp nhiều kiến thức/định luật
- Câu hỏi bắt đầu bằng: "Tính", "Giải bài toán", "Xác định", "Vận dụng"
- Ví dụ stem: "Một vật trượt trên mặt phẳng nghiêng 30°. Tính gia tốc biết hệ số ma sát μ=0.2."
- Options MCQ: đáp án đúng cần tính toán đúng; distractors là các bước tính sai phổ biến (quên ma sát, dùng sai công thức, tính nhầm đơn vị)""",

        "van_dung_cao": """## Hướng dẫn cho câu hỏi Vận dụng cao (van_dung_cao)
- Câu hỏi yêu cầu phân tích mối quan hệ, đánh giá, hoặc bài toán phức hợp
- Kết hợp nhiều công thức, nhiều chương, hoặc dữ liệu thực tế
- Câu hỏi bắt đầu bằng: "Phân tích", "Đánh giá", "So sánh và nhận xét", "Thiết kế"
- Ví dụ stem: "Hai vật A và B nối bằng sợi dây qua ròng rọc. Phân tích chuyển động và tính gia tốc của hệ."
- Options MCQ: đáp án đúng cần phân tích đúng toàn bộ hệ; distractors là các lỗi phân tích phổ biến (bỏ qua ma sát, nhầm chiều lực, bỏ qua ràng buộc hình học)""",
    }

    # Distractor quality guide
    DISTRACTOR_GUIDE = """## Hướng dẫn viết distractors (đáp án nhiễu) cho MCQ
3 đáp án sai (distractors) phải thỏa mãn ĐỒNG THỜI:
1. **Plausible**: người không học kỹ CÓ THỂ chọn — không phải đáp án vô lý
2. **Related**: liên quan đến topic, không phải topic hoàn toàn khác
3. **Không lộ liễu**: KHÔNG chứa từ khóa quá rõ ràng của đáp án đúng
4. **Không có pattern**: KHÔNG có "tất cả các đáp án trên", "không có đáp án nào đúng", "A và B đúng"

Ví dụ distractor tốt cho "Lực ma sát luôn ngược chiều chuyển động":
- Tốt: "Lực ma sát cùng chiều chuyển động, làm vật tăng tốc" (plausible, sai bản chất)
- Tốt: "Lực ma sát có phương vuông góc với mặt tiếp xúc" (related, nhầm phương)
- Xấu: "Lực ma sát phụ thuộc vào màu sắc của vật" (không related)
- Xấu: "Lực ma sát tỉ lệ thuận với tốc độ" (plausible nhưng pattern quá dễ nhận ra)"""

    # Concurrency limits
    MAX_CONCURRENT_LLM_CALLS = 5  # semaphore limit to avoid rate limits
    CHUNK_SIZE = 5  # questions per LLM call

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

                # Generate questions for this chunk IN PARALLEL
                questions, chunk_warnings = await self._generate_chunk(
                    chunk=chunk,
                    context=reduced_context_for_llm if flush_mode else context_for_llm,
                    retrieved_context=retrieved_context,
                    scope_restriction=scope_restriction,
                    topics_used=topics_used,
                    slot_start_index=slot_start_index,
                    total_slots=len(blueprint),
                )

                warnings.extend(chunk_warnings)

                # Separate demo questions (safe by construction) from real LLM output
                real_questions = [q for q in questions if not q.get("is_demo_question")]
                demo_questions = [q for q in questions if q.get("is_demo_question")]

                # Validate only real LLM-generated questions
                validated = self.guardrails.validate_batch(real_questions)

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

                # Demo questions skip guardrails — always included
                for q in demo_questions:
                    all_questions.append(q)
                    if q.get("topic_hint"):
                        topics_used.append(q["topic_hint"])

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
        retrieved_context: list[dict],
        scope_restriction: str,
        topics_used: list[str],
        slot_start_index: int = 0,
        total_slots: int = 0,
    ) -> tuple[list[dict], list[str]]:
        """Generate questions for a blueprint chunk IN PARALLEL using semaphore.

        CHUNK_SIZE questions are generated concurrently (max 5 concurrent LLM calls).
        Results are reordered by slot position to maintain stable output order
        for the progress bar.
        """
        warnings: list[str] = []
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_LLM_CALLS)

        # Build topic-keyed context map for per-question filtering
        topic_context_map = self._build_topic_context_map(retrieved_context)
        # Also build a normalized-key map for fuzzy lookup
        norm_context_map = {
            self._normalize_chapter_key(k): v
            for k, v in topic_context_map.items()
        }
        # Also build a map keyed by normalized chapter_id (ch1, ch2, etc.)
        # so blueprint slots with 'ch2' can find chunks stored with chapter='1. ĐỘNG HỌC VẬT RẮN'
        from app.rag.structure import normalize_chapter_id
        chid_context_map: dict[str, list[dict]] = {}
        for k, v in topic_context_map.items():
            # Extract just the chapter part (before ' > section')
            chapter_part = k.split(" > ")[0] if " > " in k else k
            ch_id = normalize_chapter_id(chapter_part)
            if ch_id not in chid_context_map:
                chid_context_map[ch_id] = []
            chid_context_map[ch_id].extend(v)

        async def _generate_one_with_semaphore(
            slot: dict,
            slot_number: int,
        ) -> tuple[int, dict | None, list[str]]:
            """Generate one question with semaphore limiting concurrency."""
            async with semaphore:
                # Filter context to just this slot's chapter/section
                slot_chapter = slot.get("chapter", "Unknown")
                slot_section = slot.get("section", "") or ""
                slot_chapter_id = slot.get("chapter_id", "")  # Canonical ID from heading_tree
                slot_section_id = slot.get("section_id", "")  # Canonical section ID

                topic_key = f"{slot_chapter} > {slot_section}" if slot_section else slot_chapter
                topic_chunks: list[dict] = []
                match_path = ""

                # ── Priority 1: Exact chapter_id + section_id match (most precise) ──
                if slot_chapter_id and slot_section_id:
                    key_ids = f"{slot_chapter_id} > {slot_section_id}"
                    topic_chunks = topic_context_map.get(key_ids, [])
                    if topic_chunks:
                        match_path = "chapter_id+section_id"

                # ── Priority 2: Exact chapter_id match ──
                if not topic_chunks and slot_chapter_id:
                    topic_chunks = topic_context_map.get(slot_chapter_id, [])
                    if topic_chunks:
                        match_path = "chapter_id"

                # ── Priority 3: Exact title match ──
                if not topic_chunks:
                    topic_chunks = topic_context_map.get(topic_key, [])
                    if topic_chunks:
                        match_path = "exact_title"

                # ── Priority 4: Normalized title match ──
                if not topic_chunks:
                    norm_key = self._normalize_chapter_key(slot_chapter)
                    topic_chunks = norm_context_map.get(norm_key, [])
                    if topic_chunks:
                        match_path = "normalized"

                # ── Priority 5: normalize_chapter_id fallback ──
                if not topic_chunks:
                    ch_id = normalize_chapter_id(slot_chapter)
                    topic_chunks = chid_context_map.get(ch_id, [])
                    if topic_chunks:
                        match_path = "normalize_chapter_id"

                # ── Priority 6: Number-based fuzzy fallback ──
                if not topic_chunks:
                    import re
                    num_match = re.search(r'\d+', slot_chapter)
                    if num_match:
                        chapter_num = num_match.group()
                        for k, v in norm_context_map.items():
                            if chapter_num in re.findall(r'\d+', k):
                                topic_chunks = v
                                match_path = "number_fallback"
                                break

                if not topic_chunks:
                    match_path = "FALLBACK_ALL"
                question_context_str = (
                    self._build_context_for_llm(topic_chunks)
                    if topic_chunks
                    else context[:8000]
                )
                logger.info(
                    "Slot %d chapter=%r → %d chunks (path: %s)",
                    slot_number,
                    slot_chapter,
                    len(topic_chunks),
                    match_path,
                )

                question, q_warnings = await self._generate_single_slot(
                    slot=slot,
                    context=context[:8000],
                    question_context=question_context_str,
                    scope_restriction=scope_restriction,
                    topics_used=topics_used,
                    slot_number=slot_number,
                )
                return slot_number, question, q_warnings

        # Launch all slots in the chunk concurrently
        tasks = [
            _generate_one_with_semaphore(slot, slot_start_index + offset + 1)
            for offset, slot in enumerate(chunk)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results in original order (for stable output)
        ordered: list[tuple[int, dict | None, list[str]]] = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                slot_idx = slot_start_index + idx
                slot = chunk[idx] if idx < len(chunk) else {}
                warnings.append(f"Slot {slot_idx + 1} raised exception: {result} — using demo fallback")
                logger.warning("Slot %d task exception (using demo): %s", slot_idx + 1, result)
                demo_q = self._build_demo_question(slot, context[:8000])
                ordered.append((slot_idx + 1, demo_q, [str(result)]))
                continue
            ordered.append(result)

        # Sort by slot_number to maintain order
        ordered.sort(key=lambda x: x[0])

        all_questions: list[dict] = []
        for slot_number, question, q_warnings in ordered:
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
        question_context: str = "",
    ) -> tuple[dict | None, list[str]]:
        """
        Generate a single question for one blueprint slot.
        Retries up to 2 times on JSON parse failure, then falls back to a demo question.
        """
        warnings: list[str] = []

        # Use filtered topic context if provided, otherwise fall back to full context
        effective_context = question_context if question_context else context[:8000]

        q_id = slot.get("question_id", f"Q_{slot_number}")
        q_type = slot.get("type", "mcq")
        bloom = slot.get("bloom_level", "thong_hieu")
        chapter = slot.get("chapter", "")
        topic_hint = slot.get("topic_hint", "")
        difficulty = slot.get("estimated_difficulty", 0.5)

        # Domain 4B: Inject Bloom-specific template guide (after bloom/q_type are defined)
        bloom_guide = self.BLOOM_TEMPLATES.get(bloom, "")
        distractor_guide = self.DISTRACTOR_GUIDE if q_type == "mcq" else ""

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

        # Prompt asks for exactly ONE question (JSON array with 1 item)
        user_prompt = f"""Sinh để trả lời đúng một câu hỏi cho blueprint slot sau:

```json
{json.dumps(slot, ensure_ascii=False, indent=2)}
```

## Kiến thức nền (chỉ dùng kiến thức từ đây, không bịa đặt):
{effective_context}
{search_context and f"\n## Bối cảnh mở rộng (web search):\n{search_context}" or ""}

## Ràng buộc:
{scope_restriction}

{bloom_guide}
{distractor_guide}

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
                except json.JSONDecodeError:
                    # Try repairing unescaped quotes inside string values
                    repaired = _repair_json_string(json_str)
                    try:
                        data = json.loads(repaired, strict=False)
                        logger.info(f"Slot {slot_number}: JSON repaired successfully (attempt {attempt + 1})")
                    except json.JSONDecodeError as je:
                        warnings.append(f"Slot {slot_number}: JSON parse error after sanitize+repair")
                        logger.warning(f"[DEBUG] Slot {slot_number} JSONDecodeError at char {je.pos}: {je.msg} | snippet: {repaired[max(0,je.pos-20):je.pos+40]!r}")
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

        demo_q = self._build_demo_question(slot, effective_context)
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
                {"score": 7, "description": "�úng nhưng thiếu một số chi tiết"},
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

    def _build_topic_context_map(self, retrieved_context: list[dict]) -> dict[str, list[dict]]:
        """Build a dict mapping topic/chapter to relevant chunks for per-question context filtering.

        Keys include:
        - chapter title: "I. CƠ HỌC"
        - chapter title + section: "I. CƠ HỌC > 1.1 Động học"
        - chapter_id: "ch1" (ALWAYS indexed, not just when different from title)
        - chapter_id + section_id: "ch1 > ch1_sec1"

        Having chapter_id as a first-class key means blueprint slots that carry
        `chapter_id` can do an O(1) lookup without any normalize_chapter_id call.
        """
        topic_map: dict[str, list[dict]] = {}
        for chunk in retrieved_context:
            chapter = chunk.get("chapter", "") or chunk.get("metadata", {}).get("chapter", "Unknown")
            chapter_id = chunk.get("chapter_id", "") or chunk.get("metadata", {}).get("chapter_id", "")
            section = chunk.get("section", "") or chunk.get("metadata", {}).get("section", "")
            section_id = chunk.get("section_id", "") or chunk.get("metadata", {}).get("section_id", "")

            # Index 1: chapter title (+ optional section)
            key_title = f"{chapter} > {section}" if section else chapter
            if key_title not in topic_map:
                topic_map[key_title] = []
            topic_map[key_title].append(chunk)

            # Index 2: chapter_id (ALWAYS — primary lookup key for blueprint slots)
            if chapter_id:
                if chapter_id not in topic_map:
                    topic_map[chapter_id] = []
                topic_map[chapter_id].append(chunk)

                # Index 3: chapter_id + section_id (granular match)
                if section_id:
                    key_ids = f"{chapter_id} > {section_id}"
                    if key_ids not in topic_map:
                        topic_map[key_ids] = []
                    topic_map[key_ids].append(chunk)

        return topic_map

    @staticmethod
    def _normalize_chapter_key(key: str) -> str:
        """Normalize a chapter key for fuzzy matching.

        Strips Vietnamese diacritics, lowercases, removes spaces and punctuation
        so 'Chuong 1', 'Chương 1', 'chuong_1', 'Chapter 1' all map to the same key.
        """
        import unicodedata
        import re
        # NFD decompose → strip combining chars (diacritics)
        nfd = unicodedata.normalize("NFD", key)
        stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
        # lowercase, keep only alphanumeric
        return re.sub(r'[^a-z0-9]+', '', stripped.lower())
