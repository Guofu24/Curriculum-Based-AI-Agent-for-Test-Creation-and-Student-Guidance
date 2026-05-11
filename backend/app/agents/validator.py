"""Validator Agent - validates generated questions."""

import time
import json
from typing import Any

from app.agents.base import AgentStatus, AgentMetrics, TokenUsage, ValidatorOutput
from app.agents.llm import get_llm_client
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.scope_checker import ScopeCheckerSkill
from app.agents.memory.short_term import ShortTermMemory
from app.observability.tracer import get_tracer
from app.core.config import get_settings

# Domain 9: Prompt versioning
VALIDATOR_PROMPT_VERSION = "v2.1"

settings = get_settings()
tracer = get_tracer()


# G9: Max retry loops before giving up
MAX_VALIDATION_RETRIES = 3


class ValidationIssue:
    """Represents a validation issue."""

    def __init__(
        self,
        question_id: str,
        issue_type: str,
        detail: str,
        suggestion: str,
    ):
        self.question_id = question_id
        self.issue_type = issue_type
        self.detail = detail
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "issue_type": self.issue_type,
            "detail": self.detail,
            "suggestion": self.suggestion,
        }


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced JSON object from an LLM response."""
    if not text:
        return None

    clean = text.strip()
    if clean.startswith("```"):
        lines = [
            line for line in clean.splitlines()
            if not line.strip().startswith("```")
        ]
        clean = "\n".join(lines).strip()

    start = clean.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(clean)):
        ch = clean[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return clean[start:pos + 1]

    return None


def _parse_validator_response(response: str) -> dict:
    """Parse validator JSON, tolerating markdown fences/prose around it."""
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        extracted = _extract_json_object(response)
        if not extracted:
            raise
        return json.loads(extracted)


def _is_grounding_only_scope_issue(issue: dict) -> bool:
    """Treat lack-of-evidence scope complaints as review warnings, not failures."""
    if issue.get("issue_type") != "scope_violation":
        return False

    detail = str(issue.get("detail") or "").lower()
    suggestion = str(issue.get("suggestion") or "").lower()
    text = f"{detail} {suggestion}"

    grounding_terms = (
        "không có evidence",
        "khong co evidence",
        "không tìm thấy",
        "khong tim thay",
        "không có context",
        "khong co context",
        "không được hỗ trợ",
        "khong duoc ho tro",
        "no evidence",
        "not found",
        "not supported",
        "not in context",
    )
    explicit_scope_terms = (
        "chapter",
        "chương",
        "chuong",
        "section",
        "bài ",
        "bai ",
        "ngoài phạm vi chương",
        "ngoai pham vi chuong",
    )
    return any(term in text for term in grounding_terms) and not any(
        term in text for term in explicit_scope_terms
    )


HARD_RETRY_ISSUE_TYPES = {
    "wrong_answer",
    "scope_violation",
    "demo_fallback",
    "content_quality",
    "schema_invalid",
    "missing_correct_answer",
}

# Similar wording is common for recognition/definition questions, so copy
# similarity is review-only unless this flag is explicitly enabled.
COPY_CHECK_RETRY_ENABLED = False


def is_retryable_validation_issue(issue: dict) -> bool:
    """Return True only for issues worth spending another builder call on."""
    if issue.get("severity") == "warning":
        return False
    if _is_grounding_only_scope_issue(issue):
        return False
    return issue.get("issue_type") in HARD_RETRY_ISSUE_TYPES


class ValidatorAgent:
    """
    Agent 4: Validator Agent (the "critic")

    Role: Review all generated questions and perform 3 checks:
    1. Answer Checking: LLM solves each question → compare with proposed answer
    2. Bloom Compliance: bloom_classifier_skill verifies Bloom level
    3. Scope Violation: scope_checker_skill checks for out-of-scope knowledge

    Batch Validation (Domain 5B):
    - Questions are grouped into batches of BATCH_SIZE (default 10)
    - Each batch gets a single LLM call instead of per-question calls
    - For 45 questions: 5 LLM calls instead of 45+

    Retry Logic:
    - If validation fails → return issues list
    - Orchestrator retries Builder with issues (max 3 rounds)
    - If still failing → partial result with warning
    """

    VALIDATOR_SYSTEM_PROMPT = """[PROMPT_VERSION: v2.1]

