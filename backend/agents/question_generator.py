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
from dataclasses import dataclass, field

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Multi-chunk synthesis prompt (Phase 3)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MULTI_CHUNK_SYSTEM_PROMPT = """Đóng vai trò là một chuyên gia ra đề thi. Bạn sẽ nhận được NHIỀU đoạn văn bản từ sách giáo khoa và yêu cầu sinh câu hỏi ĐÒI HỎI TỔNG HỢP thông tin từ nhiều đoạn.

QUY TẮC TUYỆT ĐỐI:
1. Chỉ dựa DUY NHẤT vào các đoạn văn bản được cung cấp
2. KHÔNG thêm thông tin ngoài các đoạn văn bản
3. Câu hỏi PHẢI đòi hỏi người đọc kết hợp/so sánh/tổng hợp thông tin từ NHIỀU đoạn, KHÔNG chỉ dựa vào 1 đoạn duy nhất
4. Mỗi câu hỏi phải có đáp án đúng và giải thích dựa trên thông tin từ các đoạn

CÁC MỨC ĐỘ BLOOM:
- Trung bình (Medium) = Vận dụng (Apply) & Phân tích (Analyze): So sánh khái niệm giữa các đoạn, phân loại, tìm mối quan hệ
- Khó (Hard) = Đánh giá (Evaluate) & Sáng tạo (Create): Nhận định ưu/nhược điểm dựa trên nhiều nguồn, thiết kế giải pháp tổng hợp

ĐỊNH DẠNG TRẢ VỀ — JSON array:
[
  {
    "question_type": "mcq" hoặc "essay",
    "difficulty": "medium" / "hard",
    "bloom_level": "apply" / "analyze" / "evaluate" / "create",
    "content": "Nội dung câu hỏi (phải kết hợp thông tin từ nhiều đoạn)",
    "options": [{"label": "A", "text": "..."}, {"label": "B", "text": "..."}, {"label": "C", "text": "..."}, {"label": "D", "text": "..."}],
    "correct_answer": "A (cho MCQ) hoặc câu trả lời mẫu (cho essay)",
    "explanation": "Giải thích — chỉ rõ thông tin lấy từ đoạn nào"
  }
]

Lưu ý: Nếu question_type là "essay" thì KHÔNG cần trường "options".
Chỉ trả về JSON, không thêm text nào khác."""


@dataclass
class BundleContext:
    """Normalized bundle metadata for generation.

    Keeps the generator compatible with both the old assignment shape
    (`chunk_id`, `chunk_text`, `context_chunks`) and the newer richer shape
    (`primary_chunk`, `supporting_chunks`, `bundle_strategy`, `evidence_roles`).
    """
    primary_chunk_id: str
    primary_chunk_text: str
    bundle_strategy: str
    chunk_mode: str
    supporting_chunks: list[dict] = field(default_factory=list)
    source_chunk_ids: list[str] = field(default_factory=list)
    evidence_roles: dict[str, str] = field(default_factory=dict)
    bundle_score: float = 0.0
    assignment_reason: str = ""


