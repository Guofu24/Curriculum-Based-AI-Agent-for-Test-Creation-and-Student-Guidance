"""Outline Agent - creates exam blueprint from retrieved context."""

import time
import json
from typing import Any

from app.agents.base import AgentBaseOutput, AgentStatus, AgentMetrics, TokenUsage, OutlineOutput
from app.agents.llm import get_llm_client
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.difficulty_estimator import DifficultyEstimatorSkill
from app.observability.tracer import get_tracer
from app.core.config import get_settings

settings = get_settings()
tracer = get_tracer()


class OutlineAgent:
    """
    Agent 2: Outline Agent

    Role: From knowledge context, create an exam blueprint (sườn đề).
    Allocates questions by Bloom level, chapter, and section.
    Ensures balanced distribution - no single chapter > 50%.

    Output: Exam Blueprint with question slots.
    """

    OUTLINE_SYSTEM_PROMPT = """Bạn là chuyên gia thiết kế đề kiểm tra.

Nhiệm vụ của bạn:
1. Phân tích kiến thức đã truy xuất được (retrieved chunks)
2. Tạo sườn đề (blueprint) với các slot câu hỏi được phân bổ theo:
   - Mức Bloom (nhan_biet, thong_hieu, van_dung, van_dung_cao)
   - Chapter (chương)
   - Section (phần)
   - Loại nội dung (text, calculation, applied_problem, conceptual)
3. Đảm bảo phân bổ đều các chapter (không chapter nào > 50% tổng số câu)
4. Ưu tiên chapters có nhiều công thức cho mức van_dung_cao

Blueprint slot structure:
- question_id: "MCQ_001", "ESSAY_001", etc.
- type: "mcq" hoặc "essay"
- bloom_level: "nhan_biet" | "thong_hieu" | "van_dung" | "van_dung_cao"
- chapter: tên chapter
- section: tên section (nếu có)
- topic_hint: gợi ý chủ đề cụ thể
- content_type: "text" | "calculation" | "applied_problem" | "conceptual"
- estimated_difficulty: 0.0-1.0

Distribution rules:
- Convert bloom % → số câu, làm tròn hợp lý
- Đảm bảo tổng MCQ + Essay = config count
- MCQ phân bổ đều theo chapters
- Essay: ít hơn MCQ, tập trung vào van_dung và van_dung_cao

Trả về JSON:
{
  "blueprint": [slot1, slot2, ...],
  "distribution_summary": {
    "by_bloom": {"nhan_biet": N, "thong_hieu": N, "van_dung": N, "van_dung_cao": N},
    "by_chapter": {"Chương 1": N, "Chương 2": N, ...}
  }
}"""

    def __init__(self):
        self.llm = get_llm_client()
        self.bloom_skill = BloomClassifierSkill()
        self.difficulty_skill = DifficultyEstimatorSkill()

    @tracer.agent_span("outline_agent")
    async def create_outline(
        self,
        retrieved_context: list[dict],
        exam_config: dict,
        trace_id: str = "",
    ) -> OutlineOutput:
        """Create exam blueprint from retrieved context."""
        start_time = time.time()
        trace_id = trace_id or str(time.time())
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []

        try:
            # Build context summary for LLM
            context_summary = self._build_context_summary(retrieved_context)

            # Build user prompt
            user_prompt = self._build_outline_prompt(retrieved_context, exam_config)

            # Call LLM
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.OUTLINE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                role="outline",
                max_tokens=4000,
                temperature=0.3,
            )

            result = json.loads(response)
            blueprint = result.get("blueprint", [])
            distribution_summary = result.get("distribution_summary", {})

            valid_llm, reason_llm = self.validate_blueprint(blueprint)
            if not valid_llm:
                warnings.append(f"LLM blueprint invalid: {reason_llm}")
                # Try fallback
                try:
                    fallback_out = await self._fallback_outline(
                        exam_config, start_time, trace_id, warnings
                    )
                    fallback_bp = fallback_out.blueprint
                except ValueError as fe:
                    # Fallback itself raised — propagate with context
                    raise ValueError(
                        f"Both LLM and fallback blueprints are invalid. "
                        f"LLM: {reason_llm}. Fallback: {fe}"
                    ) from fe

                valid_fb, reason_fb = self.validate_blueprint(fallback_bp)
                if not valid_fb:
                    raise ValueError(
                        f"Both LLM and fallback blueprints are invalid. "
                        f"LLM: {reason_llm}. Fallback: {reason_fb}"
                    )

                # Fallback succeeded — use it
                return fallback_out

            # Validate distribution
            validation_warning = self._validate_distribution(
                blueprint, exam_config, retrieved_context
            )
            if validation_warning:
                warnings.append(validation_warning)

            # If blueprint doesn't match config, adjust
            actual_total = len(blueprint)
            expected_total = (
                exam_config.get("mcq_count", 40) + exam_config.get("essay_count", 5)
            )

            if abs(actual_total - expected_total) > 2:
                warnings.append(
                    f"Blueprint has {actual_total} questions but config expects {expected_total}"
                )

            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = metrics.prompt_tokens + metrics.completion_tokens

            return OutlineOutput(
                status=AgentStatus.SUCCESS,
                agent_name="outline",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(
                    prompt_tokens=metrics.prompt_tokens,
                    completion_tokens=metrics.completion_tokens,
                    total_tokens=usage,
                ),
                warnings=warnings,
                trace_id=trace_id,
                blueprint=blueprint,
                distribution_summary=distribution_summary,
            )

        except json.JSONDecodeError as e:
            warnings.append(f"Failed to parse blueprint JSON: {e}")
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

        except Exception as e:
            warnings.append(f"Outline creation failed: {str(e)}")
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

    def _build_context_summary(self, context: list[dict]) -> str:
        """Build a summary of retrieved context."""
        summary_parts = []

        # Group by chapter
        by_chapter: dict[str, list[str]] = {}
        for chunk in context:
            chapter = chunk.get("chapter", "Unknown")
            if chapter not in by_chapter:
                by_chapter[chapter] = []
            content = chunk.get("content", "")[:200]
            by_chapter[chapter].append(content)

        for chapter, contents in by_chapter.items():
            summary_parts.append(f"### {chapter}")
            for c in contents[:3]:  # Max 3 excerpts per chapter
                summary_parts.append(f"- {c}")
            summary_parts.append("")

        return "\n".join(summary_parts)

    def _build_outline_prompt(
        self,
        retrieved_context: list[dict],
        exam_config: dict,
    ) -> str:
        """Build the user prompt for outline creation."""
        scope = exam_config.get("scope", [])
        mcq_count = exam_config.get("mcq_count", 40)
        essay_count = exam_config.get("essay_count", 5)
        bloom_dist = exam_config.get("bloom_distribution", {})
        user_prompt = exam_config.get("user_prompt", "")
        extra_instructions = exam_config.get("extra_instructions", "")
        # G8: HITL feedback from rejected blueprint
        outline_feedback = exam_config.get("outline_feedback", "")

        feedback_section = ""
        if outline_feedback:
            feedback_section = f"""
## Phan hoi tu giang vien (HITL - G8):
{outline_feedback}

Hay dieu chinh blueprint theo phan hoi tren.
"""

        prompt = f"""Tao suon de kiem tra voi cau hinh sau:

## Scope (pham vi bai kiem tra):
{json.dumps(scope, ensure_ascii=False)}

## Cau hinh de:
- Tong so cau MCQ: {mcq_count}
- Tong so cau Essay: {essay_count}
- Phan bo Bloom:
{json.dumps(bloom_dist, ensure_ascii=False, indent=2)}

## Kien thuc da truy xuat:
{self._build_context_summary(retrieved_context)}

## Yeu cau tu giang vien:
{user_prompt or "Khong co yeu cau dac biet."}

## Huong dan bo sung:
{extra_instructions or "Sinh cau hoi chuan muc, phu hop voi chuong trinh pho thong Viet Nam."}
{feedback_section}
Tao blueprint chi tiet:"""

        return prompt

    def _validate_distribution(
        self,
        blueprint: list[dict],
        exam_config: dict,
        context: list[dict],
    ) -> str | None:
        """Validate that blueprint distribution is reasonable."""
        if not blueprint:
            return "Blueprint is empty"

        # Check chapter distribution
        chapters_in_blueprint: dict[str, int] = {}
        for slot in blueprint:
            ch = slot.get("chapter", "Unknown")
            chapters_in_blueprint[ch] = chapters_in_blueprint.get(ch, 0) + 1

        total = len(blueprint)
        for ch, count in chapters_in_blueprint.items():
            if count / total > 0.5:
                return f"Chapter '{ch}' has {count}/{total} questions (>50%). Distribution is unbalanced."

        return None

    def validate_blueprint(self, bp: list[dict]) -> tuple[bool, str]:
        """
        Validate blueprint slots conform to the actual slot schema used by both
        the LLM and the fallback generator.

        Required fields per slot:
          - question_id:  str (non-empty, format "MCQ_NNN" or "ESSAY_NNN")
          - bloom_level:  str (non-empty, one of the 4 Bloom levels)
          - chapter:       str (non-empty)

        Optional-but-warned fields (not enforced here):
          type, section, topic_hint, content_type, estimated_difficulty

        Returns (True, "") if valid, (False, reason) if invalid.
        """
        if not isinstance(bp, list):
            return False, f"Blueprint must be a list, got {type(bp).__name__}"

        valid_blooms = {"nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"}

        for i, slot in enumerate(bp):
            if not isinstance(slot, dict):
                return False, f"Blueprint[{i}] is not a dict: {type(slot).__name__}"

            missing: list[str] = []
            if not slot.get("question_id"):
                missing.append("question_id")
            if not slot.get("bloom_level"):
                missing.append("bloom_level")
            elif slot["bloom_level"] not in valid_blooms:
                return False, (
                    f"Blueprint[{i}] bloom_level '{slot['bloom_level']}' is not valid "
                    f"(expected one of {valid_blooms})"
                )
            if not slot.get("chapter"):
                missing.append("chapter")
            if missing:
                return False, f"Blueprint[{i}] missing required keys: {missing}"

        return True, ""

    async def _fallback_outline(
        self,
        exam_config: dict,
        start_time: float,
        trace_id: str,
        warnings: list[str],
    ) -> OutlineOutput:
        """Fallback when LLM fails - create default outline."""
        warnings.append("Using fallback default blueprint")

        scope = exam_config.get("scope", [])
        mcq_count = exam_config.get("mcq_count", 40)
        essay_count = exam_config.get("essay_count", 5)
        bloom_dist = exam_config.get("bloom_distribution", {
            "nhan_biet": 20, "thong_hieu": 30, "van_dung": 30, "van_dung_cao": 20
        })

        # Simple round-robin allocation
        blueprint = []
        bloom_levels = list(bloom_dist.keys())
        chapters = scope if scope else ["Chương 1"]

        mcq_id = 1
        essay_id = 1

        for bloom in bloom_levels:
            bloom_count = round(mcq_count * bloom_dist.get(bloom, 25) / 100)
            for i in range(bloom_count):
                chapter = chapters[i % len(chapters)]
                slot = {
                    "question_id": f"MCQ_{mcq_id:03d}",
                    "type": "mcq",
                    "bloom_level": bloom,
                    "chapter": chapter,
                    "section": None,
                    "topic_hint": f"Câu hỏi mức {bloom}",
                    "content_type": "calculation" if bloom in ["van_dung", "van_dung_cao"] else "text",
                    "estimated_difficulty": {"nhan_biet": 0.2, "thong_hieu": 0.4, "van_dung": 0.6, "van_dung_cao": 0.85}.get(bloom, 0.5),
                }
                blueprint.append(slot)
                mcq_id += 1

        for i in range(essay_count):
            chapter = chapters[i % len(chapters)]
            slot = {
                "question_id": f"ESSAY_{essay_id:03d}",
                "type": "essay",
                "bloom_level": "van_dung",
                "chapter": chapter,
                "section": None,
                "topic_hint": "Câu tự luận vận dụng",
                "content_type": "applied_problem",
                "estimated_difficulty": 0.7,
            }
            blueprint.append(slot)
            essay_id += 1

        distribution_summary = {
            "by_bloom": {level: round(mcq_count * bloom_dist.get(level, 25) / 100) for level in bloom_levels},
            "by_chapter": {
                ch: sum(1 for slot in blueprint if slot.get("chapter") == ch)
                for ch in chapters
            },
        }

        valid, reason = self.validate_blueprint(blueprint)
        if not valid:
            raise ValueError(f"Fallback blueprint invalid: {reason}")

        elapsed_ms = int((time.time() - start_time) * 1000)

        return OutlineOutput(
            status=AgentStatus.PARTIAL,
            agent_name="outline",
            execution_time_ms=elapsed_ms,
            token_usage=TokenUsage(),
            warnings=warnings,
            trace_id=trace_id,
            blueprint=blueprint,
            distribution_summary=distribution_summary,
        )