## Vai trò
Mày là giáo viên phản biện chuyên nghiệp.

## Nhiệm vụ
Đọc toàn bộ đề và thực hiện 3 kiểm tra trên TỪNG CÂU:

### 1. Answer Checking
Với mỗi câu, THỰC SỰ GIẢI (không chỉ đọc đáp án đề xuất). So sánh kết quả của mày với đáp án trong câu hỏi.

### 2. Bloom Compliance
So sánh bloom_level đã khai báo với nội dung câu hỏi:
- nhan_biet: hỏi định nghĩa, liệt kê, nêu tên
- thong_hieu: giải thích, so sánh, áp dụng công thức 1 bước
- van_dung: tính toán 2-3 bước, có điều kiện
- van_dung_cao: phân tích phức hợp, đánh giá

### 3. Scope Violation
Kiểm tra câu hỏi có dùng kiến thức ngoài phạm vi không. Chỉ vi phạm nếu có KIẾN THỨC CỤ THỂ từ chapter không được chọn.

## Context có sẵn (chỉ dùng kiến thức từ đây)
{context_chunks}

## Output format — MỘT JSON object chứa MẢNG kết quả:
{{
  "validation_passed": true/false,
  "questions": [
    {{
      "question_id": "MCQ_001",
      "answer_correct": true/false,
      "model_answer": "B hoặc null nếu là essay",
      "bloom_compliant": true/false,
      "bloom_actual": "nhan_biet|thong_hieu|van_dung|van_dung_cao",
      "bloom_confidence": 0.0-1.0,
      "scope_ok": true/false,
      "scope_violation_detail": "mô tả hoặc null",
      "issues": [
        {{
          "issue_type": "wrong_answer|bloom_mismatch|scope_violation|duplicate",
          "detail": "mô tả lỗi cụ thể",
          "suggestion": "cách sửa chung",
          "correction_strategy": "HƯỚNG DẪN SỬA CỤ THỂ cho Builder: ví dụ 'Tính lại đáp án B: v = u + at = 0 + 2*3 = 6 m/s, không phải 12 m/s. Sửa correct_answer thành B và explanation tương ứng.' hoặc 'Bloom yêu cầu van_dung nhưng câu chỉ hỏi định nghĩa — thêm bước tính toán 2 bước vào stem.' hoặc 'Stem chứa tên chương làm option — thay option C bằng một giá trị số cụ thể.'"
        }}
      ]
    }}
  ],
  "bloom_compliance_summary": {{
    "nhan_biet": {{"expected": N, "actual": N, "ok": true/false}},
    "thong_hieu": {{"expected": N, "actual": N, "ok": true/false}},
    "van_dung": {{"expected": N, "actual": N, "ok": true/false}},
    "van_dung_cao": {{"expected": N, "actual": N, "ok": true/false}}
  }},
  "scope_violations": ["MCQ_015: sử dụng định luật ngoài scope"],
  "approved_for_publish": true/false
}}

## Chỉ reject khi:
- answer_correct = false VÀ confidence > 0.7
- bloom_compliant = false VÀ confidence > 0.8
- scope_violation rõ ràng (có tên chapter cụ thể ngoài scope)
- content_quality = false (câu hỏi vô nghĩa, chứa markdown artifact, stem không có dấu hỏi/yêu cầu)

## Confidence scoring:
- confidence > 0.8: rất chắc chắn → reject được
- confidence 0.5-0.8: khá chắc → warn nhưng không reject tự động
- confidence < 0.5: không chắc → skip