class QuestionGeneratorAgent:
    """Generates exam questions grounded in retrieved textbook content."""

    def __init__(self, llm):
        self.llm = llm

    def _normalize_bundle_context(self, chunk_assignment: ChunkAssignment) -> BundleContext:
        """Normalize chunk assignment metadata into a single bundle view."""
        primary = getattr(chunk_assignment, "primary_chunk", None) or {
            "chunk_id": chunk_assignment.chunk_id,
            "chunk_text": chunk_assignment.chunk_text,
        }

        primary_chunk_id = primary.get("chunk_id", chunk_assignment.chunk_id)
        primary_chunk_text = primary.get("chunk_text", chunk_assignment.chunk_text)

        supporting_chunks = list(chunk_assignment.get_supporting_chunks())
        evidence_roles = dict(getattr(chunk_assignment, "evidence_roles", {}) or {})
        if primary_chunk_id:
            evidence_roles.setdefault(primary_chunk_id, "primary")

        source_chunk_ids = []
        explicit_source_chunks = getattr(chunk_assignment, "source_chunks", None)
        if explicit_source_chunks:
            source_chunk_ids = list(explicit_source_chunks)
        elif hasattr(chunk_assignment, "get_source_chunk_ids"):
            source_chunk_ids = chunk_assignment.get_source_chunk_ids()
        else:
            source_chunk_ids = [primary_chunk_id]
            for chunk in supporting_chunks:
                chunk_id = chunk.get("chunk_id")
                if chunk_id and chunk_id not in source_chunk_ids:
                    source_chunk_ids.append(chunk_id)

        return BundleContext(
            primary_chunk_id=primary_chunk_id,
            primary_chunk_text=primary_chunk_text,
            bundle_strategy=getattr(chunk_assignment, "bundle_strategy", "single") or "single",
            chunk_mode=getattr(chunk_assignment, "chunk_mode", "single") or "single",
            supporting_chunks=supporting_chunks,
            source_chunk_ids=source_chunk_ids,
            evidence_roles=evidence_roles,
            bundle_score=getattr(chunk_assignment, "bundle_score", 0.0) or 0.0,
            assignment_reason=getattr(chunk_assignment, "assignment_reason", "") or "",
        )

    def _format_bundle_segments(
        self,
        bundle: BundleContext,
        max_chars: int,
    ) -> tuple[list[str], list[str], list[str]]:
        """Format primary/supporting chunks for prompt input and traceability."""
        segments: list[str] = []
        all_chunk_ids: list[str] = []
        all_chunk_texts: list[str] = []

        primary_text = bundle.primary_chunk_text
        if len(primary_text) > max_chars:
            primary_text = primary_text[:max_chars] + "..."
        segments.append(
            "=== NGUỒN TRUNG TÂM / PRIMARY CHUNK ===\n\n"
            f"{primary_text}"
        )
        all_chunk_ids.append(bundle.primary_chunk_id)
        all_chunk_texts.append(bundle.primary_chunk_text[:500])

        for i, extra in enumerate(bundle.supporting_chunks, start=2):
            extra_text = extra.get("chunk_text", "")
            if len(extra_text) > max_chars:
                extra_text = extra_text[:max_chars] + "..."
            chunk_id = extra.get("chunk_id", f"support-{i}")
            role = bundle.evidence_roles.get(chunk_id, extra.get("role", "support"))
            segments.append(f"=== NGUỒN BỔ TRỢ {i - 1} ({role}) ===\n\n{extra_text}")
            if chunk_id not in all_chunk_ids:
                all_chunk_ids.append(chunk_id)
                all_chunk_texts.append(extra.get("chunk_text", "")[:500])

        return segments, all_chunk_ids, all_chunk_texts

    def _build_single_source_evidence(
        self,
        chunk_assignment: ChunkAssignment,
    ) -> list[dict]:
        return [
            {
                "chunk_id": chunk_assignment.chunk_id,
                "chapter_number": chunk_assignment.chapter,
                "role": "primary",
                "text_preview": chunk_assignment.chunk_text[:500],
            }
        ]

    def _build_bundle_source_evidence(
        self,
        bundle: BundleContext,
    ) -> list[dict]:
        evidence = [
            {
                "chunk_id": bundle.primary_chunk_id,
                "role": "primary",
                "text_preview": bundle.primary_chunk_text[:500],
            }
        ]
        for chunk in bundle.supporting_chunks:
            evidence.append(
                {
                    "chunk_id": chunk.get("chunk_id", ""),
                    "chapter_number": chunk.get("chapter_number"),
                    "page": chunk.get("page"),
                    "parent_heading": chunk.get("parent_heading"),
                    "role": bundle.evidence_roles.get(
                        chunk.get("chunk_id", ""),
                        chunk.get("role", "support"),
                    ),
                    "score": chunk.get("relatedness_score"),
                    "text_preview": (chunk.get("chunk_text", "") or "")[:500],
                }
            )
        return evidence

    def _build_context_source_evidence(self, context: RetrievedContext) -> list[dict]:
        evidence = []
        for chunk in context.chunks:
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            evidence.append(
                {
                    "chunk_id": chunk.get("id", ""),
                    "chapter_number": metadata.get("chapter_number"),
                    "page": metadata.get("page"),
                    "parent_heading": metadata.get("parent_heading"),
                    "role": "primary",
                    "score": chunk.get("score"),
                    "text_preview": (chunk.get("text", "") or "")[:500],
                }
            )
        return evidence

    def _normalize_rubric(self, question_type: str, payload: dict) -> dict | None:
        rubric = payload.get("rubric")
        if isinstance(rubric, dict):
            return rubric
        if question_type == "essay":
            explanation = (payload.get("explanation") or "").strip()
            if explanation:
                return {"guidance": explanation}
        return None

    def _build_bundle_user_message(
        self,
        assignments: list[dict],
        bundle: BundleContext,
        combined_text: str,
    ) -> str:
        """Build a strategy-aware prompt for local/semantic bundle generation."""
        task_descriptions = []
        for assignment in assignments:
            diff = assignment["difficulty"]
            q_type = assignment["question_type"]

            if diff == "medium":
                bloom_desc = (
                    "vận dụng/phân tích: so sánh khái niệm giữa các đoạn, "
                    "phân loại, tìm mối quan hệ"
                )
            else:
                bloom_desc = (
                    "đánh giá/sáng tạo: nhận định ưu/nhược điểm dựa trên "
                    "nhiều nguồn, thiết kế giải pháp tổng hợp"
                )

            type_desc = (
                "trắc nghiệm (MCQ, 4 lựa chọn A-D)"
                if q_type == "mcq"
                else "tự luận (essay)"
            )
            task_descriptions.append(
                f"- 1 câu hỏi {type_desc}, mức độ {diff.upper()} ({bloom_desc})"
            )

        strategy_guidance = {
            "local_multi": (
                "Ưu tiên dùng nguồn trung tâm làm trục chính, sau đó kết nối với các nguồn bổ trợ "
                "gần về cấu trúc/chủ đề để tạo câu hỏi tổng hợp mạch lạc."
            ),
            "semantic_multi": (
                "Ưu tiên tổng hợp ý từ nguồn trung tâm với các nguồn bổ trợ có quan hệ khái niệm, "
                "ví dụ định nghĩa - ví dụ - ngoại lệ - so sánh, thay vì chỉ gom các đoạn gần nhau."
            ),
            "multi": (
                "Dùng nguồn trung tâm làm neo chính, các nguồn bổ trợ để mở rộng, đối chiếu hoặc minh họa."
            ),
        }

        task_list = "\n".join(task_descriptions)
        source_summary = ", ".join(bundle.source_chunk_ids)

        return (
            f"Dựa vào CÁC đoạn văn bản dưới đây, hãy sinh ra chính xác "
            f"{len(assignments)} câu hỏi TỔNG HỢP.\n\n"
            f"Chunk mode: {bundle.chunk_mode}\n"
            f"Bundle strategy: {bundle.bundle_strategy}\n"
            f"Bundle score: {bundle.bundle_score:.2f}\n"
            f"Primary chunk: {bundle.primary_chunk_id}\n"
            f"Supporting chunks: {[c.get('chunk_id') for c in bundle.supporting_chunks]}\n"
            f"Traceable source chunks: {source_summary}\n"
            f"Assignment reason: {bundle.assignment_reason or 'n/a'}\n\n"
            f"YÊU CẦU QUAN TRỌNG:\n"
            f"- Chunk chính là nguồn trung tâm, phải được phản ánh trong nội dung câu hỏi.\n"
            f"- Supporting chunks chỉ dùng để bổ trợ, mở rộng, đối chiếu hoặc tổng hợp.\n"
            f"- Không được bỏ qua chunk chính để chỉ hỏi từ chunk phụ.\n"
            f"- Giải thích phải có khả năng truy vết về các source chunks.\n"
            f"- {strategy_guidance.get(bundle.bundle_strategy, strategy_guidance['multi'])}\n\n"
            f"{task_list}\n\n"
            f"{combined_text}\n\n"
            f"=== HẾT VĂN BẢN ===\n\n"
            f"Trả về JSON array chứa đúng {len(assignments)} câu hỏi."
        )

    # ─── Micro-prompting: generate from a single chunk ──────────────

    async def generate_from_single_chunk(
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
        source_evidence = self._build_single_source_evidence(chunk_assignment)
        for i, q_data in enumerate(questions_data):
            if i >= len(assignments):
                break

            a = assignments[i]
            options = q_data.get("options") if q_data.get("question_type", a["question_type"]) == "mcq" else None

            generated.append(GeneratedQuestion(
                slot_number=a.get("slot_number", 0),
                blueprint_cell_key=a.get("blueprint_cell_key", ""),
                question_type=q_data.get("question_type", a["question_type"]),
                bloom_level=q_data.get("bloom_level", a["bloom_level"]),
                difficulty_score=self._difficulty_to_score(
                    q_data.get("difficulty", a["difficulty"])
                ),
                content=q_data.get("content", ""),
                options=options,
                correct_answer=q_data.get("correct_answer", ""),
                rubric=self._normalize_rubric(
                    q_data.get("question_type", a["question_type"]),
                    q_data,
                ),
                explanation=q_data.get("explanation", ""),
                source_chunks=[chunk_assignment.chunk_id],
                source_texts=[chunk_assignment.chunk_text[:500]],
                source_evidence=list(source_evidence),
                scope_tags=list(a.get("scope_tags") or []),
            ))

        logger.debug(
            f"Chunk {chunk_assignment.chunk_id}: generated {len(generated)}/{len(assignments)} questions"
        )

        return generated

    async def generate_from_chunk(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """Backward-compatible alias for the original single-chunk generator."""
        return await self.generate_from_single_chunk(chunk_assignment, constraints)

    # ─── Multi-chunk synthesis: generate from context bundle ────────

    async def generate_from_context_bundle(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """
        Generate synthesis questions from a multi-chunk context bundle.

        The LLM receives the primary chunk + extra context_chunks and must
        create questions that require combining information across sources.
        Used for medium/hard slots (Phase 3).
        """
        assignments = chunk_assignment.assignments
        if not assignments:
            return []

        max_chars = settings.MAX_CHUNK_CHARS
        bundle = self._normalize_bundle_context(chunk_assignment)
        segments, all_chunk_ids, all_chunk_texts = self._format_bundle_segments(
            bundle=bundle,
            max_chars=max_chars,
        )
        combined_text = "\n\n".join(segments)
        user_message = self._build_bundle_user_message(
            assignments=assignments,
            bundle=bundle,
            combined_text=combined_text,
        )

        extra = ""
        if constraints.get("strict_grounding", True):
            extra = (
                "\n\nLƯU Ý QUAN TRỌNG: Bạn đang ở chế độ STRICT GROUNDING. "
                "Mọi thông tin trong câu hỏi PHẢI có trong các đoạn văn bản trên. "
                "KHÔNG sử dụng kiến thức bên ngoài."
            )

        messages = [
            SystemMessage(content=MULTI_CHUNK_SYSTEM_PROMPT + extra),
            HumanMessage(content=user_message),
        ]

        questions_data = await self._invoke_with_retry(
            messages, chunk_assignment.chunk_id,
        )

        generated = []
        source_evidence = self._build_bundle_source_evidence(bundle)
        for i, q_data in enumerate(questions_data):
            if i >= len(assignments):
                break

            a = assignments[i]
            options = (
                q_data.get("options")
                if q_data.get("question_type", a["question_type"]) == "mcq"
                else None
            )

            generated.append(GeneratedQuestion(
                slot_number=a.get("slot_number", 0),
                blueprint_cell_key=a.get("blueprint_cell_key", ""),
                question_type=q_data.get("question_type", a["question_type"]),
                bloom_level=q_data.get("bloom_level", a["bloom_level"]),
                difficulty_score=self._difficulty_to_score(
                    q_data.get("difficulty", a["difficulty"])
                ),
                content=q_data.get("content", ""),
                options=options,
                correct_answer=q_data.get("correct_answer", ""),
                rubric=self._normalize_rubric(
                    q_data.get("question_type", a["question_type"]),
                    q_data,
                ),
                explanation=q_data.get("explanation", ""),
                source_chunks=all_chunk_ids,
                source_texts=all_chunk_texts,
                source_evidence=list(source_evidence),
                scope_tags=list(a.get("scope_tags") or []),
            ))

        logger.debug(
            f"Multi-chunk bundle {bundle.primary_chunk_id}: "
            f"generated {len(generated)}/{len(assignments)} synthesis questions"
        )

        return generated

    async def generate_from_local_bundle(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """Generate from a local multi-chunk bundle."""
        return await self.generate_from_context_bundle(chunk_assignment, constraints)

    async def generate_from_semantic_bundle(
        self,
        chunk_assignment: ChunkAssignment,
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """Generate from a semantic-style multi-chunk bundle."""
        return await self.generate_from_context_bundle(chunk_assignment, constraints)

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

        Dispatches each ChunkAssignment to the appropriate method:
        - Single-chunk (strategy=single or no support) → generate_from_single_chunk()
        - Local bundle (strategy=local_multi) → generate_from_local_bundle()
        - Semantic bundle (strategy=semantic_multi) → generate_from_semantic_bundle()
        - Fallback multi bundle → generate_from_context_bundle()
        """
        delay = settings.LLM_REQUEST_DELAY
        all_questions = []

        single_count = sum(
            1 for ca in chunk_assignments
            if (ca.bundle_strategy == "single") or not ca.get_supporting_chunks()
        )
        multi_count = len(chunk_assignments) - single_count

        logger.info(
            f"Starting sequential generation: {len(chunk_assignments)} assignments "
            f"({single_count} single-chunk, {multi_count} multi-chunk bundles), "
            f"delay={delay}s between calls"
        )

        for idx, ca in enumerate(chunk_assignments):
            bundle = self._normalize_bundle_context(ca)
            supporting_chunks = bundle.supporting_chunks
            mode = bundle.bundle_strategy or ("multi-chunk" if supporting_chunks else "single")
            logger.info(
                f"Generating {idx + 1}/{len(chunk_assignments)} "
                f"({mode}, chunk_id={ca.chunk_id[:16]}..., "
                f"tasks={len(ca.assignments)}, bundle_score={bundle.bundle_score:.2f})"
            )

            try:
                if not supporting_chunks or mode == "single":
                    questions = await self.generate_from_single_chunk(ca, constraints)
                elif mode == "local_multi":
                    questions = await self.generate_from_local_bundle(ca, constraints)
                elif mode == "semantic_multi":
                    questions = await self.generate_from_semantic_bundle(ca, constraints)
                else:
                    questions = await self.generate_from_context_bundle(ca, constraints)
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

        edit_prompt = (constraints.get("_edit_prompt") or "").strip()
        edit_instruction = ""
        if edit_prompt:
            edit_instruction = (
                "\n\nEdit guidance to preserve while regenerating:\n"
                f"{edit_prompt}\n"
                "Keep the same scope, answerability requirements, and question family."
            )

        user_message = f"""Generate a {slot.question_type.upper()} question with these specifications:

Chapter: {slot.target_chapter}
Topics: {', '.join(slot.target_topics) if slot.target_topics else 'General'}
Bloom's Level: {slot.bloom_level}
Difficulty: {slot.difficulty_score:.2f} (scale 0.0-1.0)
Question Number: {slot.slot_number}
Scope Tags: {', '.join(getattr(slot, 'scope_tags', []) or [])}

=== TEXTBOOK CONTEXT (use ONLY this information) ===

{context.combined_text}

=== END CONTEXT ===

Generate the question now.{edit_instruction}"""

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
            blueprint_cell_key=getattr(slot, "blueprint_cell_key", ""),
            question_type=slot.question_type,
            bloom_level=slot.bloom_level,
            difficulty_score=slot.difficulty_score,
            content=question_data.get("content", ""),
            options=options,
            correct_answer=question_data.get("correct_answer", ""),
            rubric=self._normalize_rubric(slot.question_type, question_data),
            explanation=question_data.get("explanation", ""),
            source_chunks=[c["id"] for c in context.chunks],
            source_texts=[c["text"] for c in context.chunks],
            source_evidence=self._build_context_source_evidence(context),
            scope_tags=list(getattr(slot, "scope_tags", []) or []),
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
            blueprint_cell_key=original_question.blueprint_cell_key,
            scope_tags=list(original_question.scope_tags or []),
        )

        if edit_prompt:
            # Add specific edit guidance
            constraints = {**constraints, "_edit_prompt": edit_prompt}

        regenerated = await self._generate_single(slot, context, constraints)
        regenerated.is_locked = original_question.is_locked
        return regenerated
