"""Outline Agent - creates exam blueprint from retrieved context."""

import logging
import time
import json
from typing import Any

from app.agents.base import AgentBaseOutput, AgentStatus, AgentMetrics, TokenUsage, OutlineOutput
from app.agents.llm import get_llm_client
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.difficulty_estimator import DifficultyEstimatorSkill
from app.observability.tracer import get_tracer
from app.core.config import get_settings

# Domain 9: Prompt versioning
OUTLINE_PROMPT_VERSION = "v2.1"

settings = get_settings()
tracer = get_tracer()
logger = logging.getLogger("app.agents.outline")


class OutlineAgent:
    """
    Agent 2: Outline Agent

    Role: From knowledge context, create an exam blueprint (sườn đề).
    Allocates questions by Bloom level, chapter, and section.
    Ensures balanced distribution - no single chapter > 50%.

    Output: Exam Blueprint with question slots.
    """

    OUTLINE_SYSTEM_PROMPT = """[PROMPT_VERSION: v2.1]

## Vai trò
Mày là chuyên gia thiết kế đề kiểm tra giáo dục đại học Việt Nam.

## Nhiệm vụ
Tạo sườn đề (blueprint) với các slot câu hỏi được phân bổ theo:
  - Mức Bloom (nhan_biet, thong_hieu, van_dung, van_dung_cao)
  - Chapter (chương)
  - Section (phần)
  - Loại nội dung (text, calculation, applied_problem, conceptual)

## Ràng buộc nghiêm ngặt
- Tổng MCQ + Essay phải KHỚP với config
- **Phân bổ Bloom phải CHÍNH XÁC**: tổng slot mỗi mức = config yêu cầu (±0 câu)
- Không chapter nào chiếm > 50% tổng số câu
- MCQ: 4 lựa chọn, 1 đúng, 3 mồi nhử có logic
- Essay: có rubric chấm điểm

## Taxonomy Bloom đầy đủ
- **nhan_biet** (Nhận biết): Định nghĩa, liệt kê, nêu tên — câu hỏi bắt đầu bằng "Định nghĩa", "Nêu", "Liệt kê", "Cho biết"
- **thong_hieu** (Thông hiểu): Giải thích, so sánh, diễn giải — áp dụng công thức đơn giản 1 bước
- **van_dung** (Vận dụng): Tính toán 2-3 bước, có điều kiện ràng buộc
- **van_dung_cao** (Vận dụng cao): Phân tích mối quan hệ, đánh giá, bài toán phức hợp, nhiều công thức kết hợp

## Few-shot example (tham khảo format output)
```json
{
  "blueprint": [
    {"question_id": "MCQ_001", "type": "mcq", "bloom_level": "nhan_biet", "chapter": "Chương 1", "section": "1.1", "topic_hint": "Định nghĩa lực", "content_type": "text", "estimated_difficulty": 0.2},
    {"question_id": "MCQ_002", "type": "mcq", "bloom_level": "thong_hieu", "chapter": "Chương 1", "section": "1.2", "topic_hint": "Định luật 1 Newton", "content_type": "text", "estimated_difficulty": 0.4}
  ],
  "distribution_summary": {
    "by_bloom": {"nhan_biet": 10, "thong_hieu": 15, "van_dung": 10, "van_dung_cao": 5},
    "by_chapter": {"Chương 1": 12, "Chương 2": 10, "Chương 3": 18}
  }
}
```

## Chain-of-thought (suy luận trước khi output)
Với mỗi blueprint, trước tiên suy nghĩ:
1. Tổng câu = MCQ + Essay = ?
2. Phân bổ câu cho từng chapter: mỗi chapter được phân bao nhiêu câu?
3. Trong mỗi chapter, phân bổ Bloom level như thế nào?
4. Kiểm tra: tổng slot = config? Bloom sum = config?
5. Đảm bảo không có topic trùng lặp trong cùng chapter

## Self-verification checklist
Trước khi trả JSON, kiểm tra:
- [ ] Tổng số slot = mcq_count + essay_count (chính xác)
- [ ] Tổng theo bloom = bloom_distribution (chính xác ±0)
- [ ] Không chapter nào > 50% tổng
- [ ] Mỗi slot có question_id, bloom_level, chapter (đầy đủ)
- [ ] Topic hints không trùng nhau trong cùng chapter

## Output format
Trả về JSON với schema:
{
  "blueprint": [slot...],
  "distribution_summary": {
    "by_bloom": {...},
    "by_chapter": {...}
  },
  "distribution_check": {
    "bloom_total_ok": true/false,
    "chapter_balance_ok": true/false,
    "total_slots_ok": true/false
  }
}
"""

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

            # 3B: Strict Bloom distribution enforcement
            expected_bloom = exam_config.get("bloom_distribution", {})
            actual_bloom: dict[str, int] = {}
            for slot in blueprint:
                bl = slot.get("bloom_level", "unknown")
                actual_bloom[bl] = actual_bloom.get(bl, 0) + 1

            bloom_mismatch: list[str] = []
            for bloom, expected_count in expected_bloom.items():
                actual_count = actual_bloom.get(bloom, 0)
                if actual_count != expected_count:
                    bloom_mismatch.append(
                        f"Bloom '{bloom}': expected {expected_count}, got {actual_count}"
                    )

            if bloom_mismatch:
                warnings.append(f"Bloom distribution mismatch — retrying: {'; '.join(bloom_mismatch)}")
                # Retry with specific error message injected into prompt
                return await self._retry_with_bloom_feedback(
                    retrieved_context=retrieved_context,
                    exam_config=exam_config,
                    bloom_mismatch=bloom_mismatch,
                    expected_bloom=expected_bloom,
                    trace_id=trace_id,
                    start_time=start_time,
                )

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

            # ─── Strict enforcement: MCQ-only or Essay-only ───
            # If the user requested only MCQ (essay_count=0), strip any essay slots the LLM may have generated.
            # If the user requested only Essay (mcq_count=0), strip any MCQ slots.
            essay_count = exam_config.get("essay_count", 5)
            mcq_count = exam_config.get("mcq_count", 40)

            # Debug: log config values
            logger.info(f"[OUTLINE AGENT] exam_type={exam_config.get('exam_type')} "
                        f"mcq_count={mcq_count} essay_count={essay_count} "
                        f"LLM returned {len(blueprint)} slots")

            if essay_count == 0 and mcq_count > 0:
                # MCQ-only: remove essay slots, then truncate to exactly mcq_count
                blueprint = [s for s in blueprint if s.get("type") != "essay"]
                original_len = len(blueprint)
                if len(blueprint) > mcq_count:
                    blueprint = blueprint[:mcq_count]
                    warnings.append(
                        f"Blueprint had {original_len} MCQ slots but config requires {mcq_count}. "
                        "Truncated to match configuration."
                    )
                elif len(blueprint) < mcq_count:
                    warnings.append(
                        f"Blueprint has only {len(blueprint)} MCQ slots but config requires {mcq_count}."
                    )
            elif mcq_count == 0 and essay_count > 0:
                # Essay-only: remove MCQ slots
                original_len = len(blueprint)
                blueprint = [s for s in blueprint if s.get("type") != "mcq"]
                if len(blueprint) < original_len:
                    warnings.append(
                        f"LLM generated {original_len - len(blueprint)} MCQ slots but exam is Essay-only. "
                        "These were removed to match the configuration."
                    )
                if len(blueprint) > essay_count:
                    blueprint = blueprint[:essay_count]

            # If blueprint doesn't match config, adjust
            actual_total = len(blueprint)
            expected_total = mcq_count + essay_count

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

    async def _retry_with_bloom_feedback(
        self,
        retrieved_context: list[dict],
        exam_config: dict,
        bloom_mismatch: list[str],
        expected_bloom: dict[str, int],
        trace_id: str,
        start_time: float,
    ) -> OutlineOutput:
        """Retry outline generation with explicit Bloom mismatch feedback."""
        warnings = [f"Bloom distribution error: {'; '.join(bloom_mismatch)}"]

        # Inject precise correction instructions
        correction_prompt = f"""
LỖI PHÂN BỔ BLOOM - CẦN SỬA NGAY:

Các lỗi cụ thể:
{chr(10).join(f'- {m}' for m in bloom_mismatch)}

YÊU CẦU CHÍNH XÁC:
{json.dumps(expected_bloom, ensure_ascii=False, indent=2)}

Hãy tạo lại blueprint với phân bổ CHÍNH XÁC như trên.
KIỂM TRA LẠI trước khi output.
"""
        exam_config = dict(exam_config)
        exam_config["outline_feedback"] = correction_prompt

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.OUTLINE_SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_outline_prompt(retrieved_context, exam_config)},
                ],
                role="outline",
                max_tokens=4000,
                temperature=0.2,
            )
            result = json.loads(response)
            blueprint = result.get("blueprint", [])
            distribution_summary = result.get("distribution_summary", {})

            # Verify one more time
            actual_bloom: dict[str, int] = {}
            for slot in blueprint:
                bl = slot.get("bloom_level", "unknown")
                actual_bloom[bl] = actual_bloom.get(bl, 0) + 1

            for bloom, expected_count in expected_bloom.items():
                actual_count = actual_bloom.get(bloom, 0)
                if actual_count != expected_count:
                    warnings.append(
                        f"Retry also failed: Bloom '{bloom}' still mismatched ({actual_count} vs {expected_count})"
                    )

        except Exception as e:
            warnings.append(f"Retry failed: {e}")
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

        valid_llm, reason_llm = self.validate_blueprint(blueprint)
        if not valid_llm:
            warnings.append(f"Retry blueprint invalid: {reason_llm}")
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

        elapsed_ms = int((time.time() - start_time) * 1000)
        return OutlineOutput(
            status=AgentStatus.SUCCESS,
            agent_name="outline",
            execution_time_ms=elapsed_ms,
            token_usage=TokenUsage(),
            warnings=warnings,
            trace_id=trace_id,
            blueprint=blueprint,
            distribution_summary=distribution_summary,
        )

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

        # MCQ-only: strip essay slots before building essay section
        if essay_count == 0:
            return blueprint

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