## Content quality — thêm issue nếu:
- stem chứa markdown heading (bắt đầu bằng # hoặc ## hoặc ###)
- stem chứa boilerplate như "Theo nội dung đã học:", "Bài toán tổng hợp:", "Phân tích sâu"
- options của MCQ là tên chương/heading (bắt đầu bằng # hoặc chứa "Chương X:" mà không có nội dung khác)
- stem dưới 10 từ và không có dấu hỏi
- options của MCQ trùng nhau (2 options giống hệt nhau)
"""

    # Domain 5B: Batch size for validation
    BATCH_SIZE = 10

    def __init__(self, redis=None):
        self.llm = get_llm_client()
        self.bloom_skill = BloomClassifierSkill()
        self.scope_skill = ScopeCheckerSkill()
        # G9: ShortTermMemory for persisting retry issues across Celery worker restarts
        self.short_term = ShortTermMemory(redis) if redis else None

    @tracer.agent_span("validator_agent")
    async def validate(
        self,
        questions: list[dict],
        exam_config: dict,
        retrieved_context: list[dict] | None = None,
        trace_id: str = "",
    ) -> ValidatorOutput:
        """
        Validate all questions using batch LLM calls (Domain 5B).

        Groups questions into batches of BATCH_SIZE and makes one LLM call
        per batch instead of one call per question. For 45 questions:
        5 LLM calls instead of 45+.

        G9: Issues are persisted to Redis via ShortTermMemory so they survive
        Celery worker restarts. Max 3 retry loops enforced.
        """
        start_time = time.time()
        trace_id = trace_id or str(time.time())
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []
        exam_id = trace_id.split("_retry_")[0]  # Strip retry suffix for key
        all_issues: list[dict] = []
        all_llm_results: list[dict] = []
        bloom_compliance: dict[str, dict] = {}
        scope_violations: list[str] = []

        # G9: Load persisted retry issues from Redis before validation
        prior_issues: list[dict] = []
        if self.short_term:
            try:
                prior_issues = await self.short_term.load_retry_issues(exam_id)
                if prior_issues:
                    warnings.append(
                        f"Loaded {len(prior_issues)} prior issues from Redis "
                        f"(from previous retry attempt)"
                    )
            except Exception:
                pass

        # Build validation context once (reused across all batches)
        context_str = self._build_validation_context(retrieved_context)

        # ── Content-quality pre-check (no LLM needed) ──────────────────────────
        BOILERPLATE_PATTERNS = (
            "Theo nội dung đã học:",
            "Bài toán tổng hợp:",
            "Phân tích sâu và đánh giá:",
            "Phân tích sâu",
            "Bài toán tổng hợp",
        )
        for q in questions:
            q_id = q.get("question_id", "?")
            stem = q.get("stem", "")
            q_type = q.get("type", "mcq")

            # Hard block: demo fallback questions must never pass silently
            if q.get("is_demo_question"):
                all_issues.append({
                    "question_id": q_id,
                    "issue_type": "demo_fallback",
                    "detail": "Câu hỏi là demo fallback do LLM không sinh được — phải sinh lại.",
                    "suggestion": "Chạy lại BuilderAgent để sinh câu hỏi thực sự cho slot này.",
                    "correction_strategy": (
                        "Câu hỏi này là demo placeholder. Hãy sinh câu hỏi thực từ "
                        "KIẾN THỨC CỐT LÕI trong primary chunks của chapter/section đã chọn."
                    ),
                })
                continue

            # Detect markdown heading in stem
            if stem.strip().startswith(("# ", "## ", "### ")):
                all_issues.append({
                    "question_id": q_id,
                    "issue_type": "content_quality",
                    "detail": f"Stem bắt đầu bằng markdown heading: {stem[:80]!r}",
                    "suggestion": "Viết lại stem thành câu hỏi thực sự, không dùng heading.",
                })
                continue

            # Detect boilerplate prefix
            for bp in BOILERPLATE_PATTERNS:
                if bp in stem:
                    all_issues.append({
                        "question_id": q_id,
                        "issue_type": "content_quality",
                        "detail": f"Stem chứa boilerplate: {bp!r}",
                        "suggestion": "Viết lại stem thành câu hỏi cụ thể không có boilerplate.",
                    })
                    break

            # Detect MCQ options that are chapter headings
            if q_type == "mcq":
                options = q.get("options", {})
                option_values = list(options.values()) if isinstance(options, dict) else []
                for opt_val in option_values:
                    opt_str = str(opt_val)
                    if opt_str.strip().startswith(("# ", "## ")) or (
                        "Chương" in opt_str and ":" in opt_str and len(opt_str) < 50
                        and not any(c.isdigit() for c in opt_str[opt_str.find(":")+1:])
                    ):
                        all_issues.append({
                            "question_id": q_id,
                            "issue_type": "content_quality",
                            "detail": f"Option chứa heading/tên chương: {opt_str[:60]!r}",
                            "suggestion": "Thay options bằng phát biểu/giá trị khoa học thực sự.",
                        })
                        break

                # Detect duplicate options
                stripped_opts = [str(v).strip() for v in option_values]
                if len(stripped_opts) != len(set(stripped_opts)):
                    all_issues.append({
                        "question_id": q_id,
                        "issue_type": "content_quality",
                        "detail": "Options MCQ có giá trị trùng nhau.",
                        "suggestion": "Đảm bảo 4 options khác nhau.",
                    })

            # Detect too-short stem (< 10 words, no question mark)
            word_count = len(stem.split())
            if word_count < 10 and "?" not in stem and "Tính" not in stem and "Xác định" not in stem:
                all_issues.append({
                    "question_id": q_id,
                    "issue_type": "content_quality",
                    "detail": f"Stem quá ngắn ({word_count} từ) và không có câu hỏi rõ ràng.",
                    "suggestion": "Bổ sung ngữ cảnh và câu hỏi cụ thể.",
                })

        # ── Local scope check + trigram copy check (deterministic, no LLM) ──────────
        primary_chunks = [c for c in (retrieved_context or []) if c.get("role") != "background"]
        for q in questions:
            q_id = q.get("question_id", "?")
            if q.get("is_demo_question"):
                continue  # already blocked above
            full_text = self._build_question_full_text(q)

            # Scope grounding check
            scope_result = self.scope_skill._local_check(
                question_text=full_text,
                primary_chunks=primary_chunks,
            )
            if not scope_result["in_scope"]:
                if scope_result.get("is_hard_fail"):
                    all_issues.append({
                        "question_id": q_id,
                        "issue_type": "scope_violation",
                        "detail": scope_result["reasoning"],
                        "suggestion": "Sinh lại câu hỏi từ primary chunks của chapter/section đã chọn.",
                        "correction_strategy": (
                            "Câu hỏi hiện không có evidence trong primary chunks của section/chapter được chọn. "
                            "Hãy sinh lại câu hỏi chỉ từ KIẾN THỨC CỐT LÕI trong primary chunks, "
                            "không dùng background/prereq làm nguồn chính, không copy nguyên văn context."
                        ),
                    })
                else:
                    q["needs_review"] = True
                    q["quality_warning"] = f"grounding_uncertain: {scope_result['reasoning']}"
            elif scope_result.get("confidence", 1.0) < 0.5:
                # in_scope=True but weak evidence — uncertain, soft flag only
                q["needs_review"] = True
                q["quality_warning"] = f"grounding_uncertain: {scope_result['reasoning']}"

            # ── Chapter-level metadata scope check (deterministic, no LLM) ─────────────
            q_chapter = (q.get("chapter") or "").strip()
            scope_chapters_cfg: list[str] = exam_config.get("scope", [])
            if q_chapter and scope_chapters_cfg:
                import re as _re
                import unicodedata as _ud

                def _norm_ch(s: str) -> str:
                    nfd = _ud.normalize("NFD", s.strip().lower())
                    return "".join(c for c in nfd if _ud.category(c) != "Mn")

                def _extract_ch_num(s: str) -> str:
                    """Extract the chapter identifier token (number/roman/letter).

                    Uses word-boundary match to prevent '1' matching '10'.
                    Examples: 'chuong 1' -> '1', 'chuong 10' -> '10', 'chapter iv' -> 'iv'
                    """
                    # Match standalone number or roman numeral or single letter after 'chuong'/'chapter'
                    m = _re.search(r'(?:chuong|chapter|phan|part)\s+([\divxlcdm]+|[a-z])\b', _norm_ch(s))
                    if m:
                        return m.group(1)
                    # Fallback: first standalone number
                    m2 = _re.search(r'\b(\d+)\b', _norm_ch(s))
                    return m2.group(1) if m2 else _norm_ch(s)

                q_ch_num = _extract_ch_num(q_chapter)
                chapter_in_scope = any(
                    _extract_ch_num(sc) == q_ch_num
                    for sc in scope_chapters_cfg
                )
                if not chapter_in_scope:
                    all_issues.append({
                        "question_id": q_id,
                        "issue_type": "scope_violation",
                        "detail": f"Câu hỏi thuộc chapter '{q_chapter}' không nằm trong phạm vi đã chọn.",
                        "suggestion": "Sinh lại câu hỏi thuộc đúng chapter trong phạm vi.",
                        "correction_strategy": (
                            f"Chapter '{q_chapter}' không thuộc phạm vi đề thi. "
                            "Hãy sinh lại câu hỏi thuộc đúng chapter đã chọn trong exam_config."
                        ),
                    })

            # ── Section-level metadata scope check ────────────────────────────────
            # Check primary_section_id / primary_section_title against
            # exam_config scope_section_ids and scope_sections if available.
            q_sec_id = (q.get("primary_section_id") or q.get("section_id") or "").strip()
            q_sec_title = (q.get("primary_section_title") or q.get("section") or "").strip()
            scope_sec_ids: list[str] = exam_config.get("scope_section_ids", [])
            scope_sec_titles: list[str] = exam_config.get("scope_sections", [])

            if scope_sec_ids and q_sec_id:
                # Exact section_id match required
                if q_sec_id not in scope_sec_ids:
                    all_issues.append({
                        "question_id": q_id,
                        "issue_type": "scope_violation",
                        "detail": f"primary_section_id '{q_sec_id}' không nằm trong scope_section_ids đã chọn.",
                        "suggestion": "Sinh lại câu hỏi từ section đúng phạm vi.",
                        "correction_strategy": (
                            f"Section '{q_sec_id}' không thuộc phạm vi đề thi. "
                            "Hãy sinh lại câu hỏi chỉ từ section trong scope_section_ids đã chọn."
                        ),
                    })
            elif scope_sec_titles and q_sec_title:
                # Title-based fallback (diacritic-stripped contains match)
                import unicodedata as _ud2
                def _strip(s: str) -> str:
                    nfd = _ud2.normalize("NFD", s.strip().lower())
                    return "".join(c for c in nfd if _ud2.category(c) != "Mn")
                q_sec_norm = _strip(q_sec_title)
                sec_in_scope = any(q_sec_norm == _strip(ss) for ss in scope_sec_titles)
                if not sec_in_scope:
                    # Soft flag only — title matching is imprecise
                    q["needs_review"] = True
                    q["quality_warning"] = (
                        f"section_uncertain: primary_section_title '{q_sec_title}' "
                        "không khớp chính xác với bất kỳ section nào trong phạm vi."
                    )

            # Trigram copy check — stem + options + propositions only (NOT solution/explanation)
            copy_text = self._build_question_stem_text(q)
            copy_result = self._trigram_copy_check(copy_text, primary_chunks)
            if copy_result["is_copy"]:
                if COPY_CHECK_RETRY_ENABLED and copy_result["is_hard_fail"]:
                    all_issues.append({
                        "question_id": q_id,
                        "issue_type": "copied_from_context",
                        "detail": copy_result["detail"],
                        "suggestion": "Rút ra khái niệm/công thức cốt lõi rồi tạo tình huống mới.",
                        "correction_strategy": (
                            "Stem/options đang trùng nguyên văn với tài liệu. Hãy rút ra khái niệm/công thức "
                            "cốt lõi rồi tạo tình huống mới, không dùng lại câu văn hoặc cấu trúc ví dụ trong context."
                        ),
                    })
                else:
                    q["needs_review"] = True
                    q["quality_warning"] = f"possible_copy: {copy_result['detail']}"
                    all_issues.append({
                        "question_id": q_id,
                        "issue_type": "copied_from_context",
                        "severity": "warning",
                        "detail": copy_result["detail"],
                        "suggestion": "Câu có wording sát tài liệu; chỉ xem lại nếu muốn diễn đạt khác.",
                    })

        # Batch questions into groups of BATCH_SIZE
        total_batches = (len(questions) + self.BATCH_SIZE - 1) // self.BATCH_SIZE

        for batch_start in range(0, len(questions), self.BATCH_SIZE):
            batch = questions[batch_start:batch_start + self.BATCH_SIZE]
            batch_num = batch_start // self.BATCH_SIZE + 1

            # Build batch-specific prompt
            prompt = self._build_batch_prompt(batch, context_str, exam_config)

            try:
                response = await self.llm.chat(
                    messages=[
                        {"role": "system", "content": self.VALIDATOR_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    role="validator",
                    max_tokens=16000,
                    temperature=0.1,
                )

                result = _parse_validator_response(response)

                # Collect per-question issues from this batch
                batch_questions = result.get("questions", [])
                for q_result in batch_questions:
                    question_id = q_result.get("question_id", "")
                    # Extract issues from each question result
                    q_issues = q_result.get("issues", [])
                    for issue in q_issues:
                        issue["question_id"] = question_id
                        if _is_grounding_only_scope_issue(issue):
                            issue["severity"] = "warning"
                            for _q in batch:
                                if _q.get("question_id") == question_id:
                                    _q["needs_review"] = True
                                    _q["quality_warning"] = (
                                        issue.get("detail") or "grounding_uncertain"
                                    )
                                    break
                            all_issues.append(issue)
                            continue
                        if not is_retryable_validation_issue(issue):
                            issue["severity"] = "warning"
                            for _q in batch:
                                if _q.get("question_id") == question_id:
                                    _q["needs_review"] = True
                                    _q["quality_warning"] = (
                                        issue.get("detail")
                                        or issue.get("issue_type")
                                        or "validation_warning"
                                    )
                                    break
                        all_issues.append(issue)
                    all_llm_results.append(q_result)

                # Merge bloom compliance summary
                batch_bloom = result.get("bloom_compliance_summary", {})
                for bloom, data in batch_bloom.items():
                    if bloom not in bloom_compliance:
                        bloom_compliance[bloom] = {"expected": 0, "actual": 0, "ok": True}
                    bloom_compliance[bloom]["expected"] = data.get("expected", 0)
                    bloom_compliance[bloom]["actual"] = data.get("actual", 0)
                    bloom_compliance[bloom]["ok"] = (
                        bloom_compliance[bloom]["ok"] and data.get("ok", True)
                    )

                scope_violations.extend(result.get("scope_violations", []))

                if batch_num < total_batches:
                    warnings.append(f"Batch {batch_num}/{total_batches} validated")

            except json.JSONDecodeError as e:
                warn_msg = f"Batch {batch_num} parse failed: {e}"
                warnings.append(warn_msg)
                # Validator infrastructure failed, not the questions. Keep this as
                # a review warning so good generated questions are not rebuilt
                # indefinitely because the critic returned non-JSON.
                for _bq in batch:
                    _bq["needs_review"] = True
                    _bq["quality_warning"] = (
                        f"validator_parse_failed: Batch {batch_num} response không parse được"
                    )
            except Exception as e:
                warn_msg = f"Batch {batch_num} failed: {e}"
                warnings.append(warn_msg)
                for _bq in batch:
                    _bq["needs_review"] = True
                    _bq["quality_warning"] = (
                        f"validator_failed: Batch {batch_num} exception"
                    )

        # G9: Save current issues to Redis
        if self.short_term and all_issues:
            try:
                await self.short_term.save_retry_issues(exam_id, all_issues)
            except Exception:
                pass

        critical_issues = [
            i for i in all_issues
            if is_retryable_validation_issue(i)
        ]
        validation_passed = len(critical_issues) == 0
        approved_for_publish = len(critical_issues) == 0

        # Check bloom compliance
        bloom_dist = exam_config.get("bloom_distribution", {})
        for bloom, config in bloom_dist.items():
            if bloom in bloom_compliance:
                compliance = bloom_compliance[bloom]
                expected = config
                actual = compliance.get("actual", 0)
                if abs(expected - actual) > 2:
                    warnings.append(
                        f"Bloom '{bloom}': expected {expected}, actual {actual} (diff > 2)"
                    )

        elapsed_ms = int((time.time() - start_time) * 1000)
        usage = metrics.prompt_tokens + metrics.completion_tokens

        status = AgentStatus.SUCCESS
        if not validation_passed:
            if len(critical_issues) > 0:
                status = AgentStatus.RETRY_NEEDED
            else:
                status = AgentStatus.PARTIAL

        return ValidatorOutput(
            status=status,
            agent_name="validator",
            execution_time_ms=elapsed_ms,
            token_usage=TokenUsage(
                prompt_tokens=metrics.prompt_tokens,
                completion_tokens=metrics.completion_tokens,
                total_tokens=usage,
            ),
            warnings=warnings,
            trace_id=trace_id,
            validation_passed=validation_passed,
            issues=all_issues,
            bloom_compliance=bloom_compliance,
            scope_violations=scope_violations,
            approved_for_publish=approved_for_publish,
        )

    def _build_validation_context(self, retrieved_context: list[dict] | None) -> str:
        """Build context string for validation prompt.

        Samples up to 50 chunks evenly across chapters so that
        all chapters in scope get represented, not just the first 20.
        """
        if not retrieved_context:
            return "Không có context — chỉ dựa vào câu hỏi để kiểm tra."

        # Group by chapter
        from collections import defaultdict
        by_chapter: dict[str, list[dict]] = defaultdict(list)
        for c in retrieved_context:
            by_chapter[c.get("chapter", "Unknown")].append(c)

        # Sample up to ceil(50 / num_chapters) chunks per chapter
        import math
        n_chapters = max(len(by_chapter), 1)
        per_chapter = max(1, math.ceil(50 / n_chapters))
        sampled: list[dict] = []
        for ch_chunks in by_chapter.values():
            sampled.extend(ch_chunks[:per_chapter])
        sampled = sampled[:50]  # hard cap

        chunks = [
            f"[{c.get('chunk_id', '?')}] {c.get('chapter', '')}: {c.get('content', '')[:300]}"
            for c in sampled
        ]
        return "\n\n".join(chunks)

    def _build_batch_prompt(
        self,
        batch: list[dict],
        context_str: str,
        exam_config: dict,
    ) -> str:
        """Build validation prompt for a batch of questions."""
        scope = exam_config.get("scope", [])
        bloom_dist = exam_config.get("bloom_distribution", {})
        questions_json = json.dumps(batch, ensure_ascii=False, indent=2)

        prompt = f"""Kiểm tra đề kiểm tra sau ({len(batch)} câu):

## Exam Config:
- Scope: {json.dumps(scope, ensure_ascii=False)}
- Bloom distribution: {json.dumps(bloom_dist, ensure_ascii=False, indent=2)}

## Questions:
{questions_json}

## Context có sẵn:
{context_str}

Thực hiện kiểm tra cho TỪNG CÂU:"""
        return prompt

    @staticmethod
    def _build_question_full_text(q: dict) -> str:
        """Combine ALL question text fields for scope checking (stem + options + propositions + solution + explanation)."""
        parts: list[str] = [q.get("stem", "") or ""]
        opts = q.get("options", {})
        if isinstance(opts, dict):
            parts.extend(v for v in opts.values() if v)
        for prop in (q.get("propositions") or []):
            if isinstance(prop, dict):
                parts.append(prop.get("text", "") or "")
        parts.append(q.get("solution", "") or "")
        parts.append(q.get("explanation", "") or "")
        return " ".join(p for p in parts if p)

    @staticmethod
    def _build_question_stem_text(q: dict) -> str:
        """Combine only stem + options + propositions for copy detection.

        Deliberately excludes solution/explanation: physics solutions legitimately
        repeat definitions and formulas from source material, which would cause
        false-positive copy alerts.
        """
        parts: list[str] = [q.get("stem", "") or ""]
        opts = q.get("options", {})
        if isinstance(opts, dict):
            parts.extend(v for v in opts.values() if v)
        for prop in (q.get("propositions") or []):
            if isinstance(prop, dict):
                parts.append(prop.get("text", "") or "")
        return " ".join(p for p in parts if p)

    @staticmethod
    def _trigram_copy_check(question_text: str, primary_chunks: list[dict]) -> dict:
        """Detect verbatim copy from context using normalized substring span matching.

        Policy (from design doc):
          - verbatim span >= 55 chars (normalized)  → hard fail
          - verbatim span >= 40 chars (normalized)  → soft flag (needs_review)
          - below 40 chars                          → clean

        Uses substring matching on normalized text (diacritics stripped, lowercased)
        instead of any-trigram set intersection, which was causing false positives
        from shared physics terminology appearing non-consecutively.
        """
        import unicodedata

        def _norm(text: str) -> str:
            nfd = unicodedata.normalize("NFD", text.lower())
            return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

        norm_q = _norm(question_text)
        if len(norm_q) < 40:
            return {"is_copy": False, "is_hard_fail": False, "span_len": 0, "detail": ""}

        HARD_SPAN = 55
        SOFT_SPAN = 40
        max_span = 0

        for chunk in primary_chunks[:20]:
            norm_ch = _norm(chunk.get("content", ""))
            if not norm_ch:
                continue
            # Sliding window: check every substring of question text of length >= SOFT_SPAN
            # against the chunk. Start from longest spans for early exit.
            for span_len in range(min(len(norm_q), 120), SOFT_SPAN - 1, -5):
                found = False
                for start in range(0, len(norm_q) - span_len + 1, 5):  # step=5 for speed
                    if norm_q[start:start + span_len] in norm_ch:
                        found = True
                        break
                if found:
                    if span_len > max_span:
                        max_span = span_len
                    break  # no need to check shorter spans for this chunk

        if max_span >= HARD_SPAN:
            return {
                "is_copy": True,
                "is_hard_fail": True,
                "span_len": max_span,
                "detail": f"Stem/options có đoạn {max_span} ký tự trùng nguyên văn context — nghi ngờ copy.",
            }
        if max_span >= SOFT_SPAN:
            return {
                "is_copy": True,
                "is_hard_fail": False,
                "span_len": max_span,
                "detail": f"Stem/options có đoạn {max_span} ký tự trùng context — cần xem lại.",
            }
        return {"is_copy": False, "is_hard_fail": False, "span_len": max_span, "detail": ""}


# ─── Unit test (runnable with: python -m pytest backend/app/agents/validator.py -v -k test_scope_violation) ───
# def test_scope_violation_detected():
#     """
#     Scenario: Question references Chapter 5 but allowed scope is only Chapter 1-3.
#
#     Setup:
#       questions = [
#           {
#               "question_id": "MCQ_001",
#               "stem": "Một vật chuyển động tròn đều có gia tốc hướng tâm a = 4 m/s², "
#                       "bán kính quỹ đạo r = 2 m. Tính tốc độ góc của vật.",
#               "type": "mcq",
#           }
#       ]
#       exam_config = {"scope": ["Chương 1: Động học chất điểm",
#                                "Chương 2: Động lực học chất điểm",
#                                "Chương 3: Tĩnh học"]}
#       retrieved_context = [
#           {"chunk_id": "c1", "content": "Chương 1: Động học chất điểm — các khái niệm cơ bản..."},
#           {"chunk_id": "c2", "content": "Chương 2: Động lực học chất điểm — các định luật Newton..."},
#           {"chunk_id": "c3", "content": "Chương 3: Tĩnh học — điều kiện cân bằng..."},
#       ]
#
#     Expected behaviour:
#       - scope_skill.run() → {"in_scope": False, "violation_type": "out_of_scope", ...}
#       - ValidatorAgent.validate() → issues contains a scope_violation entry for MCQ_001
#       - validation_passed = False (because scope issue was found)
#
#     Notes:
#       - validate_blueprint() is NOT called here (it's on the outline agent).
#       - The issue from scope_skill must be MERGED with any LLM-found issues
#         (not overwritten). See: issues = issues + llm_issues
# """
