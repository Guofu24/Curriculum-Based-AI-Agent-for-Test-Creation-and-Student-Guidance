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
- Tổng MCQ + Essay + Đúng-Sai + Trả lời ngắn phải KHỚP với config
- **Phân bổ Bloom phải CHÍNH XÁC**: tổng slot mỗi mức = config yêu cầu (±0 câu)
- Không chapter nào chiếm > 50% tổng số câu
- MCQ: 4 lựa chọn, 1 đúng, 3 mồi nhử có logic
- Essay: có rubric chấm điểm
- dung_sai: 4 mệnh đề a/b/c/d, mỗi mệnh đề đúng hoặc sai (THPT 2025)
- short_answer: kết quả là con số, thí sinh điền trực tiếp (THPT 2025)

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
1. Tổng câu = MCQ + Essay + Đúng-Sai + Trả lời ngắn = ?
2. Phân bổ câu cho từng chapter: mỗi chapter được phân bao nhiêu câu?
3. Trong mỗi chapter, phân bổ Bloom level như thế nào?
4. Kiểm tra: tổng slot = config? Bloom sum = config?
5. Đảm bảo không có topic trùng lặp trong cùng chapter

## Self-verification checklist
Trước khi trả JSON, kiểm tra:
- [ ] Tổng số slot = mcq_count + essay_count + dung_sai_count + short_answer_count (chính xác)
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

    MODIFICATION_SYSTEM_PROMPT = """[PROMPT_VERSION: v2.1-mod]

## Vai trò
Mày là chuyên gia chỉnh sửa đề kiểm tra. Nhiệm vụ DUY NHẤT là CHỈNH SỬA blueprint
đã có theo phản hồi của giáo viên — KHÔNG tạo mới từ đầu.

## Nguyên tắc chỉnh sửa
- Giữ nguyên tổng số slot và phân bổ Bloom chính xác
- Điều chỉnh field "chapter", "section", "topic_hint" theo phản hồi giáo viên
- Giữ nguyên "type", "bloom_level", "content_type", "estimated_difficulty" của từng slot
- Mỗi chương phải có ít nhất 1 slot

## ⚠️ QUAN TRỌNG — Output đầy đủ
Output phải chứa TẤT CẢ các slot trong blueprint (không bỏ sót bất kỳ câu nào).
NEVER output chỉ các slot đã thay đổi — output TOÀN BỘ danh sách blueprint với số lượng
slot CHÍNH XÁC bằng số slot đã nhận được.

## Taxonomy Bloom
- **nhan_biet**: Định nghĩa, liệt kê, nhận biết
- **thong_hieu**: Giải thích, so sánh, áp dụng đơn giản
- **van_dung**: Tính toán 2-3 bước, có điều kiện
- **van_dung_cao**: Phân tích, đánh giá, bài toán phức hợp

## Output format (BẮT BUỘC - JSON thuần, không markdown)
{
  "blueprint": [TẤT CẢ slot đã chỉnh sửa — đủ số lượng như đầu vào],
  "distribution_summary": {
    "by_bloom": {"nhan_biet": N, "thong_hieu": N, "van_dung": N, "van_dung_cao": N},
    "by_chapter": {"Tên chương": count}
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

        # Determine mode before try block so except handlers can reference it
        is_modification = bool(
            exam_config.get("outline_feedback") and exam_config.get("current_blueprint")
        )

        try:
            # Build context summary for LLM
            context_summary = self._build_context_summary(retrieved_context)

            # Build user prompt
            user_prompt = self._build_outline_prompt(retrieved_context, exam_config)

            # Choose system prompt based on mode
            system_prompt = (
                self.MODIFICATION_SYSTEM_PROMPT if is_modification
                else self.OUTLINE_SYSTEM_PROMPT
            )

            # Modification mode needs higher token limit:
            # 28 slots × ~200 chars/slot ≈ 5600 chars + distribution_summary overhead
            _max_tokens = 8192 if is_modification else 4000

            # Call LLM
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                role="outline",
                max_tokens=_max_tokens,
                temperature=0.3,
            )

            print(f"[OutlineAgent] RAW ({len(response)} chars): {response[:400]!r}", flush=True)
            # Strip markdown code fences before parsing (model often wraps JSON in ```json...```)
            _clean = response.strip()
            if _clean.startswith("```"):
                _clean = _clean.split("```", 2)[1] if _clean.count("```") >= 2 else _clean.split("\n", 1)[-1]
                _clean = _clean.lstrip("json").strip()
                if "```" in _clean:
                    _clean = _clean[:_clean.rfind("```")].strip()
            print(f"[OutlineAgent] CLEAN ({len(_clean)} chars): {_clean[:200]!r}", flush=True)
            result = json.loads(_clean)
            blueprint = result.get("blueprint", [])
            distribution_summary = result.get("distribution_summary", {})

            # Debug: raw LLM output before any post-processing
            _raw_ch: dict = {}
            for _s in blueprint:
                _raw_ch[_s.get("chapter", "?")] = _raw_ch.get(_s.get("chapter", "?"), 0) + 1
            print(f"[OutlineAgent] RAW LLM: {len(blueprint)} slots, chapter_dist={_raw_ch}", flush=True)

            # ── Hard type-count enforcement BEFORE Bloom check ──────────────
            mcq_target    = int(exam_config.get("mcq_count", 40) or 0)
            essay_target  = int(exam_config.get("essay_count", 0) or 0)
            ds_target     = int(exam_config.get("dung_sai_count", 0) or 0)
            sa_target     = int(exam_config.get("short_answer_count", 0) or 0)
            _scope_for_pad = [str(s) for s in (exam_config.get("scope", []) or [])]
            blueprint = self._enforce_type_counts(
                blueprint, mcq_target, essay_target, ds_target, sa_target,
                scope_chapters=_scope_for_pad,
            )
            # Warn if LLM only returned a subset of slots (common in modification mode)
            _actual_from_llm = len(result.get("blueprint", []))
            if _actual_from_llm < (mcq_target + essay_target + ds_target + sa_target):
                logger.warning(
                    "[OutlineAgent] LLM returned only %d/%d slots — padded remainder. "
                    "Check if modification prompt is truncating output.",
                    _actual_from_llm, mcq_target + essay_target + ds_target + sa_target,
                )

            # 3B: Strict Bloom distribution enforcement
            raw_bloom = exam_config.get("bloom_distribution", {})
            total_questions = (
                int(exam_config.get("mcq_count", 0) or 0)
                + int(exam_config.get("essay_count", 0) or 0)
                + int(exam_config.get("dung_sai_count", 0) or 0)
                + int(exam_config.get("short_answer_count", 0) or 0)
            )
            expected_bloom = self._bloom_pct_to_counts(raw_bloom, total_questions)

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
                if is_modification:
                    # In modification mode, triggering a Bloom retry would override the
                    # teacher's chapter redistribution feedback. Log and continue instead.
                    warnings.append(
                        f"Bloom mismatch in modification mode (skipping retry to preserve "
                        f"teacher chapter feedback): {'; '.join(bloom_mismatch)}"
                    )
                    logger.warning(
                        "[OutlineAgent] Bloom mismatch in modification mode — "
                        "skipping Bloom retry to honor teacher chapter redistribution feedback."
                    )
                else:
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
            dung_sai_count_val = int(exam_config.get("dung_sai_count", 0) or 0)
            short_answer_count_val = int(exam_config.get("short_answer_count", 0) or 0)
            expected_total = mcq_count + essay_count + dung_sai_count_val + short_answer_count_val

            if abs(actual_total - expected_total) > 2:
                warnings.append(
                    f"Blueprint has {actual_total} questions but config expects {expected_total}"
                )

            # ── Chapter coverage + total count enforcement ──
            blueprint, warnings = self._enforce_chapter_coverage(
                blueprint=blueprint,
                exam_config=exam_config,
                mcq_count=mcq_count,
                essay_count=essay_count,
                expected_total=expected_total,
                warnings=warnings,
            )

            # ── Recompute distribution_summary from actual blueprint ──
            # Bug fix: distribution_summary was returned from LLM response (before
            # _enforce_chapter_coverage added missing chapters). Recompute now so
            # frontend sees all 9 scope chapters, not just the 6 LLM originally generated.
            _scope_raw = exam_config.get("scope", [])
            scope_chapters = [str(s) for s in (_scope_raw if isinstance(_scope_raw, list) else [])]
            bloom_dist = exam_config.get("bloom_distribution", {})
            distribution_summary = {
                "by_bloom": {level: sum(1 for s in blueprint if s.get("bloom_level") == level) for level in bloom_dist},
                "by_chapter": {
                    ch: sum(1 for s in blueprint if s.get("chapter") == ch)
                    for ch in scope_chapters
                },
            }

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
            if is_modification and exam_config.get("current_blueprint"):
                logger.warning(
                    "[OutlineAgent] JSON parse failed in modification mode — "
                    "applying deterministic chapter redistribution on current blueprint."
                )
                warnings.append("JSON parse failed — falling back to deterministic chapter redistribution")
                return await self._deterministic_redistribute(exam_config, start_time, trace_id, warnings)
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

        except Exception as e:
            warnings.append(f"Outline creation failed: {str(e)}")
            if is_modification and exam_config.get("current_blueprint"):
                logger.warning(
                    "[OutlineAgent] LLM call failed in modification mode (%s) — "
                    "applying deterministic chapter redistribution.", e
                )
                warnings.append(f"LLM call failed ({e}) — falling back to deterministic chapter redistribution")
                return await self._deterministic_redistribute(exam_config, start_time, trace_id, warnings)
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
        # Preserve original teacher chapter feedback alongside bloom correction
        original_feedback = exam_config.get("outline_feedback", "")
        if original_feedback and "LỖI PHÂN BỔ BLOOM" not in original_feedback:
            exam_config["outline_feedback"] = original_feedback + "\n\n---\n" + correction_prompt
        else:
            exam_config["outline_feedback"] = correction_prompt

        try:
            # Use MODIFICATION system prompt if we have a current blueprint to modify
            _sys_prompt = (
                self.MODIFICATION_SYSTEM_PROMPT
                if exam_config.get("current_blueprint")
                else self.OUTLINE_SYSTEM_PROMPT
            )
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": _sys_prompt},
                    {"role": "user", "content": self._build_outline_prompt(retrieved_context, exam_config)},
                ],
                role="outline",
                max_tokens=4000,
                temperature=0.2,
            )
            print(f"[OutlineAgent] RAW ({len(response)} chars): {response[:400]!r}", flush=True)
            # Strip markdown code fences before parsing (model often wraps JSON in ```json...```)
            _clean = response.strip()
            if _clean.startswith("```"):
                _clean = _clean.split("```", 2)[1] if _clean.count("```") >= 2 else _clean.split("\n", 1)[-1]
                _clean = _clean.lstrip("json").strip()
                if "```" in _clean:
                    _clean = _clean[:_clean.rfind("```")].strip()
            print(f"[OutlineAgent] CLEAN ({len(_clean)} chars): {_clean[:200]!r}", flush=True)
            result = json.loads(_clean)
            blueprint = result.get("blueprint", [])
            distribution_summary = result.get("distribution_summary", {})

            # ── Hard type-count enforcement (retry path) ─────────────────────
            _scope_retry = [str(s) for s in (exam_config.get("scope", []) or [])]
            blueprint = self._enforce_type_counts(
                blueprint,
                int(exam_config.get("mcq_count", 0) or 0),
                int(exam_config.get("essay_count", 0) or 0),
                int(exam_config.get("dung_sai_count", 0) or 0),
                int(exam_config.get("short_answer_count", 0) or 0),
                scope_chapters=_scope_retry,
            )

            # Do NOT call _redistribute_chapters here — it does even round-robin
            # which contradicts any teacher chapter-redistribution feedback.

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

        # Apply same chapter enforcement as happy path
        mcq_count = exam_config.get("mcq_count", 0)
        essay_count = exam_config.get("essay_count", 0)
        dung_sai_count = int(exam_config.get("dung_sai_count", 0) or 0)
        short_answer_count = int(exam_config.get("short_answer_count", 0) or 0)
        expected_total = mcq_count + essay_count + dung_sai_count + short_answer_count
        blueprint, warnings = self._enforce_chapter_coverage(
            blueprint=blueprint,
            exam_config=exam_config,
            mcq_count=mcq_count,
            essay_count=essay_count,
            expected_total=expected_total,
            warnings=warnings,
        )

        # Recompute distribution_summary from actual blueprint (same fix as happy path)
        _scope_raw = exam_config.get("scope", [])
        scope_chapters = [str(s) for s in (_scope_raw if isinstance(_scope_raw, list) else [])]
        bloom_dist = exam_config.get("bloom_distribution", {})
        distribution_summary = {
            "by_bloom": {level: sum(1 for s in blueprint if s.get("bloom_level") == level) for level in bloom_dist},
            "by_chapter": {
                ch: sum(1 for s in blueprint if s.get("chapter") == ch)
                for ch in scope_chapters
            },
        }

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
    async def _deterministic_redistribute(
        self,
        exam_config: dict,
        start_time: float,
        trace_id: str,
        warnings: list[str],
    ) -> "OutlineOutput":
        """
        Fallback for modification mode when LLM fails to produce valid JSON.

        Takes the current_blueprint from exam_config and redistributes its slots
        evenly across all scope chapters using _redistribute_chapters().
        This honours the teacher's intent (equal distribution) without needing
        a successful LLM call.
        """
        current_blueprint = list(exam_config.get("current_blueprint", []))
        scope = exam_config.get("scope", [])
        scope_chapters = [str(s) for s in (scope if isinstance(scope, list) else [])]

        if not current_blueprint or not scope_chapters:
            warnings.append("_deterministic_redistribute: missing blueprint or scope — using full fallback")
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

        blueprint = self._redistribute_chapters(current_blueprint, scope_chapters)
        n = len(blueprint)
        k = len(scope_chapters)
        warnings.append(
            f"Deterministic redistribution applied: {n} slots across {k} chapters "
            f"(~{n // k} per chapter, remainder {n % k})"
        )

        bloom_dist = exam_config.get("bloom_distribution", {})
        distribution_summary = {
            "by_bloom": {
                level: sum(1 for s in blueprint if s.get("bloom_level") == level)
                for level in bloom_dist
            },
            "by_chapter": {
                ch: sum(1 for s in blueprint if s.get("chapter") == ch)
                for ch in scope_chapters
            },
        }

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

    def _enforce_chapter_coverage(
        self,
        blueprint: list[dict],
        exam_config: dict,
        mcq_count: int,
        essay_count: int,
        expected_total: int,
        warnings: list[str],
    ) -> tuple[list[dict], list[str]]:
        """
        Ensure every scope chapter has ≥1 slot, and total slot count = expected_total.

        Called from both the happy path and the bloom-retry path so chapter
        coverage is enforced regardless of which LLM response path was taken.
        """
        _scope_raw = exam_config.get("scope", [])
        scope_chapters = [str(s) for s in (_scope_raw if isinstance(_scope_raw, list) else [])]

        if scope_chapters:
            chapters_in_bp = {slot.get("chapter", "") for slot in blueprint}
            missing_chapters = [ch for ch in scope_chapters if ch not in chapters_in_bp]

            if missing_chapters:
                logger.warning(
                    "Blueprint missing %d scope chapters: %s — redistributing slots",
                    len(missing_chapters), missing_chapters,
                )
                ch_counts: dict[str, int] = {}
                for slot in blueprint:
                    ch = slot.get("chapter", "")
                    ch_counts[ch] = ch_counts.get(ch, 0) + 1

                for missing_ch in missing_chapters:
                    if ch_counts:
                        donor_ch = max(ch_counts, key=lambda k: ch_counts.get(k, 0))
                        if ch_counts.get(donor_ch, 0) > 1:
                            for i in range(len(blueprint) - 1, -1, -1):
                                if blueprint[i].get("chapter") == donor_ch:
                                    old_id = blueprint[i].get("question_id", "")
                                    blueprint[i]["chapter"] = missing_ch
                                    blueprint[i]["section"] = ""
                                    blueprint[i]["topic_hint"] = f"Nội dung chương {missing_ch}"
                                    ch_counts[donor_ch] -= 1
                                    ch_counts[missing_ch] = ch_counts.get(missing_ch, 0) + 1
                                    warnings.append(
                                        f"Reassigned {old_id} from '{donor_ch}' → missing '{missing_ch}'"
                                    )
                                    break
                        else:
                            q_type = "mcq" if mcq_count > 0 else "essay"
                            new_slot = {
                                "question_id": f"{'MCQ' if q_type == 'mcq' else 'ESSAY'}_{len(blueprint)+1:03d}",
                                "type": q_type,
                                "bloom_level": "thong_hieu",
                                "chapter": missing_ch,
                                "section": "",
                                "topic_hint": f"Nội dung chương {missing_ch}",
                                "content_type": "text",
                                "estimated_difficulty": 0.4,
                            }
                            blueprint.append(new_slot)
                            ch_counts[missing_ch] = 1
                            warnings.append(f"Added extra slot for missing chapter '{missing_ch}'")

        # Pad to expected_total
        bloom_cycle = ["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"]
        while len(blueprint) < expected_total:
            ch_counts_pad: dict[str, int] = {}
            for slot in blueprint:
                ch_counts_pad[slot.get("chapter", "")] = ch_counts_pad.get(slot.get("chapter", ""), 0) + 1
            target_ch = (
                min(ch_counts_pad, key=lambda k: ch_counts_pad[k])
                if ch_counts_pad else (scope_chapters[0] if scope_chapters else "unknown")
            )
            q_type = "mcq" if mcq_count > 0 else "essay"
            pad_slot = {
                "question_id": f"{'MCQ' if q_type == 'mcq' else 'ESSAY'}_{len(blueprint)+1:03d}",
                "type": q_type,
                "bloom_level": bloom_cycle[len(blueprint) % len(bloom_cycle)],
                "chapter": target_ch,
                "section": "",
                "topic_hint": f"Nội dung chương {target_ch}",
                "content_type": "text",
                "estimated_difficulty": 0.5,
            }
            blueprint.append(pad_slot)
            warnings.append(f"Padded slot for '{target_ch}' (total={len(blueprint)})")

        # Truncate from over-represented chapter
        while len(blueprint) > expected_total:
            ch_counts_trunc: dict[str, int] = {}
            for slot in blueprint:
                ch_counts_trunc[slot.get("chapter", "")] = ch_counts_trunc.get(slot.get("chapter", ""), 0) + 1
            donor_ch = max(ch_counts_trunc, key=lambda k: ch_counts_trunc[k])
            for i in range(len(blueprint) - 1, -1, -1):
                if blueprint[i].get("chapter") == donor_ch:
                    removed = blueprint.pop(i)
                    warnings.append(f"Truncated {removed.get('question_id')} from '{donor_ch}'")
                    break

        return blueprint, warnings

    def _enforce_type_counts(
        self,
        blueprint: list[dict],
        mcq_target: int,
        essay_target: int,
        ds_target: int,
        sa_target: int,
        scope_chapters: list[str] | None = None,
    ) -> list[dict]:
        """
        Enforce exact per-type slot counts.

        Keeps exactly mcq_target MCQ slots, essay_target essay slots,
        ds_target dung_sai slots, and sa_target short_answer slots.
        Truncates excess; pads missing with correct type slots.

        Args:
            scope_chapters: If provided, padded slots will have their chapter
                assigned round-robin from this list instead of left empty,
                preventing validate_blueprint failures on missing chapter.
        """
        type_targets = {
            "mcq": mcq_target,
            "essay": essay_target,
            "dung_sai": ds_target,
            "short_answer": sa_target,
        }

        # Separate by type
        by_type: dict[str, list[dict]] = {t: [] for t in type_targets}
        for slot in blueprint:
            t = slot.get("type", "mcq")
            if t in by_type:
                by_type[t].append(slot)
            else:
                by_type["mcq"].append({**slot, "type": "mcq"})  # reclassify unknown

        result: list[dict] = []
        id_counters = {"mcq": 1, "essay": 1, "dung_sai": 1, "short_answer": 1}
        prefix_map = {"mcq": "MCQ", "essay": "ESSAY", "dung_sai": "DS", "short_answer": "SA"}
        bloom_cycle = ["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"]
        _pad_chapter_pool = scope_chapters if scope_chapters else []

        for q_type, target in type_targets.items():
            if target <= 0:
                continue
            slots = by_type[q_type][:target]  # truncate excess
            # Pad missing slots
            while len(slots) < target:
                idx = len(slots)
                # Use scope_chapters round-robin so chapter is never empty
                fallback_chapter = (
                    _pad_chapter_pool[idx % len(_pad_chapter_pool)]
                    if _pad_chapter_pool else ""
                )
                slots.append({
                    "question_id": f"{prefix_map[q_type]}_{id_counters[q_type]:03d}",
                    "type": q_type,
                    "bloom_level": bloom_cycle[idx % len(bloom_cycle)],
                    "chapter": fallback_chapter,
                    "section": "",
                    "topic_hint": f"Câu hỏi mức {bloom_cycle[idx % len(bloom_cycle)]}",
                    "content_type": "calculation" if q_type in ("short_answer", "dung_sai") else "text",
                    "estimated_difficulty": 0.5,
                })
                id_counters[q_type] += 1
            # Renumber IDs for consistency
            for i, slot in enumerate(slots):
                slot["question_id"] = f"{prefix_map[q_type]}_{i+1:03d}"
            result.extend(slots)

        return result

    def _redistribute_chapters(
        self,
        blueprint: list[dict],
        scope_chapters: list[str],
    ) -> list[dict]:
        """
        Evenly redistribute chapter labels across the blueprint using
        interleaved (true round-robin) assignment.

        Called when teacher rejects with feedback — LLM can't override
        chapter bias from context density, so we do it deterministically.

        Uses interleaved round-robin: [Ch1,Ch2,Ch3,Ch4,Ch1,Ch2,...] so that
        bloom levels spread evenly across all chapters rather than being
        grouped by chapter in blocks (old: [Ch1×7, Ch2×7, ...]).

        Preserves all other slot fields (bloom_level, type, topic_hint, etc.).
        """
        if not scope_chapters or not blueprint:
            return blueprint

        n = len(blueprint)
        k = len(scope_chapters)

        # Build interleaved chapter assignment (true round-robin).
        # Each position i gets scope_chapters[i % k], which interleaves chapters
        # so consecutive slots always cycle through all chapters.
        # This ensures bloom levels (which are grouped by type in the input)
        # are spread across chapters rather than stacked in chapter blocks.
        result = []
        for i, slot in enumerate(blueprint):
            slot = dict(slot)
            slot["chapter"] = scope_chapters[i % k]
            # Clear section since chapter changed
            slot["section"] = ""
            result.append(slot)

        return result

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
        essay_count = exam_config.get("essay_count", 0)
        dung_sai_count = exam_config.get("dung_sai_count", 0)
        short_answer_count = exam_config.get("short_answer_count", 0)
        bloom_dist = exam_config.get("bloom_distribution", {})
        user_prompt = exam_config.get("user_prompt", "")
        extra_instructions = exam_config.get("extra_instructions", "")
        outline_feedback = exam_config.get("outline_feedback", "")
        current_blueprint = exam_config.get("current_blueprint", [])

        feedback_section = ""
        if outline_feedback:
            feedback_section = f"""
