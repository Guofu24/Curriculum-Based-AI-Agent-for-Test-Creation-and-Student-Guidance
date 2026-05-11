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

# Fallback topic_hint templates per Bloom level (used when LLM outline fails or pads slots)
BLOOM_HINT_TEMPLATE = {
    "nhan_biet":   "Nhận biết và định nghĩa các khái niệm cơ bản trong chương.",
    "thong_hieu":  "Giải thích hiện tượng, minh họa hoặc áp dụng công thức 1 bước. Dạng: 'Định nghĩa X là gì', 'Đơn vị của Y', 'Phát biểu định luật Z'.",
    "van_dung":    "Bài toán tính toán 2-3 bước, có điều kiện ràng buộc, áp dụng công thức và logic giải thích, cần tính ẩn số trung gian trước khi ra kết quả.",
    "van_dung_cao":"Bài toán phức hợp kết hợp nhiều định luật, phân tích hệ thống và giải quyết vấn đề tổng hợp.",
}

settings = get_settings()
tracer = get_tracer()
logger = logging.getLogger("app.agents.outline")




def _norm_text(s: str) -> str:
    """Normalize Vietnamese text: lowercase + strip diacritics."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", s.strip().lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _get_scope_chapters(exam_config: dict) -> list[str]:
    """Return unique chapter names for comparison with slot['chapter'].

    Priority:
    1. scope_units[*].chapter_title — canonical titles the LLM uses
    2. Fallback: split raw scope strings on ' > ' to strip section suffix
    """
    scope_units = exam_config.get("scope_units") or []
    if scope_units:
        seen: list[str] = []
        seen_set: set[str] = set()
        for u in scope_units:
            ch = (u.get("chapter_title") or u.get("chapter") or "").strip()
            if ch and ch not in seen_set:
                seen.append(ch)
                seen_set.add(ch)
        if seen:
            return seen

    scope_raw = exam_config.get("scope", [])
    chapters: list[str] = []
    seen_fb: set[str] = set()
    for s in (scope_raw if isinstance(scope_raw, list) else []):
        ch = str(s).split(" > ")[0].strip()
        if ch and ch not in seen_fb:
            chapters.append(ch)
            seen_fb.add(ch)
    return chapters


def _assign_blueprint_indices(blueprint: list[dict]) -> list[dict]:
    """Store the approved slot order explicitly for builder/retry/export."""
    for idx, slot in enumerate(blueprint, start=1):
        slot["blueprint_index"] = idx
    return blueprint


def _normalize_section_fields(
    blueprint: list[dict],
    scope_units: list[dict],
) -> list[dict]:
    """Deterministic post-process: fill/correct section metadata on every blueprint slot.

    No LLM calls. Rules:
    - Only units with section_title are valid section targets.
    - Chapter-level units (scope_unit_key starts with __ch__) are never assigned as primary.
    - primary resolved: section_id -> scope_unit_key -> chapter round-robin -> global fallback
    - legacy slot["section"] = primary_section_title for builder/UI backward compat
    - secondary filtered to valid keys, self removed, Bloom-capped (NB/TH=0, VD=1, VDC=2)
    - All titles rebuilt from lookup (never trust LLM strings)
    - No-op when scope_units empty or no section-level units.
    """
    sec_units = [u for u in scope_units if u.get("section_title")]
    if not sec_units:
        return blueprint

    key_lookup: dict[str, dict] = {
        u["scope_unit_key"]: u for u in sec_units
        if not u["scope_unit_key"].startswith("__ch__")
    }
    sec_id_lookup: dict[str, dict] = {
        u["section_id"]: u for u in sec_units if u.get("section_id")
    }
    ch_id_units: dict[str, list] = {}
    ch_title_units: dict[str, list] = {}
    for u in sec_units:
        if u.get("chapter_id"):
            ch_id_units.setdefault(u["chapter_id"], []).append(u)
        if u.get("chapter_title"):
            ch_title_units.setdefault(_norm_text(u["chapter_title"]), []).append(u)
    all_section_units = sec_units[:]
    rr_counter: dict[str, int] = {}

    def _resolve_unit(slot: dict) -> dict | None:
        sid = slot.get("primary_section_id") or ""
        if sid and sid in sec_id_lookup:
            return sec_id_lookup[sid]
        key = slot.get("primary_scope_unit_key") or ""
        if key and key in key_lookup:
            return key_lookup[key]
        ch_id = slot.get("chapter", "")
        units = ch_id_units.get(ch_id) or ch_title_units.get(_norm_text(ch_id))
        if not units:
            units = all_section_units
        if not units:
            return None
        rr_key = ch_id or "__global__"
        idx = rr_counter.get(rr_key, 0)
        rr_counter[rr_key] = idx + 1
        return units[idx % len(units)]

    bloom_secondary_cap = {
        "nhan_biet": 0, "thong_hieu": 0, "van_dung": 1, "van_dung_cao": 2,
    }

    for slot in blueprint:
        unit = _resolve_unit(slot)
        if unit is None:
            continue
        slot["primary_section_id"] = unit.get("section_id")
        slot["primary_section_title"] = unit.get("section_title", "")
        slot["primary_scope_unit_key"] = unit.get("scope_unit_key", "")
        slot["section"] = unit.get("section_title", "")  # legacy compat

        raw_sec_keys: list[str] = list(slot.get("secondary_scope_unit_keys") or [])
        for sid2 in (slot.get("secondary_section_ids") or []):
            u2 = sec_id_lookup.get(sid2)
            if u2:
                raw_sec_keys.append(u2["scope_unit_key"])
        primary_key = slot["primary_scope_unit_key"]
        valid_sec_keys = [
            k for k in dict.fromkeys(raw_sec_keys)
            if k in key_lookup and k != primary_key
        ]
        cap = bloom_secondary_cap.get(slot.get("bloom_level", ""), 0)
        valid_sec_keys = valid_sec_keys[:cap]
        sec_resolved = [key_lookup[k] for k in valid_sec_keys if k in key_lookup]
        slot["secondary_scope_unit_keys"] = [u["scope_unit_key"] for u in sec_resolved]
        slot["secondary_section_ids"] = [u["section_id"] for u in sec_resolved if u.get("section_id")]
        slot["secondary_section_titles"] = [u["section_title"] for u in sec_resolved if u.get("section_title")]

    return blueprint


SECTION_METADATA_FIELDS = (
    "section",
    "primary_section_id",
    "primary_section_title",
    "primary_scope_unit_key",
    "secondary_section_ids",
    "secondary_section_titles",
    "secondary_scope_unit_keys",
)


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _restore_modification_slot_metadata(
    blueprint: list[dict],
    current_blueprint: list[dict],
) -> dict[str, int]:
    """Restore locked and section metadata after LLM blueprint modification.

    The modification prompt lets the LLM change chapter/section/topic_hint, but
    it must not lose type/Bloom or silently drop section metadata. Section fields
    are restored only when the slot stays in the same chapter to avoid carrying a
    section from the wrong chapter after a deliberate redistribution.
    """
    orig_map: dict[str, dict] = {
        str(s.get("question_id") or ""): s
        for s in current_blueprint
        if s.get("question_id")
    }
    restored = {"bloom": 0, "type": 0, "section": 0}

    for slot in blueprint:
        qid = str(slot.get("question_id") or "")
        orig = orig_map.get(qid)
        if not orig:
            continue

        if slot.get("bloom_level") != orig.get("bloom_level"):
            slot["bloom_level"] = orig.get("bloom_level")
            restored["bloom"] += 1
        if slot.get("type") != orig.get("type"):
            slot["type"] = orig.get("type")
            restored["type"] += 1

        if not _has_value(slot.get("section")) and _has_value(slot.get("primary_section_title")):
            slot["section"] = slot["primary_section_title"]
            restored["section"] += 1

        slot_chapter = str(slot.get("chapter") or "")
        orig_chapter = str(orig.get("chapter") or "")
        same_chapter = (
            not slot_chapter
            or not orig_chapter
            or _norm_text(slot_chapter) == _norm_text(orig_chapter)
        )
        if not same_chapter:
            continue

        for field in SECTION_METADATA_FIELDS:
            if _has_value(slot.get(field)):
                continue
            orig_value = orig.get(field)
            if _has_value(orig_value):
                slot[field] = orig_value
                restored["section"] += 1

        if not _has_value(slot.get("section")) and _has_value(slot.get("primary_section_title")):
            slot["section"] = slot["primary_section_title"]
            restored["section"] += 1

    return restored


def _section_scope_key(chapter: str, section: str, section_id: str | None = None) -> str:
    if section_id:
        return section_id
    return f"__sec__{_norm_text(chapter)}>{_norm_text(section)}"


def _chapter_compatible(slot_chapter: str, unit: dict) -> bool:
    """Return True when a section unit belongs to the slot chapter."""
    if not slot_chapter:
        return True
    slot_norm = _norm_text(slot_chapter)
    candidates = [
        str(unit.get("chapter_title") or ""),
        str(unit.get("chapter_id") or ""),
    ]
    for candidate in candidates:
        cand_norm = _norm_text(candidate)
        if not cand_norm:
            continue
        if slot_norm == cand_norm or slot_norm in cand_norm or cand_norm in slot_norm:
            return True

    import re as _re
    slot_nums = _re.findall(r"\d+", slot_norm)
    if not slot_nums:
        return False
    for candidate in candidates:
        cand_nums = _re.findall(r"\d+", _norm_text(candidate))
        if cand_nums and cand_nums[0] == slot_nums[0]:
            return True
    return False


def _build_section_registry(
    scope_units: list[dict] | None,
    retrieved_context: list[dict] | None = None,
) -> list[dict]:
    """Build canonical section units from scope metadata and retrieved chunks."""
    registry: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(
        *,
        chapter_title: str,
        section_title: str,
        chapter_id: str | None = None,
        section_id: str | None = None,
        scope_unit_key: str | None = None,
        source: str,
    ) -> None:
        chapter_title = (chapter_title or "").strip()
        section_title = (section_title or "").strip()
        chapter_id = (chapter_id or "").strip() or None
        section_id = (section_id or "").strip() or None
        if not chapter_title or not section_title:
            return
        key = scope_unit_key or _section_scope_key(chapter_title, section_title, section_id)
        dedupe_key = (
            section_id or "",
            _norm_text(chapter_title),
            _norm_text(section_title),
        )
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        registry.append({
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "section_id": section_id,
            "section_title": section_title,
            "scope_unit_key": key,
            "source": source,
        })

    for unit in scope_units or []:
        section_title = unit.get("section_title") or unit.get("section") or ""
        if not section_title:
            continue
        key = unit.get("scope_unit_key") or unit.get("section_id")
        _add(
            chapter_title=unit.get("chapter_title") or unit.get("chapter") or unit.get("chapter_id") or "",
            chapter_id=unit.get("chapter_id"),
            section_title=section_title,
            section_id=unit.get("section_id"),
            scope_unit_key=key,
            source="scope_units",
        )

    for chunk in retrieved_context or []:
        meta = chunk.get("metadata") or {}
        chapter_title = chunk.get("chapter") or meta.get("chapter") or ""
        section_title = (
            chunk.get("section")
            or meta.get("section")
            or meta.get("title")
            or ""
        )
        _add(
            chapter_title=chapter_title,
            chapter_id=chunk.get("chapter_id") or meta.get("chapter_id") or chapter_title,
            section_title=section_title,
            section_id=chunk.get("section_id") or meta.get("section_id"),
            source="retrieved_context",
        )

    return registry


def _canonicalize_section_metadata(
    blueprint: list[dict],
    exam_config: dict,
    retrieved_context: list[dict] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Resolve section metadata after LLM edits.

    The LLM chooses chapter/section. This function canonicalizes that choice to
    the exact metadata BuilderAgent uses for section-level retrieval.
    """
    registry = _build_section_registry(
        list(exam_config.get("scope_units") or []) + list(exam_config.get("section_registry") or []),
        retrieved_context,
    )
    if not registry:
        return _normalize_section_fields(blueprint, exam_config.get("scope_units") or []), {
            "resolved": 0,
            "fallback": 0,
            "unresolved": len(blueprint),
        }

    key_lookup = {u["scope_unit_key"]: u for u in registry if u.get("scope_unit_key")}
    id_lookup = {u["section_id"]: u for u in registry if u.get("section_id")}
    counts = {"resolved": 0, "fallback": 0, "unresolved": 0}
    rr_counter: dict[str, int] = {}

    def _title_match(section_text: str, unit: dict) -> bool:
        if not section_text:
            return False
        want = _norm_text(section_text)
        got = _norm_text(str(unit.get("section_title") or ""))
        return bool(want and got and (want == got or want in got or got in want))

    def _chapter_units(chapter: str) -> list[dict]:
        return [u for u in registry if _chapter_compatible(chapter, u)]

    def _pick_unit(slot: dict) -> tuple[dict | None, bool]:
        chapter = str(slot.get("chapter") or "")

        key = slot.get("primary_scope_unit_key") or ""
        unit = key_lookup.get(key)
        if unit and _chapter_compatible(chapter, unit):
            return unit, False

        sec_id = slot.get("primary_section_id") or slot.get("section_id") or ""
        unit = id_lookup.get(sec_id)
        if unit and _chapter_compatible(chapter, unit):
            return unit, False

        section_text = (
            slot.get("primary_section_title")
            or slot.get("section")
            or ""
        )
        units_in_chapter = _chapter_units(chapter)
        search_space = units_in_chapter or registry
        for candidate in search_space:
            if _title_match(section_text, candidate):
                return candidate, False

        if units_in_chapter:
            ch_key = _norm_text(chapter) or "__global__"
            idx = rr_counter.get(ch_key, 0)
            rr_counter[ch_key] = idx + 1
            return units_in_chapter[idx % len(units_in_chapter)], True

        return None, False

    def _apply_unit(slot: dict, unit: dict) -> None:
        slot["chapter"] = unit.get("chapter_title") or slot.get("chapter", "")
        slot["section"] = unit.get("section_title", "")
        slot["primary_section_title"] = unit.get("section_title", "")
        slot["primary_scope_unit_key"] = unit.get("scope_unit_key", "")
        slot["primary_section_id"] = unit.get("section_id") or None

        primary_key = slot.get("primary_scope_unit_key")
        secondary_keys = []
        for raw_key in slot.get("secondary_scope_unit_keys") or []:
            if raw_key in key_lookup and raw_key != primary_key:
                secondary_keys.append(raw_key)
        for raw_id in slot.get("secondary_section_ids") or []:
            sec_unit = id_lookup.get(raw_id)
            if sec_unit and sec_unit.get("scope_unit_key") != primary_key:
                secondary_keys.append(sec_unit["scope_unit_key"])
        secondary_keys = list(dict.fromkeys(secondary_keys))
        secondary_units = [key_lookup[k] for k in secondary_keys if k in key_lookup]
        slot["secondary_scope_unit_keys"] = [u["scope_unit_key"] for u in secondary_units]
        slot["secondary_section_ids"] = [
            u["section_id"] for u in secondary_units if u.get("section_id")
        ]
        slot["secondary_section_titles"] = [
            u["section_title"] for u in secondary_units if u.get("section_title")
        ]

    for slot in blueprint:
        unit, fallback = _pick_unit(slot)
        if unit:
            _apply_unit(slot, unit)
            counts["fallback" if fallback else "resolved"] += 1
        else:
            counts["unresolved"] += 1

    if counts["fallback"] or counts["unresolved"]:
        logger.warning(
            "[OutlineAgent] section metadata canonicalization: resolved=%d fallback=%d unresolved=%d",
            counts["resolved"],
            counts["fallback"],
            counts["unresolved"],
        )

    return blueprint, counts


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

