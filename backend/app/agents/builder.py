"""Builder Agent - generates actual questions from blueprint slots."""

import logging
import time
import json
import asyncio
from typing import Any

# ─────────────────────────────────────────────────────────────
# Gemini Key Pool — async-safe round-robin fallback for builder
# ─────────────────────────────────────────────────────────────

class GeminiKeyPool:
    """Async-safe key pool for Gemini fallback. Each acquire() returns the next
    unused key across all slots, or None when the pool is exhausted."""

    def __init__(self, keys: list[str], max_rounds: int = 2) -> None:
        self._keys: list[str] = list(keys) * max_rounds if keys else []
        self._idx: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    async def acquire(self) -> str | None:
        """Return next available key, or None if pool exhausted."""
        async with self._lock:
            if self._idx >= len(self._keys):
                return None
            key = self._keys[self._idx]
            self._idx += 1
            return key

    @property
    def has_keys(self) -> bool:
        return bool(self._keys)


async def _call_gemini_slot(api_key: str, messages: list[dict], model: str) -> str:
    """Call Gemini via OpenAI-compatible endpoint (reuses openai SDK, no extra dep)."""
    from openai import AsyncOpenAI
    async with AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        max_retries=0,
    ) as client:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=8000,
            temperature=0.7,
        )
    return resp.choices[0].message.content or ""

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
- Think privately; do NOT output chain-of-thought, reasoning, analysis, planning, or self-check text
- Output only the final JSON array; no markdown fences, no prose before/after JSON

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
  "solution": "Lời giải mẫu ngắn gọn, nêu các ý chính và bước lập luận cần có để đạt điểm tối đa.",
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

Đúng-Sai Format (THPT 2025 — 4 mệnh đề, mỗi mệnh đề đúng hoặc sai):
{
  "question_id": "DS_001",
  "type": "dung_sai",
  "stem": "Đoạn dẫn mô tả tình huống/hiện tượng vật lý...",
  "propositions": [
    {"label": "a", "text": "Mệnh đề a...", "is_correct": true},
    {"label": "b", "text": "Mệnh đề b...", "is_correct": false},
    {"label": "c", "text": "Mệnh đề c...", "is_correct": true},
    {"label": "d", "text": "Mệnh đề d...", "is_correct": false}
  ],
  "explanation": "Giải thích từng mệnh đề: a) Đúng vì... b) Sai vì... c) Đúng vì... d) Sai vì...",
  "bloom_level": "van_dung",
  "chapter": "Chương 3"
}

Trả lời ngắn Format (THPT 2025 — điền kết quả số):
{
  "question_id": "SA_001",
  "type": "short_answer",
  "stem": "Câu hỏi yêu cầu tính toán, kết quả là một số...",
  "correct_answer": "3.14",
  "unit": "s",
  "solution": "Bước 1:... Bước 2:... Kết quả: 3.14 s",
  "bloom_level": "van_dung",
  "chapter": "Chương 1"
}