## Phản hồi từ giảng viên (HITL):
{outline_feedback}

Hãy điều chỉnh blueprint theo phản hồi trên.
"""

        total_questions = mcq_count + essay_count + dung_sai_count + short_answer_count
        bloom_counts = self._bloom_pct_to_counts(bloom_dist, total_questions)

        type_breakdown = f"- MCQ (trắc nghiệm 4 lựa chọn): {mcq_count} câu"
        if essay_count:
            type_breakdown += f"\n- Essay (tự luận): {essay_count} câu"
        if dung_sai_count:
            type_breakdown += f"\n- Đúng-Sai (4 mệnh đề a/b/c/d, type='dung_sai'): {dung_sai_count} câu"
        if short_answer_count:
            type_breakdown += f"\n- Trả lời ngắn (điền số, type='short_answer'): {short_answer_count} câu"

        # If teacher rejected and provided feedback + current blueprint
        # → switch to MODIFICATION mode so LLM understands what to change
        if outline_feedback and current_blueprint:
            print(f"[OutlineAgent] MODIFICATION MODE: feedback='{outline_feedback[:60]}', blueprint_len={len(current_blueprint)}", flush=True)
            # Compact blueprint for readability (only key fields)
            compact_bp = [
                {
                    "question_id": s.get("question_id"),
                    "type": s.get("type", "mcq"),
                    "bloom_level": s.get("bloom_level"),
                    "chapter": s.get("chapter"),
                    "topic_hint": s.get("topic_hint", ""),
                }
                for s in current_blueprint
            ]
            current_dist = {}
            for s in current_blueprint:
                ch = s.get("chapter", "?")
                current_dist[ch] = current_dist.get(ch, 0) + 1

            return f"""Bạn là chuyên gia thiết kế đề thi. Nhiệm vụ là CHỈNH SỬA blueprint dưới đây theo đúng phản hồi của giáo viên.