## Internal planning only (KHÔNG output)
Suy nghĩ nội bộ theo các bước này, nhưng KHÔNG viết chain-of-thought, reasoning, analysis, planning, hoặc self-check ra response:
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
Chỉ trả về JSON thuần. Không markdown. Không giải thích. Không chain-of-thought.
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
- Không được làm mất section metadata đã có: "section", "primary_section_id", "primary_section_title", "primary_scope_unit_key", "secondary_section_ids", "secondary_section_titles", "secondary_scope_unit_keys"
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

## Output discipline
Think privately; do NOT output chain-of-thought, reasoning, analysis, planning, or self-check text.
Chỉ trả về JSON thuần. Không markdown. Không giải thích trước/sau JSON.

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
            section_registry = _build_section_registry(
                exam_config.get("scope_units") or [],
                retrieved_context,
            )
            if section_registry:
                exam_config["section_registry"] = section_registry
                logger.info(
                    "[OutlineAgent] section registry built: %d units",
                    len(section_registry),
                )

            # Build user prompt
            user_prompt = self._build_outline_prompt(retrieved_context, exam_config)

            # Choose system prompt based on mode
            system_prompt = (
                self.MODIFICATION_SYSTEM_PROMPT if is_modification
                else self.OUTLINE_SYSTEM_PROMPT
            )

            # Modification mode needs higher token limit:
            # 28 slots × ~200 chars/slot ≈ 5600 chars + distribution_summary overhead
            _max_tokens = 20000 if is_modification else 20000

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

            # Extract token usage if LLM client returns metadata alongside text
            # llm.chat() may return a plain str or a response object with .usage
            if not isinstance(response, str):
                _usage = getattr(response, "usage", None)
                if _usage:
                    metrics.prompt_tokens = int(getattr(_usage, "prompt_tokens", 0) or 0)
                    metrics.completion_tokens = int(getattr(_usage, "completion_tokens", 0) or 0)
                response = getattr(response, "text", None) or str(response)

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

            # ── Modification mode: restore bloom_level + type from current_blueprint ──
            # The LLM is only allowed to change chapter/section/topic_hint.
            # Bloom and type must stay exactly as in the original blueprint.
            if is_modification:
                _restore_counts = _restore_modification_slot_metadata(
                    blueprint,
                    exam_config.get("current_blueprint") or [],
                )
                if _restore_counts["bloom"]:
                    print(f"[OutlineAgent] BLOOM LOCK: reverted bloom_level for {_restore_counts['bloom']} slots", flush=True)
                if _restore_counts["section"]:
                    logger.info(
                        "[OutlineAgent] SECTION LOCK: restored %d missing section metadata fields",
                        _restore_counts["section"],
                    )

            # ── Hard type-count enforcement BEFORE Bloom check ──────────────
            mcq_target    = int(exam_config.get("mcq_count", 40) or 0)
            essay_target  = int(exam_config.get("essay_count", 0) or 0)
            ds_target     = int(exam_config.get("dung_sai_count", 0) or 0)
            sa_target     = int(exam_config.get("short_answer_count", 0) or 0)
            _scope_for_pad = _get_scope_chapters(exam_config)

            # In modification mode, capture the chapter distribution from LLM output
            # BEFORE enforcement so we can use it when padding missing slots.
            # This preserves the teacher's feedback-driven chapter redistribution.
            _llm_chapter_dist: dict[str, int] | None = None
            if is_modification and blueprint:
                _llm_chapter_dist = {}
                for _s in blueprint:
                    _ch = _s.get("chapter", "")
                    _llm_chapter_dist[_ch] = _llm_chapter_dist.get(_ch, 0) + 1

            blueprint = self._enforce_type_counts(
                blueprint, mcq_target, essay_target, ds_target, sa_target,
                scope_chapters=_scope_for_pad,
                llm_chapter_dist=_llm_chapter_dist,
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

            # ── Derive expected totals from config (consistent with _enforce_type_counts) ──
            mcq_count = int(exam_config.get("mcq_count", 0) or 0)
            essay_count = int(exam_config.get("essay_count", 0) or 0)
            dung_sai_count_val = int(exam_config.get("dung_sai_count", 0) or 0)
            short_answer_count_val = int(exam_config.get("short_answer_count", 0) or 0)
            expected_total = mcq_count + essay_count + dung_sai_count_val + short_answer_count_val
            actual_total = len(blueprint)

            logger.info(
                "[OUTLINE AGENT] exam_type=%s mcq=%d essay=%d ds=%d sa=%d | "
                "blueprint_slots=%d expected=%d",
                exam_config.get("exam_type"), mcq_count, essay_count,
                dung_sai_count_val, short_answer_count_val,
                actual_total, expected_total,
            )

            if actual_total != expected_total:
                warnings.append(
                    f"Blueprint slot count mismatch after enforcement: "
                    f"{actual_total} slots but config expects {expected_total}"
                )

            # ── Chapter coverage + total count enforcement ──
            # SKIP in modification mode when the LLM already returned exactly the
            # right total — _enforce_chapter_coverage redistributes chapters
            # blindly and would undo the feedback-driven chapter distribution the
            # LLM applied.
            _total_after_enforce = len(blueprint)
            _skip_chapter_enforce = (
                is_modification
                and _total_after_enforce == expected_total
                and all(
                    any(s.get("chapter") == ch for s in blueprint)
                    for ch in _get_scope_chapters(exam_config)
                )
            )
            if _skip_chapter_enforce:
                logger.info(
                    "[OutlineAgent] Modification mode: skipping _enforce_chapter_coverage "
                    "— LLM already produced correct total (%d) and all scope chapters present.",
                    _total_after_enforce,
                )
            else:
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
            scope_chapters = _get_scope_chapters(exam_config)
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

            blueprint, section_counts = _canonicalize_section_metadata(
                blueprint,
                exam_config,
                retrieved_context,
            )
            if section_counts["unresolved"]:
                warnings.append(
                    f"Section metadata unresolved for {section_counts['unresolved']} blueprint slots"
                )
            blueprint = _assign_blueprint_indices(blueprint)
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
                # Attempt partial JSON recovery from truncated output
                _recovered = self._recover_partial_slots(_clean)
                if _recovered:
                    logger.warning(
                        "[OutlineAgent] JSON parse failed but recovered %d/%d slots from partial output.",
                        len(_recovered), len(exam_config.get("current_blueprint", []))
                    )
                    warnings.append(f"Partial JSON recovery: salvaged {len(_recovered)} slots")
                    # Merge recovered slots with original blueprint
                    _orig_bp = list(exam_config.get("current_blueprint", []))
                    _recovered_ids = {s.get("question_id") for s in _recovered}
                    # Keep recovered slots, fill missing from orig (updated chapter = orig chapter for non-recovered)
                    merged_slots = list(_recovered)
                    for orig_slot in _orig_bp:
                        if orig_slot.get("question_id") not in _recovered_ids:
                            merged_slots.append(orig_slot)
                    # Temporarily inject merged blueprint and recurse with same config
                    try:
                        _clean_merged = json.dumps({"blueprint": merged_slots, "distribution_summary": {}})
                        result_merged = json.loads(_clean_merged)
                        blueprint = result_merged.get("blueprint", [])
                        # Restore locked fields and any section metadata omitted by partial JSON.
                        _restore_modification_slot_metadata(blueprint, _orig_bp)
                        # Continue with this blueprint (fall through to enforcement)
                        is_partial_recovery = True
                        distribution_summary = {}
                    except Exception:
                        is_partial_recovery = False
                        blueprint = []

                    _orig_count = len(exam_config.get("current_blueprint") or [])
                    _recovery_ratio = len(_recovered) / max(_orig_count, 1)
                    if not is_partial_recovery or not blueprint or _recovery_ratio < 0.5:
                        logger.warning(
                            "[OutlineAgent] JSON parse failed in modification mode "
                            "(recovered %d/%d slots = %.0f%%) — retrying LLM with truncation warning.",
                            len(_recovered), _orig_count, _recovery_ratio * 100,
                        )
                        # ── Retry once with explicit "output ALL slots" instruction ──
                        _retry_config = dict(exam_config)
                        _orig_fb = _retry_config.get("outline_feedback", "")
                        _retry_config["outline_feedback"] = (
                            f"{_orig_fb}\n\n"
                            f"[LỖI KỸ THUẬT] Lần trước bạn chỉ output {len(_recovered)}/{_orig_count} slot "
                            f"do bị cắt ngắn. Lần này BẮT BUỘC phải output ĐỦ {_orig_count} slot "
                            f"trong JSON. Không được dừng giữa chừng."
                        )
                        try:
                            _retry_resp = await self.llm.chat(
                                messages=[
                                    {"role": "system", "content": self.MODIFICATION_SYSTEM_PROMPT},
                                    {"role": "user", "content": self._build_outline_prompt(
                                        retrieved_context, _retry_config
                                    )},
                                ],
                                role="outline",
                                max_tokens=20000,
                                temperature=0.1,
                            )
                            if not isinstance(_retry_resp, str):
                                _retry_resp = getattr(_retry_resp, "text", None) or str(_retry_resp)
                            _retry_clean = _retry_resp.strip()
                            if _retry_clean.startswith("```"):
                                _retry_clean = _retry_clean.split("```", 2)[1].lstrip("json").strip()
                                if "```" in _retry_clean:
                                    _retry_clean = _retry_clean[:_retry_clean.rfind("```")].strip()
                            _retry_result = json.loads(_retry_clean)
                            blueprint = _retry_result.get("blueprint", [])
                            distribution_summary = _retry_result.get("distribution_summary", {})
                            logger.info(
                                "[OutlineAgent] Truncation retry succeeded: %d slots", len(blueprint)
                            )
                            is_partial_recovery = True  # continue to enforce_type_counts below
                        except Exception as _retry_e:
                            logger.warning(
                                "[OutlineAgent] Truncation retry also failed (%s) — "
                                "applying feedback-aware deterministic redistribution.", _retry_e
                            )
                            warnings.append(
                                f"JSON parse failed (recovered {len(_recovered)}/{_orig_count} slots, "
                                f"retry failed) — feedback-aware redistribution"
                            )
                            return await self._deterministic_redistribute(
                                exam_config, start_time, trace_id, warnings
                            )

                    # Enforce type counts then proceed normally
                    _scope_for_pad = _get_scope_chapters(exam_config)
                    blueprint = self._enforce_type_counts(
                        blueprint,
                        int(exam_config.get("mcq_count", 0) or 0),
                        int(exam_config.get("essay_count", 0) or 0),
                        int(exam_config.get("dung_sai_count", 0) or 0),
                        int(exam_config.get("short_answer_count", 0) or 0),
                        scope_chapters=_scope_for_pad,
                    )
                    valid_r, reason_r = self.validate_blueprint(blueprint)
                    if not valid_r:
                        warnings.append(f"Partial recovery invalid: {reason_r} — using feedback-aware fallback")
                        return await self._deterministic_redistribute(exam_config, start_time, trace_id, warnings)

                    scope_chapters_r = _get_scope_chapters(exam_config)
                    bloom_dist_r = exam_config.get("bloom_distribution", {})
                    distribution_summary = {
                        "by_bloom": {level: sum(1 for s in blueprint if s.get("bloom_level") == level) for level in bloom_dist_r},
                        "by_chapter": {ch: sum(1 for s in blueprint if s.get("chapter") == ch) for ch in scope_chapters_r},
                    }
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    blueprint, section_counts = _canonicalize_section_metadata(
                        blueprint,
                        exam_config,
                        retrieved_context,
                    )
                    if section_counts["unresolved"]:
                        warnings.append(
                            f"Section metadata unresolved for {section_counts['unresolved']} blueprint slots"
                        )
                    blueprint = _assign_blueprint_indices(blueprint)
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
                else:
                    logger.warning(
                        "[OutlineAgent] JSON parse failed in modification mode — "
                        "no partial slots recoverable, applying feedback-aware deterministic redistribution."
                    )
                    warnings.append("JSON parse failed — falling back to feedback-aware redistribution")
                    return await self._deterministic_redistribute(exam_config, start_time, trace_id, warnings)
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

        except Exception as e:
            warnings.append(f"Outline creation failed: {str(e)}")
            if is_modification and exam_config.get("current_blueprint"):
                logger.warning(
                    "[OutlineAgent] LLM call failed in modification mode (%s) — "
                    "applying feedback-aware deterministic redistribution.", e
                )
                warnings.append(f"LLM call failed ({e}) — falling back to feedback-aware redistribution")
                return await self._deterministic_redistribute(exam_config, start_time, trace_id, warnings)
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

    def _recover_partial_slots(self, raw_text: str) -> list[dict]:
        """
        Attempt to recover complete slot objects from a truncated JSON string.
        Uses regex to find complete {...} objects that have a question_id field.
        Returns list of valid slot dicts, or empty list if none recoverable.
        """
        import re as _re
        slots = []
        for match in _re.finditer(r'\{[^{}]+\}', raw_text):
            try:
                obj = json.loads(match.group())
                if obj.get("question_id") and obj.get("type") and obj.get("bloom_level"):
                    slots.append(obj)
            except (json.JSONDecodeError, ValueError):
                continue
        return slots

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
                max_tokens=20000 if exam_config.get("current_blueprint") else 20000,
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
            _scope_retry = _get_scope_chapters(exam_config)
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
        scope_chapters = _get_scope_chapters(exam_config)
        bloom_dist = exam_config.get("bloom_distribution", {})
        distribution_summary = {
            "by_bloom": {level: sum(1 for s in blueprint if s.get("bloom_level") == level) for level in bloom_dist},
            "by_chapter": {
                ch: sum(1 for s in blueprint if s.get("chapter") == ch)
                for ch in scope_chapters
            },
        }

        elapsed_ms = int((time.time() - start_time) * 1000)
        blueprint, section_counts = _canonicalize_section_metadata(
            blueprint,
            exam_config,
            retrieved_context,
        )
        if section_counts["unresolved"]:
            warnings.append(
                f"Section metadata unresolved for {section_counts['unresolved']} blueprint slots"
            )
        blueprint = _assign_blueprint_indices(blueprint)
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

        Parses teacher feedback to understand intent:
        - "đều / cân bằng" → equal total slots per chapter
        - "vận dụng / vận dụng cao tập trung ở chương X, Y" → assign VD/VDC bloom
          slots preferentially to those chapters, then fill remaining bloom levels
          to hit the per-chapter target

        Algorithm:
        1. Determine per-chapter target total (equal or from original distribution)
        2. Detect bloom-chapter mapping from feedback
        3. Assign bloom-specific slots to preferred chapters first
        4. Fill remaining slots (other bloom levels) to reach per-chapter target
        """
        import re as _re

        current_blueprint = list(exam_config.get("current_blueprint", []))
        scope_chapters = _get_scope_chapters(exam_config)

        if not current_blueprint or not scope_chapters:
            warnings.append("_deterministic_redistribute: missing blueprint or scope — using full fallback")
            return await self._fallback_outline(exam_config, start_time, trace_id, warnings)

        feedback = (exam_config.get("outline_feedback") or "").lower()
        n = len(current_blueprint)
        k = len(scope_chapters)

        # ── Step 1: Determine per-chapter target totals ─────────────────────
        has_balance = any(kw in feedback for kw in ["đều", "cân bằng", "đồng đều", "equal"])
        if has_balance:
            base = n // k
            remainder_count = n % k
            chapter_targets: dict[str, int] = {}
            for i, ch in enumerate(scope_chapters):
                chapter_targets[ch] = base + (1 if i < remainder_count else 0)
            warnings.append(f"Equal chapter distribution: {chapter_targets}")
        else:
            # Keep original distribution from current_blueprint
            orig_dist: dict[str, int] = {}
            for slot in current_blueprint:
                ch = slot.get("chapter", "")
                if ch in scope_chapters:
                    orig_dist[ch] = orig_dist.get(ch, 0) + 1
            # Fill missing chapters
            base = n // k
            chapter_targets = {ch: orig_dist.get(ch, base) for ch in scope_chapters}
            # Adjust total to exactly n
            diff = n - sum(chapter_targets.values())
            for ch in scope_chapters:
                if diff == 0:
                    break
                chapter_targets[ch] += 1 if diff > 0 else -1
                diff += -1 if diff > 0 else 1

        # ── Step 2: Detect bloom-chapter concentration from feedback ────────
        # e.g. "vận dụng cao tập trung ở chương 3, 4" →
        #   bloom_focus = {"van_dung", "van_dung_cao"}, focus_chapters = [ch3, ch4]
        bloom_keywords: dict[str, list[str]] = {
            "van_dung_cao": ["vận dụng cao", "vdc", "van dung cao"],
            "van_dung": ["vận dụng", " vd ", "van dung"],
            "thong_hieu": ["thông hiểu", " th ", "thong hieu"],
            "nhan_biet": ["nhận biết", " nb ", "nhan biet"],
        }
        bloom_focus: set[str] = set()
        for bloom_level, kws in bloom_keywords.items():
            if any(kw in feedback for kw in kws):
                bloom_focus.add(bloom_level)

        # If no specific bloom in feedback, focus bloom is empty (all blooms distributed normally)
        focus_chapters: list[str] = []
        for ch in scope_chapters:
            num_match = _re.search(r'chương\s*(\d+)', ch.lower())
            if not num_match:
                continue
            ch_num = num_match.group(1)
            if _re.search(rf'chương\s*{ch_num}(?:\D|$)', feedback):
                focus_chapters.append(ch)

        # ── Step 3: Assign slots using bloom-chapter mapping ────────────────
        # Separate blueprint slots by bloom level
        focus_bloom_slots = [s for s in current_blueprint if s.get("bloom_level") in bloom_focus] if bloom_focus else []
        other_slots = [s for s in current_blueprint if s.get("bloom_level") not in bloom_focus] if bloom_focus else list(current_blueprint)

        assigned: dict[str, list[dict]] = {ch: [] for ch in scope_chapters}

        if bloom_focus and focus_chapters:
            # Distribute focus-bloom slots: 70% to focus_chapters, 30% to rest
            n_focus = len(focus_bloom_slots)
            non_focus_chapters = [ch for ch in scope_chapters if ch not in focus_chapters]
            k_focus = len(focus_chapters)
            k_rest = len(non_focus_chapters)

            # How many focus-bloom slots go to focus_chapters?
            # Cap at chapter_targets — we can't exceed the per-chapter total
            max_focus_in_targets = sum(chapter_targets[ch] for ch in focus_chapters)
            # Aim for 65% of focus bloom slots in focus chapters, but not more than targets allow
            target_in_focus = min(round(n_focus * 0.65), max_focus_in_targets)
            target_in_rest = n_focus - target_in_focus

            # Distribute target_in_focus across focus_chapters proportionally to their targets
            if k_focus > 0:
                focus_weight_total = sum(chapter_targets[ch] for ch in focus_chapters)
                focus_alloc: dict[str, int] = {}
                for ch in focus_chapters:
                    focus_alloc[ch] = round(target_in_focus * (chapter_targets[ch] / max(focus_weight_total, 1)))
                # Adjust for rounding
                adj = target_in_focus - sum(focus_alloc.values())
                for ch in focus_chapters:
                    if adj == 0:
                        break
                    focus_alloc[ch] += 1 if adj > 0 else -1
                    adj += -1 if adj > 0 else 1
            else:
                focus_alloc = {}

            # Assign focus-bloom slots to focus chapters
            idx = 0
            for ch in focus_chapters:
                count = focus_alloc.get(ch, 0)
                for _ in range(count):
                    if idx < n_focus:
                        slot = dict(focus_bloom_slots[idx])
                        slot["chapter"] = ch
                        slot["section"] = ""
                        assigned[ch].append(slot)
                        idx += 1

            # Remaining focus-bloom slots go to rest chapters round-robin
            for i, slot in enumerate(focus_bloom_slots[idx:]):
                if k_rest > 0:
                    ch = non_focus_chapters[i % k_rest]
                else:
                    ch = scope_chapters[i % k]
                slot = dict(slot)
                slot["chapter"] = ch
                slot["section"] = ""
                assigned[ch].append(slot)

            warnings.append(
                f"Bloom-chapter assignment: bloom_focus={bloom_focus}, "
                f"focus_chapters={focus_chapters}, focus_alloc={focus_alloc}"
            )
        else:
            # No bloom-chapter mapping — round-robin assign focus_bloom_slots normally
            for i, slot in enumerate(focus_bloom_slots):
                ch = scope_chapters[i % k]
                slot = dict(slot)
                slot["chapter"] = ch
                slot["section"] = ""
                assigned[ch].append(slot)

        # ── Step 4: Fill remaining slots (other bloom levels) to hit targets ─
        # For each chapter, how many more slots are needed?
        remaining_slots = list(other_slots)
        slot_idx = 0
        for ch in scope_chapters:
            needed = chapter_targets[ch] - len(assigned[ch])
            for _ in range(max(needed, 0)):
                if slot_idx >= len(remaining_slots):
                    break
                slot = dict(remaining_slots[slot_idx])
                slot["chapter"] = ch
                slot["section"] = ""
                assigned[ch].append(slot)
                slot_idx += 1

        # If any remaining slots left (due to rounding), distribute round-robin
        for i, slot in enumerate(remaining_slots[slot_idx:]):
            ch = scope_chapters[i % k]
            slot = dict(slot)
            slot["chapter"] = ch
            slot["section"] = ""
            assigned[ch].append(slot)

        # ── Step 5: Interleave bloom levels within each chapter ───────────────
        # Without this, assigned[ch] is grouped by bloom (e.g. 6× NB then 1× VD)
        # because slots arrive sorted by type/bloom from current_blueprint.
        # Interleaving makes the blueprint look natural: NB, TH, VD, NB, TH...
        BLOOM_ORDER = ["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"]
        for ch in scope_chapters:
            ch_slots = assigned[ch]
            if len(ch_slots) <= 1:
                continue
            # Sort by bloom order index, then preserve original relative order within same bloom
            by_bloom: dict[str, list[dict]] = {b: [] for b in BLOOM_ORDER}
            unknown: list[dict] = []
            for s in ch_slots:
                bl = s.get("bloom_level", "")
                if bl in by_bloom:
                    by_bloom[bl].append(s)
                else:
                    unknown.append(s)
            # Interleave: pick one from each bloom level in rotation until all exhausted
            interleaved: list[dict] = []
            queues = [by_bloom[b] for b in BLOOM_ORDER if by_bloom[b]] + ([unknown] if unknown else [])
            while any(queues):
                for q in queues:
                    if q:
                        interleaved.append(q.pop(0))
            assigned[ch] = interleaved

        # Flatten and verify
        blueprint = [slot for slots in assigned.values() for slot in slots]
        if len(blueprint) != n:
            logger.warning(
                "[OutlineAgent] _deterministic_redistribute: blueprint length mismatch "
                "(%d != %d) — padding with round-robin slots to compensate.",
                len(blueprint), n,
            )
            warnings.append(f"Redistribution length mismatch ({len(blueprint)} != {n}) — padded")
            # Pad with any leftover slots from current_blueprint round-robin
            while len(blueprint) < n:
                idx = len(blueprint)
                slot = dict(current_blueprint[idx % len(current_blueprint)])
                slot["chapter"] = scope_chapters[idx % k]
                slot["section"] = ""
                blueprint.append(slot)
            blueprint = blueprint[:n]  # truncate if somehow over

        warnings.append(
            f"Deterministic redistribution applied: "
            f"{{{', '.join(f'{ch}: {len(assigned[ch])}' for ch in scope_chapters)}}}"
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
        blueprint, section_counts = _canonicalize_section_metadata(blueprint, exam_config)
        if section_counts["unresolved"]:
            warnings.append(
                f"Section metadata unresolved for {section_counts['unresolved']} blueprint slots"
            )
        blueprint = _assign_blueprint_indices(blueprint)
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
        scope_chapters = _get_scope_chapters(exam_config)

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
        llm_chapter_dist: dict[str, int] | None = None,
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
            llm_chapter_dist: If provided (modification mode), padded slots
                are assigned to chapters proportionally to this distribution
                rather than round-robin, preserving teacher feedback intent.
        """
        type_targets = {
            "mcq": mcq_target,
            "essay": essay_target,
            "dung_sai": ds_target,
            "short_answer": sa_target,
        }

        # Build chapter pool: if we have an LLM distribution, expand it into
        # a weighted pool so padding follows the same proportions as the LLM output.
        if llm_chapter_dist:
            # e.g. {Ch1: 3, Ch2: 7} → [Ch1, Ch1, Ch1, Ch2, Ch2, ...]
            _weighted_pool: list[str] = []
            for ch, cnt in llm_chapter_dist.items():
                _weighted_pool.extend([ch] * cnt)
            _pad_chapter_pool = _weighted_pool if _weighted_pool else (scope_chapters or [])
        else:
            _pad_chapter_pool = scope_chapters if scope_chapters else []

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

        for q_type, target in type_targets.items():
            if target <= 0:
                continue
            slots = by_type[q_type][:target]  # truncate excess
            # Pad missing slots
            while len(slots) < target:
                idx = len(slots)
                # Use weighted pool so chapter proportions match LLM feedback output
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
                    "topic_hint": BLOOM_HINT_TEMPLATE.get(bloom_cycle[idx % len(bloom_cycle)], f"Câu hỏi mức {bloom_cycle[idx % len(bloom_cycle)]}"),
                    "content_type": "calculation" if q_type in ("short_answer", "dung_sai") else "text",
                    "estimated_difficulty": 0.5,
                })
                id_counters[q_type] += 1
            # Renumber IDs for consistency
            for i, slot in enumerate(slots):
                slot["question_id"] = f"{prefix_map[q_type]}_{i+1:03d}"
            result.extend(slots)

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
        """Build the user prompt for outline creation or modification."""
        scope = exam_config.get("scope", [])
        mcq_count = int(exam_config.get("mcq_count", 0) or 0)
        essay_count = int(exam_config.get("essay_count", 0) or 0)
        dung_sai_count = int(exam_config.get("dung_sai_count", 0) or 0)
        short_answer_count = int(exam_config.get("short_answer_count", 0) or 0)
        bloom_dist = exam_config.get("bloom_distribution", {})
        user_prompt_text = exam_config.get("user_prompt", "") or ""
        extra_instructions = exam_config.get("extra_instructions", "") or ""
        outline_feedback = exam_config.get("outline_feedback", "") or ""
        current_blueprint = exam_config.get("current_blueprint", []) or []

        total_questions = mcq_count + essay_count + dung_sai_count + short_answer_count
        bloom_counts = self._bloom_pct_to_counts(bloom_dist, total_questions)
        blueprint_history: list[dict] = exam_config.get("blueprint_history") or []

        # Build section list for section-aware prompt. For textbook namespaces,
        # section_registry is built from retrieved chunks because no document
        # heading_tree exists.
        scope_units: list[dict] = exam_config.get("section_registry") or exam_config.get("scope_units") or []
        _sec_units_for_prompt = [
            u for u in scope_units
            if u.get("section_title") and not u.get("scope_unit_key", "").startswith("__ch__")
        ]
        if _sec_units_for_prompt:
            _sec_lines = [
                f"  - {u['scope_unit_key']} | {u.get('chapter_title','')} > {u.get('section_title','')}"
                for u in _sec_units_for_prompt
            ]
            section_list_str = (
                "\n\n### Danh sách MỤC được phép dùng (scope_units):\n"
                + "\n".join(_sec_lines)
                + "\n\nMỗi slot PHẢI có field \"primary_scope_unit_key\" = một key trong danh sách trên.\n"
                + "Quy tắc secondary: nhan_biet/thong_hieu → secondary_scope_unit_keys=[], "
                + "van_dung → tối đa 1, van_dung_cao → tối đa 2. "
                + "primary và secondary KHÔNG được trùng.\n"
                + "Nếu không có section phù hợp, chọn key gần nhất với chapter của slot."
            )
        else:
            section_list_str = ""

        # ── Pre-compute the EXACT slot matrix (bloom × type) ──────────────────
        # From current_blueprint, count per (bloom_level, type).
        # This gives LLM the precise breakdown it must preserve.
        bloom_levels = ["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"]
        q_types_active = []
        if mcq_count: q_types_active.append("mcq")
        if essay_count: q_types_active.append("essay")
        if dung_sai_count: q_types_active.append("dung_sai")
        if short_answer_count: q_types_active.append("short_answer")

        type_label = {"mcq": "MCQ", "essay": "Essay", "dung_sai": "Đúng-Sai", "short_answer": "Trả lời ngắn"}

        # Build bloom×type matrix from existing blueprint if in modification mode
        slot_matrix: dict[str, dict[str, int]] = {bl: {qt: 0 for qt in q_types_active} for bl in bloom_levels}
        if current_blueprint:
            for s in current_blueprint:
                bl = s.get("bloom_level", "")
                qt = s.get("type", "mcq")
                if bl in slot_matrix and qt in slot_matrix[bl]:
                    slot_matrix[bl][qt] += 1

        # Format matrix as readable table string
        def _matrix_table() -> str:
            header = "| Bloom Level       | " + " | ".join(type_label.get(qt, qt) for qt in q_types_active) + " | TỔNG |"
            sep    = "|" + "---|" * (len(q_types_active) + 2)
            rows = []
            for bl in bloom_levels:
                if bloom_counts.get(bl, 0) == 0:
                    continue
                cells = [str(slot_matrix[bl].get(qt, 0)) for qt in q_types_active]
                row_total = sum(slot_matrix[bl].get(qt, 0) for qt in q_types_active)
                rows.append(f"| {bl:<17} | " + " | ".join(cells) + f" | {row_total}    |")
            total_row_cells = [str(sum(slot_matrix[bl].get(qt, 0) for bl in bloom_levels)) for qt in q_types_active]
            rows.append(f"| **TỔNG**          | " + " | ".join(total_row_cells) + f" | **{total_questions}** |")
            return "\n".join([header, sep] + rows)

        # ═══════════════════════════════════════════════════════════════
        # MODIFICATION MODE — teacher rejected the previous blueprint
        # ═══════════════════════════════════════════════════════════════
        if outline_feedback and current_blueprint:
            print(f"[OutlineAgent] MODIFICATION MODE: feedback='{outline_feedback[:80]}', "
                  f"blueprint_len={len(current_blueprint)}", flush=True)

            # Compact current blueprint for LLM, while preserving section
            # metadata needed by BuilderAgent for section-level retrieval.
            compact_bp = []
            for s in current_blueprint:
                item = {
                    "question_id": s.get("question_id"),
                    "type": s.get("type", "mcq"),
                    "bloom_level": s.get("bloom_level"),
                    "chapter": s.get("chapter"),
                    "topic_hint": s.get("topic_hint", ""),
                }
                for field in SECTION_METADATA_FIELDS:
                    value = s.get(field)
                    if _has_value(value):
                        item[field] = value
                compact_bp.append(item)
            current_dist = {}
            for s in current_blueprint:
                ch = s.get("chapter", "?")
                current_dist[ch] = current_dist.get(ch, 0) + 1

            # Compute per-% helper for teacher feedback that references percentages
            pct_helper = f"(tổng {total_questions} câu → 10% ≈ {round(total_questions*0.1)} câu, " \
                         f"20% ≈ {round(total_questions*0.2)} câu, " \
                         f"30% ≈ {round(total_questions*0.3)} câu, " \
                         f"40% ≈ {round(total_questions*0.4)} câu, " \
                         f"50% ≈ {round(total_questions*0.5)} câu)"

        # Build blueprint history block for modification mode
        history_block_mod = ""
        if blueprint_history:
            history_block_mod = "\n---\n### LỊCH SỬ CÁC BLUEPRINT ĐÃ BỊ TỪ CHỐI\n\n"
            for entry in blueprint_history[-2:]:  # Show at most 2 previous rounds
                rnd = entry.get("round", "?")
                fb = entry.get("feedback", "")
                prev_bp = entry.get("blueprint", [])
                prev_dist: dict[str, int] = {}
                for s in prev_bp:
                    ch = s.get("chapter", "?")
                    prev_dist[ch] = prev_dist.get(ch, 0) + 1
                history_block_mod += (
                    f"**Round {rnd}** — Phản hồi: \"{fb}\"\n"
                    f"Phân bổ khi đó: {json.dumps(prev_dist, ensure_ascii=False)}\n\n"
                )
            history_block_mod += "Tránh lặp lại các lỗi đã bị từ chối ở trên.\n"

            return f"""Bạn là chuyên gia thiết kế đề thi. Nhiệm vụ: CHỈNH SỬA blueprint theo phản hồi giáo viên.

---
### RÀNG BUỘC BẤT BIẾN (KHÔNG ĐƯỢC THAY ĐỔI — vi phạm là output sai)

TỔNG SỐ SLOT: {total_questions} (chính xác, không +1, không -1)

Phân bổ loại câu hỏi (giữ nguyên hoàn toàn):
{chr(10).join(f"  - {type_label.get(qt,'?')}: {[mcq_count,essay_count,dung_sai_count,short_answer_count][q_types_active.index(qt)]} câu" for qt in q_types_active)}

Số câu theo mức Bloom (giữ nguyên hoàn toàn):
{chr(10).join(f"  - {bl}: {bloom_counts.get(bl,0)} câu" for bl in bloom_levels if bloom_counts.get(bl,0) > 0)}

Ma trận slot bloom x loại câu (từng con số không được thay đổi):
{_matrix_table()}

---
### YÊU CẦU GỐC CỦA GIÁO VIÊN KHI TẠO ĐỀ

{user_prompt_text or "(Không có yêu cầu đặc biệt)"}

---
### BLUEPRINT CŨ CẦN CHỈNH SỬA

Phân bổ theo chương hiện tại: {json.dumps(current_dist, ensure_ascii=False)}
Tổng slot: {len(compact_bp)}

{json.dumps(compact_bp, ensure_ascii=False, indent=2)}

---
### PHẢN HỒI GIÁO VIÊN (thực hiện đúng yêu cầu này)

{outline_feedback}
{history_block_mod}
---
### HƯỚNG DẪN THỰC HIỆN

Tổng {total_questions} câu. Quy đổi phần trăm: {pct_helper}

Bước 1: Xác định chương nào tăng/giảm theo phản hồi.
Bước 2: Tính số câu cụ thể mỗi chương (tổng phải bằng {total_questions}).
Bước 3: Gán lại field "chapter", "section" và "topic_hint" cho từng slot. Tuyệt đối KHÔNG thêm/xóa slot, KHÔNG thay đổi bloom_level, KHÔNG thay đổi type.
Nếu BLUEPRINT CŨ có các field section metadata ("section", "primary_section_id", "primary_section_title", "primary_scope_unit_key", "secondary_section_ids", "secondary_section_titles", "secondary_scope_unit_keys") thì output mới PHẢI giữ lại các field đó, trừ khi feedback yêu cầu đổi section/chapter cụ thể.
Nếu chỉ đổi thứ tự/random/phân bố đều hơn thì KHÔNG được xóa section metadata.
Bước 4: Kiểm tra: tổng slot = {total_questions}? bloom counts khớp ma trận? mỗi chương trong scope có ít nhất 1 slot?

Phạm vi (scope): {json.dumps(scope, ensure_ascii=False)}{section_list_str}

Output chỉ JSON thuần (không markdown, không giải thích):
{{"blueprint": [<TOAN BO {total_questions} slot da chinh sua, gom day du section metadata neu co>], "distribution_summary": {{"by_bloom": {bloom_counts}, "by_chapter": {{}}}}}}"""

        # CREATION MODE — build with constraints + history
        print(f"[OutlineAgent] CREATION MODE: outline_feedback={bool(outline_feedback)}, "
              f"has_blueprint={bool(current_blueprint)}", flush=True)

        type_breakdown_lines = []
        if mcq_count:          type_breakdown_lines.append(f"  - MCQ (trắc nghiệm 4 lựa chọn): {mcq_count} câu")
        if essay_count:        type_breakdown_lines.append(f"  - Essay (tự luận): {essay_count} câu")
        if dung_sai_count:     type_breakdown_lines.append(f"  - Đúng-Sai (4 mệnh đề a/b/c/d, type='dung_sai'): {dung_sai_count} câu")
        if short_answer_count: type_breakdown_lines.append(f"  - Trả lời ngắn (điền số, type='short_answer'): {short_answer_count} câu")
        type_breakdown = "\n".join(type_breakdown_lines)

        # Blueprint history block for creation mode (if re-running after a rejection)
        history_block_create = ""
        if blueprint_history:
            history_block_create = "\n### LỊCH SỬ PHẢN HỒI TRƯỚC ĐÓ (tránh lặp lại)\n\n"
            for entry in blueprint_history[-2:]:
                rnd = entry.get("round", "?")
                fb = entry.get("feedback", "")
                prev_bp = entry.get("blueprint", [])
                prev_dist: dict[str, int] = {}
                for s in prev_bp:
                    ch = s.get("chapter", "?")
                    prev_dist[ch] = prev_dist.get(ch, 0) + 1
                history_block_create += (
                    f"Round {rnd} — Phản hồi: \"{fb}\"\n"
                    f"Phân bổ khi đó: {json.dumps(prev_dist, ensure_ascii=False)}\n\n"
                )

        pct_helper_create = (
            f"(tổng {total_questions} câu → 10% ≈ {round(total_questions*0.1)} câu, "
            f"20% ≈ {round(total_questions*0.2)} câu, "
            f"30% ≈ {round(total_questions*0.3)} câu)"
        )

        return f"""Tạo sườn đề kiểm tra với cấu hình sau:

### RÀNG BUỘC BẮT BUỘC (KHÔNG ĐƯỢC SAI)

Tổng số câu: {total_questions} (chính xác)
{type_breakdown}

Phân bổ Bloom (số câu chính xác, không phải %):
{chr(10).join(f"  - {bl}: {bloom_counts.get(bl,0)} câu" for bl in bloom_levels if bloom_counts.get(bl,0) > 0)}

Quy đổi %: {pct_helper_create}

### Phạm vi (scope):
{json.dumps(scope, ensure_ascii=False)}{section_list_str}

Quy tắc phân bổ mặc định:
- Mỗi chương trong scope phải có ít nhất 1 câu
- Không chương nào > 50% tổng câu
- Mặc định phân bổ đều các chương trừ khi giáo viên chỉ định khác
- Nếu chỉ 1 chương trong scope → phân bổ theo section/chủ đề trong chương đó

### Kiến thức đã truy xuất:
{self._build_context_summary(retrieved_context)}

### Yêu cầu từ giảng viên:
{user_prompt_text or "Không có yêu cầu đặc biệt — phân bổ đều các chương."}

### Hướng dẫn bổ sung:
{extra_instructions or "Sinh câu hỏi chuẩn mực, phù hợp với chương trình phổ thông Việt Nam."}
{history_block_create}
Tạo blueprint chi tiết (JSON thuần):"""


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
                    "topic_hint": BLOOM_HINT_TEMPLATE.get(bloom, f"Câu hỏi mức {bloom}"),
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
                "topic_hint": BLOOM_HINT_TEMPLATE["van_dung"],
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
                    "topic_hint": BLOOM_HINT_TEMPLATE.get(bloom, f"Câu đúng-sai mức {bloom}"),
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
                    "topic_hint": BLOOM_HINT_TEMPLATE.get(bloom, f"Câu trả lời ngắn mức {bloom}"),
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

        blueprint, section_counts = _canonicalize_section_metadata(blueprint, exam_config)
        if section_counts["unresolved"]:
            warnings.append(
                f"Section metadata unresolved for {section_counts['unresolved']} blueprint slots"
            )
        blueprint = _assign_blueprint_indices(blueprint)
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
