"""clarification_check — G1: Check if requirements are clear."""

import json
import logging
import re

from app.agents.graph.state import ExamGraphState, PipelineStatus

logger = logging.getLogger("app.agents.graph")

# Keywords that suggest bloom-chapter concentration (ambiguous without explicit counts)
_VAGUE_QUANTIFIERS = [
    "nhiều", "ít hơn", "phần lớn", "chủ yếu", "mostly", "focus on",
]


def _is_prompt_ambiguous(user_prompt: str, exam_config: dict) -> list[dict]:
    """
    Check if user_prompt contains bloom-chapter concentration hints without
    explicit slot counts. Returns list of clarification questions, or [] if clear.

    Triggers when:
    - User mentions bloom level + chapter + concentration keyword (tập trung/ưu tiên)
      but does NOT specify a count or percentage.
    - User uses vague quantifiers (nhiều, phần lớn) with chapter mentions.
    """
    if not user_prompt or len(user_prompt.strip()) < 10:
        return []

    prompt_lower = user_prompt.lower()
    questions: list[dict] = []

    # Detect chapter/section mentions
    chapter_mentions = re.findall(r'chương\s*\d+|phần\s*\d+|section\s*\d+', prompt_lower)
    bloom_mentions = [kw for kw in ["vận dụng cao", "vận dụng", "nhận biết", "thông hiểu"]
                      if kw in prompt_lower]

    # Bloom + chapter + concentration keyword, but no explicit count
    if bloom_mentions and chapter_mentions:
        has_count = bool(re.search(r'\d+\s*(?:câu|slot|bài|phần trăm|%)', prompt_lower))
        has_concentration_kw = any(
            kw in prompt_lower
            for kw in ["tập trung", "ưu tiên", "nhiều hơn", "trọng tâm", "chủ yếu"]
        )
        if has_concentration_kw and not has_count:
            chap_str = ", ".join(set(chapter_mentions))
            bloom_str = ", ".join(set(bloom_mentions))
            questions.append({
                "question_id": "bloom_chapter_count",
                "question": (
                    f"Bạn muốn tập trung {bloom_str} vào {chap_str}. "
                    "Cụ thể bạn muốn phân bổ bao nhiêu câu (hoặc %) cho phần đó?\n"
                    "Ví dụ: \"5 câu vận dụng ở chương 3\" hoặc \"40% câu vận dụng từ chương 3, 4\""
                ),
            })

    # Vague quantifiers + chapter mentions (without bloom, different kind of ambiguity)
    if not questions:
        vague_hits = [kw for kw in _VAGUE_QUANTIFIERS if kw in prompt_lower]
        if vague_hits and chapter_mentions:
            chap_str = ", ".join(set(chapter_mentions))
            questions.append({
                "question_id": "distribution_count",
                "question": (
                    f"Bạn dùng từ \"{vague_hits[0]}\" khi đề cập đến {chap_str}. "
                    "Bạn có thể cho biết cụ thể số câu hoặc tỉ lệ % mong muốn không?"
                ),
            })

    return questions[:2]  # Max 2 clarification questions at once


async def clarification_check(state: ExamGraphState) -> ExamGraphState:
    """
    G1: Check if user requirements are clear.

    Quick check first: if essential config fields are present (document_id or
    textbook_namespace, scope, and at least one question count), skip the
    expensive LLM call and proceed directly.

    Even when config is structurally complete, performs a lightweight ambiguity
    check on user_prompt to catch vague bloom-chapter concentration requests
    that would cause the outline to generate incorrectly.

    Args:
        state: Must contain user_prompt, exam_config.

    Returns:
        Updated ExamGraphState with pipeline_status set appropriately.
    """
    user_prompt = state.get("user_prompt") or ""
    exam_config = state.get("exam_config", {})

    # ── Structural completeness check ────────────────────────────────────────
    has_document = bool(
        state.get("document_id") or exam_config.get("document_id")
        or state.get("textbook_namespace") or exam_config.get("textbook_namespace")
    )
    has_scope = bool(state.get("scope") or exam_config.get("scope"))
    has_questions = (
        int(exam_config.get("mcq_count", 0) or 0) > 0
        or int(exam_config.get("essay_count", 0) or 0) > 0
        or int(exam_config.get("dung_sai_count", 0) or 0) > 0
        or int(exam_config.get("short_answer_count", 0) or 0) > 0
    )

    if has_document and has_scope and has_questions:
        # ── Lightweight ambiguity check on user_prompt ───────────────────────
        ambiguous_qs = _is_prompt_ambiguous(user_prompt, exam_config)
        if ambiguous_qs:
            logger.info(
                "Clarification check: AMBIGUOUS prompt (%d questions generated)",
                len(ambiguous_qs),
            )
            return {
                **state,
                "pipeline_status": PipelineStatus.CLARIFICATION_NEEDED,
                "checkpoint_0_requirements": {"clarification_questions": ambiguous_qs},
                "warnings": state.get("warnings", []) + [
                    "Prompt ambiguous — clarification requested before generating outline"
                ],
            }

        logger.info(
            "Clarification check: SKIP (document, scope, and question counts present)"
        )
        return {
            **state,
            "pipeline_status": PipelineStatus.RUNNING,
            "checkpoint_0_status": "approved",  # type: ignore
            "checkpoint_0_requirements": {
                "scope": state.get("scope", []),
                "exam_config": exam_config,
            },
        }

    # ── LLM clarification (only when config is structurally incomplete) ──────
    CLARIFY_PROMPT = """Bạn là trợ lý giúp giảng viên tạo đề kiểm tra.

Nếu yêu cầu chưa rõ ràng, hãy đặt tối đa 3 câu hỏi làm rõ:
- Scope (phạm vi bài kiểm tra — chương nào, phần nào)
- Số lượng và loại câu hỏi (MCQ, đúng-sai, trả lời ngắn, essay)
- Mức độ phân bổ Bloom (nhận biết / thông hiểu / vận dụng / vận dụng cao)
- Yêu cầu đặc biệt nào khác

Trả về JSON:
{
  "clarification_questions": [
    {"question_id": "q1", "question": "..."}
  ],
  "requirements_clear": true/false
}"""

    clarity_prompt = f"""Yêu cầu hiện tại:
Prompt: {user_prompt}
Config: {json.dumps(exam_config, ensure_ascii=False, indent=2)}

Xác định xem yêu cầu đã đủ thông tin để tạo đề chưa."""

    messages = [
        {"role": "system", "content": CLARIFY_PROMPT},
        {"role": "user", "content": clarity_prompt},
    ]

    try:
        from app.agents.llm import get_llm_client
        client = get_llm_client()
        response = await client.chat(
            messages=messages,
            role="planner",
            max_tokens=1000,
            temperature=0.3,
        )
        result = json.loads(response)
        if not result.get("requirements_clear", True):
            questions = result.get("clarification_questions", [])
            if questions:
                return {
                    **state,
                    "pipeline_status": PipelineStatus.CLARIFICATION_NEEDED,
                    "checkpoint_0_requirements": {"clarification_questions": questions[:3]},
                    "warnings": state.get("warnings", []) + [
                        "Requirements unclear — clarification needed"
                    ],
                }
    except Exception as exc:
        logger.warning("Clarification LLM check failed: %s", exc)

    # Default: proceed with whatever we have
    return {
        **state,
        "pipeline_status": PipelineStatus.RUNNING,
        "checkpoint_0_status": "approved",  # type: ignore
        "checkpoint_0_requirements": {
            "scope": state.get("scope", []),
            "exam_config": state.get("exam_config", {}),
        },
    }