## BLUEPRINT HIỆN TẠI (cần chỉnh sửa):
Phân bổ theo chương hiện tại: {json.dumps(current_dist, ensure_ascii=False)}
Tổng số slot: {len(compact_bp)}

Chi tiết blueprint:
{json.dumps(compact_bp, ensure_ascii=False, indent=2)}

## PHẢN HỒI CỦA GIÁO VIÊN (BẮT BUỘC TUÂN THEO):
{outline_feedback}

## HƯỚNG DẪN THỰC HIỆN (suy luận trước khi output):
Tổng số câu = {total_questions}.
- Nếu phản hồi đề cập đến % cho nhóm chương, hãy tính số câu cụ thể:
  VD "60% chương 3, 4" → {round(total_questions * 0.6)} câu cho chương 3 và 4 cộng lại
- Chỉ thay đổi field "chapter" (và "section", "topic_hint") của mỗi slot
- Giữ nguyên "bloom_level" và "type" của từng slot để tổng bloom không thay đổi
- Ghi rõ số câu mục tiêu mỗi chương TRƯỚC khi viết JSON

## ⚠️ RÀNG BUỘC TUYỆT ĐỐI:
- OUTPUT PHẢI CÓ ĐỦ {total_questions} SLOT — không được thiếu bất kỳ câu nào
- Mỗi slot trong input PHẢI xuất hiện trong output (chỉ thay đổi chapter/section/topic_hint)
- TỔNG SỐ CÂU: {total_questions} ({type_breakdown.replace(chr(10), ', ')})
- Phân bổ Bloom (số câu chính xác): {json.dumps(bloom_counts, ensure_ascii=False)}
- Phạm vi (scope): {json.dumps(scope, ensure_ascii=False)}
- Mỗi chương phải có ít nhất 1 câu