## QUY TẮC NỘI DUNG BẮT BUỘC:
- KHÔNG được output markdown heading (# ## ###) trong stem hoặc options
- KHÔNG được output tên heading của sách như "Chương 2: Khí lí tưởng" làm option
- KHÔNG được dùng boilerplate như "Theo nội dung đã học:", "Bài toán tổng hợp:", "Phân tích sâu và đánh giá:"
- KHÔNG được để options trùng nhau hoặc chứa nội dung giống hệt nhau
- Stem PHẢI là câu hỏi hoặc bài toán thực sự — có ít nhất 15 từ, có dấu hỏi hoặc yêu cầu rõ ràng
- Options MCQ PHẢI là câu trả lời thực sự (số, định nghĩa, phát biểu) — không được là tên chương hay heading
- Câu Đúng-Sai: mỗi mệnh đề phải là phát biểu khoa học cụ thể, có thể kiểm chứng
- Câu tự luận Essay BẮT BUỘC có field "solution" là lời giải mẫu/ý chính cần đạt; rubric chỉ là thang điểm, KHÔNG thay thế solution
- KHÔNG dùng "\\\\" để xuống dòng trong văn bản thường; nếu cần tách ý, dùng câu văn hoặc newline thật trong string

## QUY TẮC PHẠM VI KIẾN THỨC (CỰC KỲ QUAN TRỌNG):
- Phần ngữ cảnh được cung cấp gồm BA loại:
  - **KIẾN THỨC CỐT LÕI**: định nghĩa, công thức, định luật, định lý — đây là nguồn chính để sinh câu hỏi
  - **VÍ DỤ / BÀI TẬP THAM KHẢO**: ví dụ minh họa, bài tập mẫu, lời giải — CHỈ dùng để hiểu cách áp dụng kiến thức
  - **KIẾN THỨC NỀN (TIÊN QUYẾT)**: nội dung tiên quyết — CHỈ đọc để hiểu ngữ cảnh, TUYỆT ĐỐI KHÔNG sinh câu hỏi từ phần này
- **QUY TRÌNH BẮT BUỘC trước khi sinh câu hỏi**: Đọc context → Rút ra khái niệm, công thức, định luật và quan hệ cốt lõi → Sinh câu hỏi kiểm tra sự hiểu biết về những kiến thức đó
- **NGHIÊM CẤM**: copy, paraphrase, hoặc chỉ đổi số liệu từ ví dụ/bài tập mẫu trong context để tạo câu hỏi
- Ví dụ và bài tập mẫu KHÔNG được dùng làm stem trực tiếp, KHÔNG giữ nguyên cấu trúc bài, KHÔNG chỉ thay số liệu
- Câu hỏi phải bắt nguồn từ kiến thức cốt lõi; background chỉ được dùng để viết distractors hoặc giải thích rõ hơn

Trả về JSON array (không có key bọc ngoài):
[câu_hỏi_1]

## VÍ DỤ MẪU (few-shot — học format và mức Bloom, KHÔNG copy nội dung):

### Ví dụ 1 — nhan_biet / MCQ
Slot: {"type": "mcq", "bloom_level": "nhan_biet", "chapter": "Sóng điện từ"}
Output:
[{"type": "mcq", "bloom_level": "nhan_biet", "chapter": "Sóng điện từ", "stem": "Khi nói về sóng điện từ, phát biểu nào sau đây là đúng?", "options": {"A": "Khi truyền trong chân không, sóng điện từ không mang theo năng lượng.", "B": "Sóng điện từ có thể là sóng dọc hoặc sóng ngang.", "C": "Sóng điện từ luôn lan truyền với tốc độ c = 3.10^8 m/s.", "D": "Tốc độ truyền sóng điện từ phụ thuộc vào môi trường."}, "correct_answer": "D", "explanation": "Sóng điện từ luôn là sóng ngang và mang năng lượng. Trong chân không tốc độ là c, nhưng trong môi trường có chiết suất n thì v = c/n, tức phụ thuộc môi trường."}]

### Ví dụ 2 — thong_hieu / dung_sai
Slot: {"type": "dung_sai", "bloom_level": "thong_hieu", "chapter": "Nhiệt học — Các nguyên lý nhiệt động lực học"}
Output:
[{"type": "dung_sai", "bloom_level": "thong_hieu", "chapter": "Nhiệt học — Các nguyên lý nhiệt động lực học", "stem": "Vào những ngày mùa đông lạnh giá, một học sinh thực hiện việc xoa nhanh hai lòng bàn tay vào nhau trong một khoảng thời gian ngắn và cảm thấy tay ấm lên. Sau đó, học sinh này áp lòng bàn tay vào mặt của mình. Các nhận xét sau đúng hay sai?", "propositions": [{"label": "a", "text": "Nội năng của bàn tay tăng lên do nhận công.", "is_correct": true}, {"label": "b", "text": "Bàn tay đã nhận nhiệt lượng từ cơ thể và ấm lên.", "is_correct": false}, {"label": "c", "text": "Khi áp lòng bàn tay vào mặt, có sự truyền nhiệt lượng từ mặt vào bàn tay.", "is_correct": false}, {"label": "d", "text": "Trong toàn bộ quá trình từ lúc xoa tay đến lúc áp tay vào mặt, tổng năng lượng (bao gồm cơ năng và nhiệt năng) của hệ luôn được bảo toàn.", "is_correct": true}], "explanation": "a) Đúng: xoa tay thực hiện công thắng ma sát, cơ năng chuyển hóa thành nhiệt năng làm nội năng tay tăng. b) Sai: tay ấm lên do nhận công từ xoa, không phải nhận nhiệt từ cơ thể. c) Sai: sau khi xoa tay ấm hơn mặt, nhiệt truyền từ tay sang mặt chứ không phải ngược lại. d) Đúng: xét hệ gồm cơ thể, bàn tay, mặt và môi trường thì tổng năng lượng được bảo toàn."}]

### Ví dụ 3 — van_dung / short_answer
Slot: {"type": "short_answer", "bloom_level": "van_dung", "chapter": "Vật lí hạt nhân"}
Output:
[{"type": "short_answer", "bloom_level": "van_dung", "chapter": "Vật lí hạt nhân", "stem": "Một lò phản ứng hạt nhân dùng uranium ${}^{235}_{92}\\\\text{U}$, thanh nhiên liệu làm giàu 4%. Mỗi hạt nhân phân hạch tỏa 200 MeV, 90% năng lượng dùng làm nóng 500 tấn nước từ 30°C lên 250°C. Khi khối lượng ${}^{235}_{92}\\\\text{U}$ còn lại 99,5% so với ban đầu. Biết c = 4200 J/(kg.K), 1 mol ${}^{235}_{92}\\\\text{U}$ = 235 g, 1 MeV = $1{,}6\\\\times10^{-13}$ J. Khối lượng các thanh nhiên liệu ban đầu là bao nhiêu kilôgam?", "correct_answer": "31", "unit": "kg", "solution": "Khối lượng U phân hạch: $m_{ph} = 0{,}5\\\\% \\\\times 4\\\\% \\\\times m = 2\\\\times10^{-4}m$ (g). Từ $\\\\frac{m_{ph}}{M}N_A \\\\cdot \\\\Delta E \\\\cdot H = m_n c \\\\Delta T$ suy ra $m_{ph} \\\\approx 6{,}26$ g, do đó $m \\\\approx 31310$ g $\\\\approx 31$ kg."}]

### Ví dụ 4 — van_dung_cao / essay
Slot: {"type": "essay", "bloom_level": "van_dung_cao", "chapter": "Cơ học thiên thể — Định luật Kepler"}
Output (essay luôn phải có cả "solution" và "rubric"):
[{"type": "essay", "bloom_level": "van_dung_cao", "chapter": "Cơ học thiên thể — Định luật Kepler", "stem": "Trái Đất chuyển động quanh Mặt Trời theo quỹ đạo tròn bán kính $R_T = 150\\\\times10^9$ m với chu kỳ $T_0$ và vận tốc $v_T$. Một sao chổi chuyển động trong mặt phẳng quỹ đạo Trái Đất, đến gần Mặt Trời nhất ở khoảng cách $kR_T$ với vận tốc $v_1$. Cho k = 0,42; $v_T = 3\\\\times10^4$ m/s; $v_1 = 65{,}08\\\\times10^3$ m/s. (1) Xác định vận tốc v của sao chổi khi cắt quỹ đạo Trái Đất. (2) Chứng minh quỹ đạo là elip, xác định bán trục lớn $a = \\\\lambda R_T$, tâm sai e và chu kỳ $T = nT_0$. (3) Biểu diễn và tính gần đúng khoảng thời gian $\\\\tau$ sao chổi ở trong quỹ đạo Trái Đất.", "rubric": [{"score": 4, "description": "Giải đúng và đầy đủ cả 3 phần: tính v bằng bảo toàn năng lượng và mô men động lượng; chứng minh elip, tìm đúng $\\\\lambda, e, n$; biểu diễn $\\\\tau$ dưới dạng tích phân và tính được $\\\\tau \\\\approx 77$ ngày."}, {"score": 3, "description": "Giải đúng phần (1) và (2), phần (3) biểu diễn được tích phân nhưng tính gần đúng còn sai sót nhỏ hoặc chưa hoàn chỉnh."}, {"score": 2, "description": "Giải đúng phần (1), phần (2) tìm được $\\\\lambda$ hoặc e nhưng chưa đủ; phần (3) chưa làm hoặc sai."}, {"score": 1, "description": "Nêu được công thức bảo toàn năng lượng và mô men động lượng, lập được hệ phương trình nhưng chưa tính ra kết quả cụ thể nào."}]}]"""

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
- Options MCQ: đáp án đúng cần tính toán đúng; distractors là các bước tính sai phổ biến (quên ma sát, dùng sai công thức, tính nhầm đơn vị)
- BẮT BUỘC: Phải có ẩn số TRUNG GIAN — tức là phải tính một đại lượng phụ trước, mới tính được đáp án cuối
- KIỂM TRA: Nếu chỉ cần thay số vào đúng 1 công thức → đó là thong_hieu, KHÔNG ĐƯỢC gán van_dung""",

        "van_dung_cao": """## Hướng dẫn cho câu hỏi Vận dụng cao (van_dung_cao)
- Câu hỏi yêu cầu phân tích mối quan hệ, đánh giá, hoặc bài toán phức hợp nhiều bước
- Kết hợp ít nhất 2 định luật/công thức KHÁC NHAU, có dữ liệu thực tế, ẩn số trung gian
- Câu hỏi bắt đầu bằng: "Phân tích", "Đánh giá", "Xác định", bài toán có >=2 dữ kiện số ràng buộc
- Ví dụ stem tốt: "Mạch RLC nối tiếp, tụ C thay đổi được, điều chỉnh để $U_C$ đạt cực đại. Khi đó điện áp tức thời cực đại trên R là $12a$. Biết lúc $u=16a$ thì $u_C=7a$. Hệ thức nào đúng?"
- Ví dụ stem SAI (chỉ là van_dung): "Hai vật A và B nối bằng sợi dây qua ròng rọc. Tính gia tốc hệ."
- Options MCQ: đáp án đúng cần phân tích đúng toàn bộ hệ; distractors là lỗi phân tích phổ biến
- BẮT BUỘC: Kết hợp ít nhất 2 định luật/công thức KHÁC NHAU trong cùng bài toán
- BẮT BUỘC: Có ít nhất 1 đại lượng KHÔNG cho trực tiếp — phải suy ra từ điều kiện bài toán
- BẮT BUỘC: Lời giải/explanation phải có ít nhất 3 bước tường minh (Bước 1, Bước 2, Bước 3...)
- KIỂM TRA: Nếu không có bước thiết lập phương trình trung gian hoặc phân tích hệ → không đạt van_dung_cao

## VÍ DỤ VDC — MCQ (học cấu trúc độ khó, KHÔNG copy số liệu/chủ đề):
Slot: {"type": "mcq", "bloom_level": "van_dung_cao", "chapter": "Dòng điện xoay chiều"}
Output:
[{"type": "mcq", "bloom_level": "van_dung_cao", "chapter": "Dòng điện xoay chiều", "stem": "Mạch RLC nối tiếp, tụ C thay đổi được, điều chỉnh để $U_C$ đạt cực đại. Khi đó điện áp tức thời cực đại trên R là $12a$. Biết lúc $u = 16a$ thì $u_C = 7a$. Hệ thức nào đúng?", "options": {"A": "$4R = 3\\omega L$", "B": "$3R = 4\\omega L$", "C": "$R = 2\\omega L$", "D": "$2R = \\omega L$"}, "correct_answer": "B", "explanation": "Bước 1: Điều kiện $U_{C\\max}$: $Z_C = (R^2 + Z_L^2)/Z_L$, suy ra $\\tan\\varphi = -R/Z_L$. Bước 2: Vì $\\tan\\varphi \\cdot \\tan\\varphi_{RL} = -1$, $u$ và $u_{RL}$ vuông pha, lập hệ thức: $u^2 Z_L^2 + u_{RL}^2 R^2 = U_0^2 Z_L^2$. Bước 3: $u = 16a$, $u_C = 7a$ suy ra $u_{RL} = 9a$. Bước 4: Thế vào hệ thức: $256Z_L^2 + 81R^2 = 144(R^2+Z_L^2)$, rút gọn được $9R^2 = 16Z_L^2$, tức $3R = 4\\omega L$."}]

## VÍ DỤ VDC — DUNG_SAI (học cấu trúc độ khó, KHÔNG copy số liệu/chủ đề):
Slot: {"type": "dung_sai", "bloom_level": "van_dung_cao", "chapter": "Dòng điện xoay chiều"}
Output:
[{"type": "dung_sai", "bloom_level": "van_dung_cao", "chapter": "Dòng điện xoay chiều", "stem": "Cho mạch RLC nối tiếp: $u = 200\\sqrt{2}\\cos(100\\pi t)\\,\\text{V}$, $R = 100\\,\\Omega$, $L = 1/\\pi\\,\\text{H}$, $C = 10^{-4}/(2\\pi)\\,\\text{F}$. Mắc thêm tụ $C'$ song song với $C$ để công suất đạt cực đại. Xác định đúng/sai:", "propositions": [{"label": "a", "text": "Trước khi mắc thêm $C'$, mạch đang có tính cảm kháng.", "is_correct": false}, {"label": "b", "text": "Để công suất cực đại, cần thêm $C' = \\frac{10^{-4}}{2\\pi}\\,\\text{F}$.", "is_correct": true}, {"label": "c", "text": "Sau khi mắc thêm $C'$, điện áp hiệu dụng trên bộ tụ $(C+C')$ bằng điện áp hiệu dụng trên $L$.", "is_correct": true}, {"label": "d", "text": "Sau khi mắc thêm $C'$, công suất cực đại của mạch là $200\\,\\text{W}$.", "is_correct": false}], "explanation": "Bước 1: $Z_L = 100\\,\\Omega$, $Z_C = 200\\,\\Omega$; vì $Z_C > Z_L$ mạch có tính dung kháng, (a) sai. Bước 2: Cộng hưởng khi $Z_{C\\text{total}} = Z_L = 100\\,\\Omega$, suy ra $C' = 10^{-4}/(2\\pi)\\,\\text{F}$, (b) đúng. Bước 3: Cộng hưởng $\\Rightarrow U_L = U_{C+C'}$, (c) đúng. Bước 4: $P_{\\max} = U^2/R = 400\\,\\text{W} \\neq 200\\,\\text{W}$, (d) sai."}]

## VÍ DỤ VDC — SHORT_ANSWER (học cấu trúc độ khó, KHÔNG copy số liệu/chủ đề):
Slot: {"type": "short_answer", "bloom_level": "van_dung_cao", "chapter": "Dao động cơ"}
Output:
[{"type": "short_answer", "bloom_level": "van_dung_cao", "chapter": "Dao động cơ", "stem": "Hai vật A, B cùng khối lượng $m = 200\\,\\text{g}$, nối dây dài $l = 20\\,\\text{cm}$. A gắn lò xo $k = 40\\,\\text{N/m}$, lò xo ban đầu tự nhiên. Hệ số ma sát $\\mu = 0{,}1$ với cả hai vật, $g = 10\\,\\text{m/s}^2$. Kéo B để lò xo giãn $6\\,\\text{cm}$ rồi thả. Tính khoảng cách giữa A và B khi cả hai dừng hẳn.", "correct_answer": "8", "unit": "cm", "solution": "Bước 1: Hệ (A+B) dao động quanh VTCB lệch $x_I = \\mu Mg/k = 1\\,\\text{cm}$; biên độ $A_1 = 5\\,\\text{cm}$. Bước 2: Dây chùng tại $x = 0$; $v^2 = \\omega^2(A_1^2 - x_I^2) = 2400\\,\\text{cm}^2/\\text{s}^2$. Bước 3: B trượt tự do $s_B = v^2/(2\\mu g) = 12\\,\\text{cm}$; dừng tại $x_B = 20 - 12 = 8\\,\\text{cm}$ tính từ A ban đầu. Bước 4: A dao động tắt dần một mình, dừng tại $x_A = 0$ (lực đàn hồi = 0 không thắng ma sát nghỉ). Bước 5: Khoảng cách = $x_B - x_A = 8\\,\\text{cm}$."}]

## VÍ DỤ VDC — ESSAY (học cấu trúc độ khó, KHÔNG copy số liệu/chủ đề):
Slot: {"type": "essay", "bloom_level": "van_dung_cao", "chapter": "Nhiệt động lực học"}
Output:
[{"type": "essay", "bloom_level": "van_dung_cao", "chapter": "Nhiệt động lực học", "stem": "Bình trụ đứng có tiết diện $S = 23\\,\\text{cm}^2$, dưới piston nặng $P = 10\\,\\text{N}$ chứa khí lý tưởng đơn nguyên tử. Ban đầu piston cách đáy $h = 30\\,\\text{cm}$; vòng chắn không cho piston vượt quá $H = 50\\,\\text{cm}$. Cho $p_0 = 100\\,\\text{kPa}$. (a) Tính áp suất ban đầu của khí. (b) Khi truyền nhiệt, xác định các giai đoạn của quá trình và nhiệt lượng khí nhận trong từng giai đoạn. (c) Tính tổng nhiệt lượng để áp suất cuối tăng gấp $\\alpha = 1{,}5$ lần áp suất ban đầu.", "solution": "Bước 1: Cân bằng piston ban đầu cho $p_1 = p_0 + P/S \\approx 1{,}043\\times10^5\\,\\text{Pa}$. Bước 2: Khi piston còn chuyển động tự do, quá trình đẳng áp từ $V_1 = Sh$ đến $V_2 = SH$, nên $Q_{12} = \\frac{5}{2}p_1S(H-h) \\approx 120\\,\\text{J}$. Bước 3: Khi piston chạm vòng chắn, thể tích không đổi và áp suất tăng từ $p_1$ đến $\\alpha p_1$, nên $Q_{23} = \\frac{3}{2}SH(\\alpha - 1)p_1 \\approx 90\\,\\text{J}$. Bước 4: Tổng nhiệt lượng $Q = Q_{12}+Q_{23} \\approx 210\\,\\text{J}$; điểm then chốt là nhận ra điều kiện chuyển từ đẳng áp sang đẳng tích.", "rubric": [{"score": 2, "description": "Tính đúng áp suất ban đầu từ cân bằng lực lên piston."}, {"score": 3, "description": "Nhận diện đúng hai giai đoạn đẳng áp rồi đẳng tích và điều kiện piston chạm vòng chắn."}, {"score": 3, "description": "Áp dụng đúng nhiệt lượng khí đơn nguyên tử cho từng giai đoạn, tính được $Q_{12}$ và $Q_{23}$."}, {"score": 2, "description": "Tổng hợp đúng kết quả và giải thích vai trò của ràng buộc vòng chắn."}]}]""",
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
    MAX_CONCURRENT_LLM_CALLS = 2  # semaphore limit to avoid rate limits
    CHUNK_SIZE = 5  # questions per LLM call

    def __init__(self, redis_client=None):
        self.llm = get_llm_client()
        self.guardrails = GuardrailsPipeline()
        self.bloom_skill = BloomClassifierSkill()
        self.dedup_skill = DedupCheckerSkill()
        self.difficulty_skill = DifficultyEstimatorSkill()
        self.latex_skill = LatexRendererSkill()
        self.redis = redis_client

    @tracer.agent_span("builder_single")
    async def build_single_question(
        self,
        question_id: str,
        retrieved_context: list[dict],
        extra_prompt: str = "",
        existing_questions: list[dict] | None = None,
        trace_id: str = "",
    ) -> dict | None:
        """
        Regenerate a single question by question_id with an optional prompt.

        Used by the partial-regenerate endpoint at CP2 so teachers can
        refine individual questions without triggering full pipeline restart.

        Finds the existing question's slot metadata (type, bloom, chapter) and
        calls _generate_single_slot with extra_prompt injected into scope_restriction.

        Returns the regenerated question dict, or None on failure.
        """
        existing_questions = existing_questions or []

        # Find the existing question to get its slot metadata
        existing_q = next(
            (q for q in existing_questions if q.get("question_id") == question_id),
            None,
        )
        if not existing_q:
            logger.warning("build_single_question: question_id %r not found", question_id)
            return None

        # Reconstruct a blueprint slot from the existing question.
        # Section metadata fields must be carried forward so the validator's
        # section-scope check works correctly in partial-regenerate paths.
        _SECTION_META_FIELDS = (
            "primary_section_id", "primary_section_title", "primary_scope_unit_key",
            "secondary_section_ids", "secondary_section_titles", "secondary_scope_unit_keys",
        )
        slot: dict = {
            "question_id": question_id,
            "type": existing_q.get("type", "mcq"),
            "bloom_level": existing_q.get("bloom_level", "thong_hieu"),
            "chapter": existing_q.get("chapter", ""),
            "section": existing_q.get("section", ""),
            "topic_hint": existing_q.get("topic_hint", ""),
            "estimated_difficulty": existing_q.get("estimated_difficulty", 0.5),
            "content_type": existing_q.get("content_type", "text"),
        }
        for _f in _SECTION_META_FIELDS:
            _v = existing_q.get(_f)
            if _v is not None:
                slot[_f] = _v

        # Build chapter-filtered context
        context_all = self._build_context_for_llm(retrieved_context)
        chapter = slot.get("chapter", "")
        topic_context_map = self._build_topic_context_map(retrieved_context)
        topic_chunks = topic_context_map.get(chapter, [])
        question_context = (
            self._build_context_for_llm(topic_chunks) if topic_chunks else context_all[:8000]
        )

        # Inject extra_prompt as additional scope_restriction line
        scope_restriction = ""
        if extra_prompt:
            scope_restriction = (
                f"## Yêu cầu chỉnh sửa từ giảng viên (PHẢI tuân theo):\n{extra_prompt}\n"
            )

        topics_used = [q.get("topic_hint", "") for q in existing_questions]

        from app.core.config import get_settings as _gcfg
        _sq_pool: GeminiKeyPool | None = None
        _sqkeys = _gcfg().GEMINI_KEYS
        if _sqkeys:
            _sq_pool = GeminiKeyPool(_sqkeys)

        question, warnings = await self._generate_single_slot(
            slot=slot,
            context=context_all[:8000],
            question_context=question_context,
            scope_restriction=scope_restriction,
            topics_used=topics_used,
            slot_number=0,
            gemini_key_pool=_sq_pool,
        )

        if warnings:
            logger.info(
                "build_single_question %r warnings: %s",
                question_id, "; ".join(warnings),
            )

        # Mirror full-build path: copy section metadata from slot → question
        # so validator's section-scope check has the correct fields.
        if question:
            for _f in _SECTION_META_FIELDS:
                _v = slot.get(_f)
                if _v is not None:
                    question[_f] = _v

        return question

    @tracer.agent_span("builder_agent")
    async def build(
        self,
        blueprint: list[dict],
        retrieved_context: list[dict],
        topics_used: list[str] | None = None,
        allowed_concepts: list[str] | None = None,
        scope_chapters: list[str] | None = None,
        trace_id: str = "",
        correction_strategies: dict[str, str] | None = None,
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

            # Single budget check for all chunks combined
            budget_status = self.guardrails.check_budget(8000 * len(blueprint_chunks))
            flush_mode = budget_status == "flush_needed"
            if budget_status == "stop":
                warnings.append("Token budget exhausted. Cannot generate questions.")
            else:
                if flush_mode:
                    warnings.append("Token budget flush needed — using reduced context")

                context_to_use = reduced_context_for_llm if flush_mode else context_for_llm
                topics_snapshot = list(topics_used)

                # Create Gemini key pool (shared across all slots for this build run)
                from app.core.config import get_settings as _gcfg
                _gemini_pool: GeminiKeyPool | None = None
                _gkeys = _gcfg().GEMINI_KEYS
                if _gkeys:
                    _gemini_pool = GeminiKeyPool(_gkeys)
                    logger.info("GeminiKeyPool ready: %d keys × 2 rounds = %d slots", len(_gkeys), len(_gkeys) * 2)

                # Global semaphore — shared across ALL chunks so total concurrent
                # LLM calls never exceeds MAX_CONCURRENT_LLM_CALLS regardless of
                # how many chunks run in parallel.
                _global_sem = asyncio.Semaphore(self.MAX_CONCURRENT_LLM_CALLS)
                logger.info("Global semaphore: max %d concurrent LLM calls", self.MAX_CONCURRENT_LLM_CALLS)

                # Launch all chunks in parallel — each gets an independent topics copy
                chunk_tasks = [
                    self._generate_chunk(
                        chunk=bp_chunk,
                        context=context_to_use,
                        retrieved_context=retrieved_context,
                        scope_restriction=scope_restriction,
                        topics_used=list(topics_snapshot),
                        slot_start_index=i * self.CHUNK_SIZE,
                        total_slots=len(blueprint),
                        correction_strategies=correction_strategies,
                        gemini_key_pool=_gemini_pool,
                        semaphore=_global_sem,
                    )
                    for i, bp_chunk in enumerate(blueprint_chunks)
                ]
                chunk_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)

                for chunk_idx, result in enumerate(chunk_results):
                    if isinstance(result, Exception):
                        warnings.append(f"Chunk {chunk_idx} failed: {result}")
                        # Instead of silently dropping all slots in this chunk,
                        # generate a demo fallback for each slot so question count
                        # always matches the blueprint.
                        failed_chunk_slots = blueprint_chunks[chunk_idx]
                        for _slot in failed_chunk_slots:
                            _demo = self._build_demo_question(_slot, "")
                            all_questions.append(_demo)
                            if _demo.get("topic_hint"):
                                topics_used.append(_demo["topic_hint"])
                            warnings.append(
                                f"Slot {_slot.get('question_id', '?')} used demo fallback due to chunk failure"
                            )
                        continue

                    questions, chunk_warnings = result
                    warnings.extend(chunk_warnings)
                    metrics.completion_tokens += len(questions) * 50  # Estimate

                    real_questions = [q for q in questions if not q.get("is_demo_question")]
                    demo_questions = [q for q in questions if q.get("is_demo_question")]

                    validated = self.guardrails.validate_batch(real_questions)

                    for q in validated:
                        if not q.get("filter_passed", True):
                            # Mark-and-keep instead of drop: question count must match blueprint.
                            # Flag it so the teacher can see it needs attention, but don't discard it.
                            warn_msg = f"Question {q.get('question_id')} failed filter: {q.get('filter_error')}"
                            warnings.append(warn_msg)
                            logger.warning(warn_msg)
                            q["needs_review"] = True
                            q["quality_warning"] = q.get("filter_error", "Failed quality check")
                            # Fall through — append below

                        stem = q.get("stem") or q.get("content") or ""
                        if stem and allowed_concepts:
                            in_scope, violation = scope_guard.is_allowed(stem)
                            if not in_scope:
                                warn_msg = f"Question {q.get('question_id')} out of scope: {violation}"
                                warnings.append(warn_msg)
                                logger.warning(warn_msg)
                                # Mark out-of-scope but still keep in output
                                q["needs_review"] = True
                                q["quality_warning"] = violation or "Out of scope"

                        if not q.get("source_evidence") and q.get("evidence_chunks"):
                            q["source_evidence"] = [
                                {
                                    "chunk_id": ev.get("chunk_id", ""),
                                    "content": ev.get("text", ev.get("content", "")),
                                    "page_number": ev.get("page_number"),
                                    "section": ev.get("section_id", ""),
                                    "relevance_score": ev.get("score", 1.0),
                                }
                                for ev in q.get("evidence_chunks", [])
                                if isinstance(ev, dict)
                            ]

                        all_questions.append(q)
                        if q.get("topic_hint"):
                            topics_used.append(q["topic_hint"])
                        if q.get("evidence_chunks"):
                            chunks_referenced.extend(q["evidence_chunks"])

                    for q in demo_questions:
                        all_questions.append(q)
                        if q.get("topic_hint"):
                            topics_used.append(q["topic_hint"])

            # Build output
            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = metrics.prompt_tokens + metrics.completion_tokens
            status = AgentStatus.SUCCESS
            if blueprint and not all_questions:
                warnings.append("Builder produced 0 questions from a non-empty blueprint.")
                status = AgentStatus.PARTIAL

            _real_count = sum(1 for q in all_questions if not q.get("is_demo_question"))
            _demo_count = sum(1 for q in all_questions if q.get("is_demo_question"))
            _review_count = sum(1 for q in all_questions if q.get("needs_review"))
            logger.info(
                "Builder finished: %d questions total (real=%d, demo=%d, needs_review=%d) "
                "from %d blueprint slots — elapsed=%dms",
                len(all_questions), _real_count, _demo_count, _review_count,
                len(blueprint), elapsed_ms,
            )
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
            logger.error("Builder top-level exception after %d questions: %s", len(all_questions), e, exc_info=True)

            # Generate demo fallback for any blueprint slots not yet covered
            covered_ids = {q.get("question_id") for q in all_questions}
            for _slot in blueprint:
                if _slot.get("question_id") not in covered_ids:
                    _demo = self._build_demo_question(_slot, "")
                    all_questions.append(_demo)
                    warnings.append(
                        f"Slot {_slot.get('question_id', '?')} used demo fallback due to builder exception"
                    )

            logger.info(
                "Builder finished (partial): %d questions from %d slots",
                len(all_questions), len(blueprint),
            )
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
        correction_strategies: dict[str, str] | None = None,
        gemini_key_pool: GeminiKeyPool | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> tuple[list[dict], list[str]]:
        """Generate questions for a blueprint chunk IN PARALLEL using semaphore.

        Semaphore is shared globally across all chunks (passed from build()) so
        MAX_CONCURRENT_LLM_CALLS is a hard cap for the entire builder run, not
        per-chunk. Falls back to a local semaphore if called without one.
        """
        warnings: list[str] = []
        semaphore = semaphore or asyncio.Semaphore(self.MAX_CONCURRENT_LLM_CALLS)

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

        _correction_strategies = correction_strategies or {}

        async def _generate_one_with_semaphore(
            slot: dict,
            slot_number: int,
        ) -> tuple[int, dict | None, list[str]]:
            """Generate one question with semaphore limiting concurrency."""
            async with semaphore:
                # ── Section-aware chunk selection ─────────────────────────────────
                import unicodedata as _ud
                def _norm_sec(s: str) -> str:
                    nfd = _ud.normalize("NFD", s.strip().lower())
                    return "".join(c for c in nfd if _ud.category(c) != "Mn")

                primary_sec_id    = slot.get("primary_section_id") or ""
                primary_sec_title = slot.get("primary_section_title") or slot.get("section") or ""
                secondary_sec_ids  = set(slot.get("secondary_section_ids") or [])
                secondary_sec_titles = {
                    _norm_sec(t) for t in (slot.get("secondary_section_titles") or []) if t
                }

                def _is_primary_chunk(c: dict) -> bool:
                    if c.get("role") == "background":
                        return False
                    if primary_sec_id and c.get("section_id") == primary_sec_id:
                        return True
                    if primary_sec_title and _norm_sec(c.get("section", "")) == _norm_sec(primary_sec_title):
                        return True
                    return False

                def _is_secondary_chunk(c: dict) -> bool:
                    if c.get("role") == "background":
                        return False
                    sec_id = c.get("section_id", "")
                    if sec_id and sec_id in secondary_sec_ids:
                        return True
                    sec_title_norm = _norm_sec(c.get("section", ""))
                    if sec_title_norm and sec_title_norm in secondary_sec_titles:
                        return True
                    return False

                sec_primary_chunks   = [c for c in retrieved_context if _is_primary_chunk(c)]
                sec_secondary_chunks = [c for c in retrieved_context if _is_secondary_chunk(c)]
                section_chunks = sec_primary_chunks + sec_secondary_chunks

                # ── Chapter-level fallback (existing logic) ───────────────────────
                slot_chapter = slot.get("chapter", "Unknown")
                slot_section = slot.get("section", "") or ""
                topic_key = f"{slot_chapter} > {slot_section}" if slot_section else slot_chapter
                topic_chunks = topic_context_map.get(topic_key, [])
                match_path = "exact" if topic_chunks else ""
                if not topic_chunks:
                    norm_key = self._normalize_chapter_key(slot_chapter)
                    topic_chunks = norm_context_map.get(norm_key, [])
                    if topic_chunks:
                        match_path = "normalized"
                # Try chapter_id match (ch2 -> chunks from that namespace)
                if not topic_chunks:
                    ch_id = normalize_chapter_id(slot_chapter)
                    topic_chunks = chid_context_map.get(ch_id, [])
                    if topic_chunks:
                        match_path = "chapter_id"
                # Last resort: pick any chunks whose normalized key contains the chapter number
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

                # Prefer section-level chunks; fall back to chapter-level
                if section_chunks:
                    topic_chunks = section_chunks
                    match_path = f"section({'id' if sec_primary_chunks else 'title'})"

                # Collect background (prereq) chunks from full retrieved_context.
                background_chunks = [
                    c for c in retrieved_context if c.get("role") == "background"
                ]

                # Build context: primary topic chunks + background chunks (role-separated)
                combined_for_slot = (topic_chunks if topic_chunks else []) + background_chunks
                question_context_str = (
                    self._build_context_for_llm(combined_for_slot)
                    if combined_for_slot
                    else context[:8000]
                )
                logger.info(
                    "Slot %d chapter=%r section=%r → %d chunks (path: %s)",
                    slot_number,
                    slot_chapter,
                    primary_sec_title or primary_sec_id or "",
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
                    correction_strategy=_correction_strategies.get(slot.get("question_id", ""), ""),
                    gemini_key_pool=gemini_key_pool,
                )

                # Copy section metadata from slot into question for traceability
                if question:
                    for _field in (
                        "primary_section_id", "primary_section_title", "primary_scope_unit_key",
                        "secondary_section_ids", "secondary_section_titles",
                        "secondary_scope_unit_keys",
                    ):
                        _val = slot.get(_field)
                        if _val is not None:
                            question[_field] = _val

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
        correction_strategy: str = "",
        gemini_key_pool: GeminiKeyPool | None = None,
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
                except Exception as exc:
                    logger.debug("SerpAPI search failed (non-critical): %s", exc)

        # Inject Validator's targeted correction instruction when retrying a failed question
        negotiation_block = ""
        if correction_strategy:
            negotiation_block = (
                f"\n## ⚠️ YÊU CẦU SỬA LỖI TỪ VALIDATOR (PHẢI TUÂN THEO NGHIÊM NGẶT):\n"
                f"{correction_strategy}\n"
                f"Đây là lần sinh lại — câu hỏi cũ đã bị từ chối vì lý do trên. "
                f"KHÔNG lặp lại lỗi cũ.\n"
            )

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
{negotiation_block}
{bloom_guide}
{distractor_guide}

## Yêu cầu:
- Sinh đúng MỘT câu hỏi duy nhất theo blueprint slot trên
- Câu hỏi phải thuộc mức Bloom: {bloom}
- Chỉ dùng kiến thức trong phạm vi đã cho
- Trả lời đúng một JSON array chứa đúng một object câu hỏi, không thêm gì khác

Đây là JSON array MỘT câu hỏi:"""

        # Retry malformed/partial primary output before falling back. Provider/API
        # exceptions still fall through to fallback immediately to avoid 429 spam.
        max_retries = 2
        # VDC gate correction hint — updated on each failed gate check, injected into next attempt
        vdc_correction = ""
        for attempt in range(max_retries + 1):
            try:
                response = await self.llm.chat(
                    messages=[
                        {"role": "system", "content": self.BUILDER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt + vdc_correction},
                    ],
                    role="builder",
                    max_tokens=8000,
                    temperature=0.7,
                )

                if not response or not response.strip():
                    msg = f"Slot {slot_number}: primary builder returned empty response (attempt {attempt + 1})"
                    warnings.append(msg)
                    logger.warning(msg)
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
                    first_json_pos = next((i for i, ch in enumerate(clean) if ch in ("{", "[")), -1)
                    if first_json_pos >= 0:
                        msg = f"Slot {slot_number}: primary builder returned incomplete/unextractable JSON (attempt {attempt + 1})"
                    else:
                        msg = f"Slot {slot_number}: primary builder returned no JSON (attempt {attempt + 1})"
                    warnings.append(msg)
                    logger.warning(
                        "%s | len=%d first_json_pos=%d prefix=%r suffix=%r",
                        msg,
                        len(clean),
                        first_json_pos,
                        clean[:500],
                        clean[-500:],
                    )
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
                        msg = f"Slot {slot_number}: primary builder JSON parse error after sanitize+repair"
                        warnings.append(msg)
                        logger.warning("%s | char=%s msg=%s snippet=%r", msg, je.pos, je.msg, repaired[max(0, je.pos - 20):je.pos + 40])
                        continue

                # Normalize: data can be {"questions": [...]} or [...]
                questions_raw: list = []
                if isinstance(data, list):
                    questions_raw = data
                elif isinstance(data, dict):
                    questions_raw = data.get("questions", [data])

                if not questions_raw:
                    msg = f"Slot {slot_number}: primary builder parsed JSON but found no questions (attempt {attempt + 1})"
                    warnings.append(msg)
                    logger.warning(msg)
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

                # Build propositions for Đúng-Sai
                if q_type == "dung_sai" and "propositions" not in q:
                    q["propositions"] = [
                        {"label": "a", "text": "Mệnh đề a", "is_correct": True},
                        {"label": "b", "text": "Mệnh đề b", "is_correct": False},
                        {"label": "c", "text": "Mệnh đề c", "is_correct": True},
                        {"label": "d", "text": "Mệnh đề d", "is_correct": False},
                    ]

                # Build answer for Short Answer
                if q_type == "short_answer" and "correct_answer" not in q:
                    q["correct_answer"] = ""
                    q["unit"] = ""
                    q["solution"] = ""

                # Build rubric for Essay
                if q_type == "essay" and "rubric" not in q:
                    q["rubric"] = [
                        {"score": 10, "description": "Hoàn toàn chính xác"},
                        {"score": 7, "description": "Đúng nhưng thiếu chi tiết"},
                        {"score": 4, "description": "Sai sót một phần"},
                        {"score": 0, "description": "Sai hoàn toàn"},
                    ]
                    q["estimated_solve_time_minutes"] = 15
                if q_type == "essay" and not q.get("solution"):
                    q["solution"] = (
                        q.get("sample_answer")
                        or q.get("model_answer")
                        or q.get("expected_answer")
                        or "Lời giải mẫu cần trình bày đầy đủ các ý chính trong rubric."
                    )

                # Apply skill pipeline (non-blocking)
                await self._apply_skill_pipeline(q, topics_used)

                # VDC hard gate: structural quality check — retry within budget if fails
                if bloom == "van_dung_cao":
                    gate_passed, gate_reason = self._check_vdc_quality(q)
                    if not gate_passed and attempt < max_retries:
                        vdc_correction = (
                            f"\n\n## ⚠️ CÂU HỎI VỪA SINH CHƯA ĐẠT MỨC VẬN DỤNG CAO:\n"
                            f"Lý do: {gate_reason}\n"
                            f"Yêu cầu bắt buộc khi sinh lại:\n"
                            f"- Lời giải/explanation phải có ít nhất 3 bước tường minh (Bước 1, Bước 2, Bước 3...)\n"
                            f"- Stem phải cung cấp ít nhất 2 dữ kiện số/điều kiện ràng buộc khác nhau\n"
                            f"- Phải kết hợp ít nhất 2 định luật/công thức khác nhau\n"
                            f"- Phải có đại lượng trung gian phải tính trước mới ra được đáp án\n"
                            f"- KHÔNG phải dạng thay số vào 1 công thức hoặc nhận xét định tính đơn giản\n"
                        )
                        warn_msg = f"Slot {slot_number}: VDC gate fail (attempt {attempt + 1}) — {gate_reason}, retrying"
                        warnings.append(warn_msg)
                        logger.warning(warn_msg)
                        continue  # retry in budget
                    elif not gate_passed:
                        # Budget exhausted — mark but keep
                        q["needs_review"] = True
                        q["quality_warning"] = f"bloom_mismatch: {gate_reason}"
                        q["difficulty_score"] = min(float(q.get("difficulty_score") or 0.5), 0.55)
                        q["estimated_difficulty"] = min(float(q.get("estimated_difficulty") or 0.5), 0.55)
                        warn_msg = f"Slot {slot_number}: VDC gate fail after all retries — {gate_reason}"
                        warnings.append(warn_msg)
                        logger.warning(warn_msg)

                logger.info(f"Slot {slot_number} generated ok (attempt {attempt + 1})")
                return q, warnings

            except json.JSONDecodeError as e:
                msg = f"Slot {slot_number}: primary builder JSON parse error (attempt {attempt + 1}): {e}"
                warnings.append(msg)
                logger.warning(msg)
                if attempt == max_retries:
                    break

            except Exception as e:
                msg = f"Slot {slot_number}: primary builder LLM error (attempt {attempt + 1}): {e}"
                warnings.append(msg)
                logger.warning(msg)
                break

        # ── Primary provider exhausted — try Gemini key pool ──
        if gemini_key_pool is not None and gemini_key_pool.has_keys:
            logger.warning(
                "Slot %d: primary builder failed; entering Gemini fallback. reasons=%s",
                slot_number,
                " | ".join(warnings[-5:]) if warnings else "unknown",
            )
            from app.core.config import get_settings as _gcfg
            _gmodel = _gcfg().GEMINI_MODEL
            _gmessages = [
                {"role": "system", "content": self.BUILDER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            while True:
                _gkey = await gemini_key_pool.acquire()
                if _gkey is None:
                    logger.warning("Slot %d: Gemini key pool exhausted — using demo question", slot_number)
                    warnings.append(f"Slot {slot_number}: Gemini pool exhausted, using demo question")
                    break
                try:
                    _gresp = await _call_gemini_slot(_gkey, _gmessages, _gmodel)
                    if not _gresp or not _gresp.strip():
                        continue
                    _clean = _gresp.strip()
                    if _clean.startswith("`"):
                        _gl = [_l for _l in _clean.split("\n") if not _l.strip().startswith("```")]
                        _clean = "\n".join(_gl).strip()
                    _jstr = _extract_json_brackets(_clean)
                    if not _jstr:
                        continue
                    _jstr = _sanitize_latex_escapes(_jstr)
                    try:
                        _gdata = json.loads(_jstr, strict=False)
                    except json.JSONDecodeError:
                        try:
                            _gdata = json.loads(_repair_json_string(_jstr), strict=False)
                        except json.JSONDecodeError:
                            continue
                    _graw: list = _gdata if isinstance(_gdata, list) else (_gdata.get("questions", [_gdata]) if isinstance(_gdata, dict) else [])
                    if not _graw:
                        continue
                    q = _graw[0]
                    if "question_id" not in q: q["question_id"] = q_id
                    if "type" not in q: q["type"] = q_type
                    if "bloom_level" not in q: q["bloom_level"] = bloom
                    if "chapter" not in q: q["chapter"] = chapter
                    q["estimated_difficulty"] = difficulty
                    if q_type == "mcq" and "options" not in q:
                        q["options"] = {"A": "Đáp án A", "B": "Đáp án B", "C": "Đáp án C", "D": "Đáp án D"}
                        q["correct_answer"] = "A"; q["explanation"] = "Đáp án đúng là A."
                    if q_type == "dung_sai" and "propositions" not in q:
                        q["propositions"] = [{"label": l, "text": f"Mệnh đề {l}", "is_correct": l in ("a", "c")} for l in "abcd"]
                    if q_type == "short_answer" and "correct_answer" not in q:
                        q["correct_answer"] = ""; q["unit"] = ""; q["solution"] = ""
                    if q_type == "essay" and "rubric" not in q:
                        q["rubric"] = [{"score": s, "description": d} for s, d in [(10, "Hoàn toàn chính xác"), (7, "Đúng nhưng thiếu chi tiết"), (4, "Sai sót một phần"), (0, "Sai hoàn toàn")]]
                        q["estimated_solve_time_minutes"] = 15
                    if q_type == "essay" and not q.get("solution"):
                        q["solution"] = (
                            q.get("sample_answer")
                            or q.get("model_answer")
                            or q.get("expected_answer")
                            or "Lời giải mẫu cần trình bày đầy đủ các ý chính trong rubric."
                        )
                    await self._apply_skill_pipeline(q, topics_used)
                    logger.info("Slot %d: Gemini fallback succeeded", slot_number)
                    warnings.append(f"Slot {slot_number}: Used Gemini key fallback")
                    return q, warnings
                except Exception as _ge:
                    logger.warning("Slot %d: Gemini key failed: %s — trying next", slot_number, str(_ge)[:120])
                    continue

        # ── All fallbacks exhausted — demo question ──
        logger.warning(f"Slot {slot_number}: All LLM retries failed — using demo question")
        warnings.append(f"Slot {slot_number}: LLM failed after {max_retries + 1} attempts, using demo question")
        demo_q = self._build_demo_question(slot, effective_context)
        return demo_q, warnings

    @staticmethod
    def _check_vdc_quality(q: dict) -> tuple[bool, str]:
        """Structural gate for van_dung_cao questions.

        Checks question complexity without any LLM call.
        Returns (passed, reason_if_failed).
        """
        import re
        stem: str = q.get("stem", "")
        q_type: str = q.get("type", "mcq")

        # Pick the richest text field for step counting
        detail_text = ""
        if q_type == "mcq":
            detail_text = str(q.get("explanation", "") or "")
        elif q_type == "dung_sai":
            detail_text = str(q.get("explanation", "") or "")
        elif q_type == "short_answer":
            detail_text = str(q.get("solution", "") or "")
        elif q_type == "essay":
            rubric = q.get("rubric", [])
            if isinstance(rubric, list):
                detail_text = " ".join(
                    r.get("description", "") if isinstance(r, dict) else str(r)
                    for r in rubric
                )
            elif isinstance(rubric, str):
                detail_text = rubric
            detail_text += " " + str(q.get("solution", "") or "")

        # 1. Multi-step check: look for explicit step markers. Normalize
        # Vietnamese diacritics first so both "Bước 1" and "Buoc 1" match.
        import unicodedata
        detail_norm = unicodedata.normalize("NFD", detail_text)
        detail_norm = "".join(
            ch for ch in detail_norm
            if unicodedata.category(ch) != "Mn"
        ).lower()
        step_count = len(re.findall(r"\b(?:buoc|step)\s*\d+", detail_norm))
        if step_count < 3:
            return False, f"chỉ có {step_count} bước tường minh trong lời giải (cần ≥3)"

        # 2. Numerical data / conditions in stem
        numbers_in_stem = re.findall(r"\d+[.,]?\d*\s*(?:[a-zA-Zμ°Ωπ]+|\\text\{[^}]+\})??", stem)
        if len(numbers_in_stem) < 2:
            return False, f"stem chỉ có {len(numbers_in_stem)} dữ kiện số (cần ≥2)"

        # 3. Math symbols present (LaTeX, operators)
        math_hits = len(re.findall(r"\$[^$]+\$|\\[a-zA-Z]+|[=+\-*/^]", stem))
        if math_hits < 2:
            return False, "stem thiếu ký hiệu toán học / công thức"

        # 4. Stem length — trivially short stems cannot be VDC
        if len(stem) < 80:
            return False, f"stem quá ngắn ({len(stem)} ký tự, cần ≥80)"

        return True, ""

    async def _apply_skill_pipeline(self, q: dict, topics_used: list[str]) -> None:
        """Run skill pipeline on a question (non-blocking, errors are swallowed)."""
        # bloom_classified is an audit-only field — bloom_level is already set from
        # the blueprint slot. Use the keyword-based fallback to avoid an extra LLM
        # call per question (which was causing 429 rate-limit spikes after few-shot
        # examples were added to BloomClassifierSkill).
        try:
            bloom_result = self.bloom_skill._fallback_classify(q.get("stem", ""))
            q["bloom_classified"] = bloom_result.get("bloom_level")
        except Exception as exc:
            logger.debug("bloom_skill fallback failed for %s: %s", q.get("question_id"), exc)

        try:
            diff_result = await self.difficulty_skill.run(
                question_stem=q.get("stem", ""),
                bloom_level=q.get("bloom_level", "thong_hieu"),
            )
            q["difficulty_score"] = diff_result.get("difficulty_score", 0.5)
        except Exception as exc:
            logger.debug("difficulty_skill failed for %s: %s", q.get("question_id"), exc)

        try:
            dedup_result = await self.dedup_skill.run(
                new_question_topic=q.get("stem", ""),
                existing_topics=topics_used,
            )
            if dedup_result.get("is_duplicate"):
                q["dedup_warning"] = dedup_result.get("suggestion")
        except Exception as exc:
            logger.debug("dedup_skill failed for %s: %s", q.get("question_id"), exc)

        if q.get("latex_content"):
            try:
                latex_result = self.latex_skill.run(raw_formula=q["latex_content"])
                q["latex_rendered"] = latex_result
            except Exception as exc:
                logger.debug("latex_skill failed for %s: %s", q.get("question_id"), exc)

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
            demo_q["solution"] = (
                "Lời giải mẫu cần nêu các ý chính, lập luận vật lí phù hợp và "
                "trình bày rõ các bước xử lí theo yêu cầu của đề."
            )
            demo_q["estimated_solve_time_minutes"] = 15

        if q_type == "dung_sai":
            demo_q["stem"] = snippet[:200] if snippet else f"Hiện tượng liên quan đến {chapter}"
            demo_q["propositions"] = [
                {"label": "a", "text": "Mệnh đề a (demo)", "is_correct": True},
                {"label": "b", "text": "Mệnh đề b (demo)", "is_correct": False},
                {"label": "c", "text": "Mệnh đề c (demo)", "is_correct": True},
                {"label": "d", "text": "Mệnh đề d (demo)", "is_correct": False},
            ]
            demo_q["explanation"] = "Câu hỏi demo. Vui lòng tạo lại đề."

        if q_type == "short_answer":
            demo_q["stem"] = snippet[:200] if snippet else f"Tính đại lượng liên quan đến {chapter}"
            demo_q["correct_answer"] = "0"
            demo_q["unit"] = ""
            demo_q["solution"] = "Câu hỏi demo. Vui lòng tạo lại đề."

        if bloom == "van_dung_cao":
            demo_q["needs_review"] = True
            demo_q["quality_warning"] = (
                "bloom_mismatch: VDC used demo fallback, not enough evidence "
                "that the question reaches van_dung_cao complexity"
            )
            demo_q["difficulty_score"] = min(float(demo_q.get("estimated_difficulty") or 0.5), 0.55)
            demo_q["estimated_difficulty"] = min(float(demo_q.get("estimated_difficulty") or 0.5), 0.55)

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

    # Keywords used to classify chunks into core-knowledge vs example/exercise
    _EXERCISE_KEYWORDS = (
        "ví dụ", "vi du", "bài tập", "bai tap", "lời giải", "loi giai",
        "bài giải", "bai giai", "hướng dẫn giải", "huong dan giai",
        "đáp số", "dap so", "kết quả:", "ket qua:", "giải:", "giai:",
        "solution", "example", "exercise",
    )
    _THEORY_KEYWORDS = (
        "định nghĩa", "dinh nghia", "định luật", "dinh luat",
        "định lý", "dinh ly", "nguyên lý", "nguyen ly",
        "công thức", "cong thuc", "khái niệm", "khai niem",
        "tính chất", "tinh chat", "hệ quả", "he qua",
        "phát biểu", "phat bieu", "theorem", "definition", "law",
    )

    @classmethod
    def _classify_chunk(cls, chunk: dict) -> str:
        """Classify a chunk as 'theory', 'exercise', or 'background'.

        Returns one of: 'theory' | 'exercise' | 'background'
        Priority: background role > exercise keywords > formula/theory markers.

        Exercise keywords are checked BEFORE content_type == 'formula' because
        physics worked examples almost always contain LaTeX formulas — checking
        formula first would wrongly classify them as theory.
        """
        if chunk.get("role") == "background":
            return "background"
        content_lower = (chunk.get("content") or "").lower()
        # Exercise keywords take highest priority — must check before formula tag
        # because worked examples in physics routinely contain LaTeX formulas.
        for kw in cls._EXERCISE_KEYWORDS:
            if kw in content_lower:
                return "exercise"
        # Chunks whose content_type is 'formula' are core knowledge (standalone formulas)
        if chunk.get("content_type") == "formula" or chunk.get("latex_repr"):
            return "theory"
        # Check theory keywords
        for kw in cls._THEORY_KEYWORDS:
            if kw in content_lower:
                return "theory"
        # Default: treat as theory (safer — LLM is already instructed not to paraphrase)
        return "theory"

    def _build_context_for_llm(self, retrieved_context: list[dict]) -> str:
        """Build a context string for the LLM prompt.

        Chunks are split into three clearly-labelled sections:
          1. KIẾN THỨC CỐT LÕI — definitions, formulas, laws (primary generation source)
          2. VÍ DỤ / BÀI TẬP THAM KHẢO — examples, worked solutions (reference only)
          3. KIẾN THỨC NỀN (TIÊN QUYẾT) — background/prereq chunks (context only)

        The LLM is instructed in BUILDER_SYSTEM_PROMPT to extract core concepts from
        section 1 first, and NOT to paraphrase section 2 directly into question stems.
        """
        theory_chunks: list[dict] = []
        exercise_chunks: list[dict] = []
        background_chunks: list[dict] = []

        for chunk in retrieved_context:
            label = self._classify_chunk(chunk)
            if label == "background":
                background_chunks.append(chunk)
            elif label == "exercise":
                exercise_chunks.append(chunk)
            else:
                theory_chunks.append(chunk)

        def _format_by_chapter(chunks: list[dict], max_per_chapter: int = 5) -> str:
            by_chapter: dict[str, list[str]] = {}
            for chunk in chunks:
                chapter = chunk.get("chapter", "Unknown")
                section = chunk.get("section", "")
                key = f"{chapter} › {section}" if section else chapter
                if key not in by_chapter:
                    by_chapter[key] = []
                content = chunk.get("content", "")
                latex = chunk.get("latex_repr")
                if latex:
                    content = f"{content}\n[Công thức: {latex}]"
                by_chapter[key].append(content)

            parts = []
            for key, contents in by_chapter.items():
                parts.append(f"### {key}")
                for c in contents[:max_per_chapter]:
                    parts.append(f"- {c[:500]}")
                parts.append("")
            return "\n".join(parts)

        sections: list[str] = []

        if theory_chunks:
            sections.append(
                "## KIẾN THỨC CỐT LÕI\n"
                "*(Dùng phần này làm nguồn kiến thức chính. Trước khi sinh câu hỏi, "
                "hãy rút ra khái niệm, công thức, định luật và quan hệ cốt lõi. "
                "Sinh câu hỏi kiểm tra sự hiểu biết về những kiến thức này — "
                "KHÔNG copy, KHÔNG paraphrase, KHÔNG chỉ đổi số liệu.)*\n"
            )
            sections.append(_format_by_chapter(theory_chunks))

        if exercise_chunks:
            # Fallback: if no theory chunks found, instruct LLM to extract implicit
            # core knowledge from the examples rather than copying their structure.
            if not theory_chunks:
                ex_header = (
                    "## VÍ DỤ / BÀI TẬP (nguồn kiến thức duy nhất — dùng thận trọng)\n"
                    "*(Không có chunk lý thuyết thuần tuý trong context này. "
                    "Hãy rút ra kiến thức cốt lõi ẩn trong các ví dụ (công thức, định luật, quan hệ vật lý) "
                    "rồi sinh câu hỏi kiểm tra kiến thức đó — KHÔNG sao chép cấu trúc bài, "
                    "KHÔNG chỉ thay số liệu.)*\n"
                )
            else:
                ex_header = (
                    "## VÍ DỤ / BÀI TẬP THAM KHẢO\n"
                    "*(Chỉ dùng để hiểu cách áp dụng kiến thức. "
                    "TUYỆT ĐỐI KHÔNG dùng làm stem trực tiếp, "
                    "KHÔNG giữ nguyên cấu trúc bài, KHÔNG chỉ thay số liệu.)*\n"
                )
            sections.append(ex_header)
            sections.append(_format_by_chapter(exercise_chunks, max_per_chapter=3))

        if background_chunks:
            sections.append(
                "## KIẾN THỨC NỀN (TIÊN QUYẾT)\n"
                "*(KHÔNG sinh câu hỏi từ phần này — chỉ dùng để hiểu ngữ cảnh "
                "và giải thích khái niệm tiên quyết.)*\n"
            )
            sections.append(_format_by_chapter(background_chunks, max_per_chapter=3))

        return "\n".join(sections)

    def _build_topic_context_map(self, retrieved_context: list[dict]) -> dict[str, list[dict]]:
        """Build a dict mapping topic/chapter to relevant chunks for per-question context filtering.

        Instead of dumping ALL chunks into every question prompt (wasting tokens),
        each question only gets chunks relevant to its chapter/topic.

        Keys include both chapter titles AND chapter_ids for flexible matching.
        """
        topic_map: dict[str, list[dict]] = {}
        for chunk in retrieved_context:
            chapter = chunk.get("chapter", "") or chunk.get("metadata", {}).get("chapter", "Unknown")
            chapter_id = chunk.get("chapter_id", "") or chunk.get("metadata", {}).get("chapter_id", "")
            section = chunk.get("section", "") or chunk.get("metadata", {}).get("section", "")
            key = f"{chapter} > {section}" if section else chapter
            if key not in topic_map:
                topic_map[key] = []
            topic_map[key].append(chunk)
            # Also index by chapter_id (e.g., "ch2") so blueprint slots can match
            if chapter_id and chapter_id != chapter:
                if chapter_id not in topic_map:
                    topic_map[chapter_id] = []
                topic_map[chapter_id].append(chunk)
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