Trả về JSON theo đúng format (KHÔNG thêm markdown, chỉ JSON thuần):
{{"blueprint": [<TOÀN BỘ {total_questions} slot đã chỉnh sửa>], "distribution_summary": {{"by_bloom": {{}}, "by_chapter": {{}}}}}}"""

        print(f"[OutlineAgent] CREATION MODE: outline_feedback={bool(outline_feedback)}, has_blueprint={bool(current_blueprint)}", flush=True)
        # Build feedback block for creation mode
        feedback_block = ""
        if outline_feedback:
            feedback_block = f"""
⚠️ PHẢN HỒI BẮT BUỘC PHẢI TUÂN THEO (HITL Rejection Feedback):
═══════════════════════════════════════════════════════════════
{outline_feedback}
═══════════════════════════════════════════════════════════════
Blueprint trước đã bị từ chối. Mày PHẢI điều chỉnh phân bổ chapter/bloom
theo phản hồi trên trước khi làm bất cứ điều gì khác.

"""

        prompt = f"""{feedback_block}Tạo sườn đề kiểm tra với cấu hình sau:

## Phạm vi (scope):
{json.dumps(scope, ensure_ascii=False)}

## Cấu hình đề:
{type_breakdown}
- TỔNG SỐ CÂU: {total_questions}
- **MỖI CHƯƠNG trong scope PHẢI có ít nhất 1 câu hỏi** (bắt buộc)
- Phân bổ Bloom (SỐ LƯỢNG CÂU, KHÔNG PHẢI %):
{json.dumps(bloom_counts, ensure_ascii=False, indent=2)}

## Kiến thức đã truy xuất:
{self._build_context_summary(retrieved_context)}

## Yêu cầu từ giảng viên:
{user_prompt or "Không có yêu cầu đặc biệt."}

## Hướng dẫn bổ sung:
{extra_instructions or "Sinh câu hỏi chuẩn mực, phù hợp với chương trình phổ thông Việt Nam."}

Tạo blueprint chi tiết:"""

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
        valid_types = {"mcq", "essay", "dung_sai", "short_answer"}

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
            slot_type = slot.get("type", "mcq")
            if slot_type not in valid_types:
                return False, (
                    f"Blueprint[{i}] type '{slot_type}' is not valid "
                    f"(expected one of {valid_types})"
                )

        return True, ""

    @staticmethod
    def _bloom_pct_to_counts(bloom_dist: dict, total_questions: int) -> dict[str, int]:
        """
        Convert bloom_distribution percentages to absolute question counts.

        Uses largest-remainder method so counts sum to exactly total_questions.
        Example: {"nhan_biet": 25, ...} with total=20 → {"nhan_biet": 5, ...}
        """
        if not bloom_dist or total_questions <= 0:
            return bloom_dist

        # Check if values are already counts (sum != 100)
        total_pct = sum(bloom_dist.values())
        if total_pct != 100:
            # Already counts, not percentages
            return bloom_dist

        # Largest-remainder method for exact allocation
        raw = {k: v * total_questions / 100 for k, v in bloom_dist.items()}
        floors = {k: int(v) for k, v in raw.items()}
        remainders = {k: raw[k] - floors[k] for k in raw}
        allocated = sum(floors.values())
        deficit = total_questions - allocated

        # Distribute remaining slots to levels with largest remainders
        for k in sorted(remainders, key=remainders.get, reverse=True):
            if deficit <= 0:
                break
            floors[k] += 1
            deficit -= 1

        return floors

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
        essay_count = exam_config.get("essay_count", 0)
        dung_sai_count = exam_config.get("dung_sai_count", 0)
        short_answer_count = exam_config.get("short_answer_count", 0)
        bloom_dist = exam_config.get("bloom_distribution", {
            "nhan_biet": 20, "thong_hieu": 30, "van_dung": 30, "van_dung_cao": 20
        })

        total_questions = mcq_count + essay_count + dung_sai_count + short_answer_count
        bloom_counts = self._bloom_pct_to_counts(bloom_dist, total_questions)
        bloom_levels = list(bloom_counts.keys())
        chapters = scope if scope else ["Chương 1"]
        diff_map = {"nhan_biet": 0.2, "thong_hieu": 0.4, "van_dung": 0.6, "van_dung_cao": 0.85}

        blueprint = []
        mcq_id = essay_id = ds_id = sa_id = 1

        # Allocate MCQ slots round-robin across bloom levels
        mcq_bloom = self._bloom_pct_to_counts(bloom_dist, mcq_count)
        for bloom in bloom_levels:
            for i in range(mcq_bloom.get(bloom, 0)):
                chapter = chapters[i % len(chapters)]
                blueprint.append({
                    "question_id": f"MCQ_{mcq_id:03d}",
                    "type": "mcq",
                    "bloom_level": bloom,
                    "chapter": chapter,
                    "section": None,
                    "topic_hint": f"Câu hỏi mức {bloom}",
                    "content_type": "calculation" if bloom in ["van_dung", "van_dung_cao"] else "text",
                    "estimated_difficulty": diff_map.get(bloom, 0.5),
                })
                mcq_id += 1

        # Essay slots
        for i in range(essay_count):
            blueprint.append({
                "question_id": f"ESSAY_{essay_id:03d}",
                "type": "essay",
                "bloom_level": "van_dung",
                "chapter": chapters[i % len(chapters)],
                "section": None,
                "topic_hint": "Câu tự luận vận dụng",
                "content_type": "applied_problem",
                "estimated_difficulty": 0.7,
            })
            essay_id += 1

        # Đúng-Sai slots (THPT 2025)
        ds_bloom = self._bloom_pct_to_counts(bloom_dist, dung_sai_count)
        for bloom in bloom_levels:
            for i in range(ds_bloom.get(bloom, 0)):
                blueprint.append({
                    "question_id": f"DS_{ds_id:03d}",
                    "type": "dung_sai",
                    "bloom_level": bloom,
                    "chapter": chapters[i % len(chapters)],
                    "section": None,
                    "topic_hint": f"Câu đúng-sai mức {bloom}",
                    "content_type": "conceptual",
                    "estimated_difficulty": diff_map.get(bloom, 0.5),
                })
                ds_id += 1

        # Short-Answer slots (THPT 2025)
        sa_bloom = self._bloom_pct_to_counts(bloom_dist, short_answer_count)
        for bloom in bloom_levels:
            for i in range(sa_bloom.get(bloom, 0)):
                blueprint.append({
                    "question_id": f"SA_{sa_id:03d}",
                    "type": "short_answer",
                    "bloom_level": bloom,
                    "chapter": chapters[i % len(chapters)],
                    "section": None,
                    "topic_hint": f"Câu trả lời ngắn mức {bloom}",
                    "content_type": "calculation",
                    "estimated_difficulty": diff_map.get(bloom, 0.6),
                })
                sa_id += 1

        distribution_summary = {
            "by_bloom": {level: sum(1 for s in blueprint if s.get("bloom_level") == level) for level in bloom_levels},
            "by_chapter": {ch: sum(1 for s in blueprint if s.get("chapter") == ch) for ch in chapters},
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
