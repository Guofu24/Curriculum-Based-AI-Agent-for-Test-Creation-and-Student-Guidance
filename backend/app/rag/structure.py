"""Structure detection: heading tree building from markdown."""

import re
from dataclasses import dataclass, field
from typing import Any

logger = __import__("logging").getLogger("rag.structure")

# ── Heading style classification ──────────────────────────────────────────────
# Unambiguous chapter keywords (Chương, Chapter, Module, Unit)
_RE_KEYWORD_CH = re.compile(
    r"^(chuong|chapter|module|unit)\s+\d+",
    re.IGNORECASE,
)
# Ambiguous keywords that are chapters in some docs, sections in others
_RE_WEAK_KW = re.compile(
    r"^(bai|phan|part)\s+\d+",
    re.IGNORECASE,
)
# Uppercase-only Roman numeral prefix: I., II., ... — IGNORECASE intentionally omitted
# so that lowercase "ii. $formula$" is NOT matched.
_RE_ROMAN_PREFIX = re.compile(r"^[IVXLCDM]{1,6}\.\s")
_RE_LETTER_PREFIX = re.compile(r"^[A-Z]\.\s+\S")
_RE_DECIMAL = re.compile(r"^\d+\.\d+")
_RE_NUMBER_DOT = re.compile(r"^\d+\.\s+\S")
_RE_GARBAGE_SECTION = re.compile(
    r"^(bai\s*tap|huong\s*dan|dap\s*so|dap\s*an|phu\s*luc|muc\s*luc|"
    r"loi\s*noi\s*dau|loi\s*mo\s*dau|tai\s*lieu\s*tham\s*khao)",
    re.IGNORECASE,
)

_STYLE_KEYWORD_CH = "KEYWORD_CHAPTER"   # Chương N, Chapter N, Module N
_STYLE_LETTER_CH  = "LETTER_CHAPTER"    # A., B., C., ... (uppercase only)
_STYLE_ROMAN_CH   = "ROMAN_CHAPTER"     # I., II., III., ... (uppercase only)
_STYLE_WEAK_CH    = "WEAK_CHAPTER"      # ALL CAPS, 1. TITLE, Bài N, Phần N
_STYLE_SEC_D2     = "SECTION_D2"
_STYLE_SEC_D3     = "SECTION_D3"
_STYLE_GARBAGE    = "GARBAGE"
_STYLE_UNKNOWN    = "UNKNOWN"


@dataclass
class SubsectionNode:
    """A subsection within a section."""
    section_id: str
    title: str


@dataclass
class SectionNode:
    """A section within a chapter."""
    section_id: str
    title: str
    subsections: list[SubsectionNode] = field(default_factory=list)


@dataclass
class ChapterNode:
    """A chapter in the document."""
    chapter_id: str
    title: str
    sections: list[SectionNode] = field(default_factory=list)


def _is_heading_chapter_level(title: str) -> bool:
    """
    Returns True if a heading title looks like a chapter-level heading
    regardless of its markdown # depth. Used to promote e.g. '## II. Something'
    or '## A. Title' to chapter level in the tree.
    """
    import unicodedata
    norm = unicodedata.normalize("NFD", title.lower())
    ascii_title = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    return bool(
        re.match(r"^[ivxldcm]+\.\s", ascii_title) or
        re.match(r"^[a-z]\.\s", ascii_title)
    )


def extract_headings_with_context(
    markdown: str,
    context_chars: int = 150,
) -> list[dict]:
    """
    Extract all # headings from markdown, each paired with the content
    preview that immediately follows it (up to context_chars characters).

    Returns a list of dicts:
      {
        "level": int,           # 1-4 (number of #)
        "heading": str,         # full heading text
        "context": str,         # content preview after heading
        "line_number": int,     # 0-based line index in markdown
      }
    """
    lines = markdown.split("\n")
    result: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m and len(m.group(2).strip()) > 1:
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            # Collect content lines until next heading or 3 non-empty lines
            content_parts: list[str] = []
            non_empty_count = 0
            j = i + 1
            while j < len(lines) and non_empty_count < 3:
                next_line = lines[j].strip()
                next_m = re.match(r"^#{1,4}\s+", next_line)
                if next_m:
                    break
                if next_line:
                    content_parts.append(next_line)
                    non_empty_count += 1
                j += 1
            context = " ".join(content_parts)[:context_chars].strip()
            result.append({
                "level": level,
                "heading": heading_text,
                "context": context,
                "line_number": i,
            })
        i += 1
    return result


def _is_likely_heading(line: str, line_index: int, total_lines: int) -> int:
    """
    Heuristic: does `line` look like a heading even without # markers?
    Returns heading level (1-3) if it looks like a heading, 0 otherwise.

    Patterns checked:
    - Short line (under 80 chars) followed by paragraph text
    - Numbered chapter/section patterns: "Chương 1", "1.1", "Bài 1", "Section", "Chapter"
    - Line is ALL CAPS or Title Case with few words
    - Short standalone line at start of page
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return 0

    # Numbered chapter/section patterns (very common in textbooks)
    chapter_patterns = [
        r"^chương\s+\d+",           # Chương 1, Chương 10
        r"^bài\s+\d+",              # Bài 1, Bài 10
        r"^\d+\.\d+",               # 1.1, 2.3.4
        r"^\d+\s+\.",                # 1 . Title, 2 . Title
        r"^chapter\s+\d+",           # Chapter 1
        r"^section\s+\d+",         # Section 1
        r"^part\s+\d+",             # Part 1
        r"^module\s+\d+",           # Module 1
        r"^unit\s+\d+",             # Unit 1
        r"^phần\s+\d+",             # Phần 1
        r"^bai\s+\d+",              # bai 1 (lowercase)
        r"^[IVXLCDM]+\.\s+",         # Roman numeral prefix: "II. LƯỠNG...", "III. Something"
        r"^[A-Z]\.\s+",            # Letter prefix: "A. QUANG...", "B. CÁI..."
    ]

    # Section patterns (second level)
    section_patterns = [
        r"^\d+\.\d+\s",             # 1.1 Title
        r"^\d+\.\d+\.",             # 1.1.
        r"^mục\s+\d+",             # Mục 1
        r"^tiểu mục\s+\d+",        # Tiểu mục 1
        r"^\(\d+\)",               # (1), (2)
        r"^\d+\)",                  # 1) Title
    ]
    for pat in section_patterns:
        if re.search(pat, stripped, re.IGNORECASE):
            return 2  # Section level

    # All-caps short line (likely a heading)
    if stripped.isupper() and len(stripped) >= 3 and len(stripped.split()) <= 8:
        return 1

    # Title Case: mostly capitalized words, short line, not a sentence
    words = stripped.split()
    if 1 <= len(words) <= 10:
        # Count Title/ALL words
        title_words = sum(1 for w in words if w[0].isupper() if w)
        if title_words / len(words) >= 0.7:
            # Check it's not a sentence (doesn't end with typical sentence endings)
            if stripped[-1] not in ".!?:;":
                return 2

    return 0


def _build_tree_from_nodes(
    headings: list[tuple[int, str]],
) -> dict:
    """
    Convert a flat list of (level, title) headings into the nested tree format.
    """
    chapters: list[ChapterNode] = []
    current_chapter: ChapterNode | None = None
    current_section: SectionNode | None = None

    for level, title in headings:
        if level == 1:
            current_chapter = ChapterNode(
                chapter_id=f"ch{len(chapters) + 1}",
                title=title,
                sections=[],
            )
            chapters.append(current_chapter)
            current_section = None

        elif level == 2:
            if current_chapter is None:
                current_chapter = ChapterNode(
                    chapter_id=f"ch{len(chapters) + 1}",
                    title="",
                    sections=[],
                )
                chapters.append(current_chapter)

            current_section = SectionNode(
                section_id=f"{current_chapter.chapter_id}_sec{len(current_chapter.sections) + 1}",
                title=title,
                subsections=[],
            )
            current_chapter.sections.append(current_section)

        elif level == 3:
            if current_chapter is None:
                current_chapter = ChapterNode(
                    chapter_id=f"ch{len(chapters) + 1}",
                    title="",
                    sections=[],
                )
                chapters.append(current_chapter)

            if current_section is None:
                current_section = SectionNode(
                    section_id=f"{current_chapter.chapter_id}_sec{len(current_chapter.sections) + 1}",
                    title="",
                    subsections=[],
                )
                current_chapter.sections.append(current_section)

            current_section.subsections.append(
                SubsectionNode(
                    section_id=f"{current_section.section_id}_sub{len(current_section.subsections) + 1}",
                    title=title,
                )
            )

    return {
        "chapters": [
            {
                "chapter_id": ch.chapter_id,
                "title": ch.title,
                "sections": [
                    {
                        "section_id": s.section_id,
                        "title": s.title,
                        "subsections": [
                            {"section_id": sub.section_id, "title": sub.title}
                            for sub in s.subsections
                        ],
                    }
                    for s in ch.sections
                ],
            }
            for ch in chapters
        ]
    }


def _heading_style(title: str) -> str:
    """Classify a heading title into a style bucket for hierarchy inference."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", title.strip())
    norm = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    norm_lower = norm.lower()

    # GARBAGE first — catches "BÀI TẬP" before "BÀI N" keyword check
    if _RE_GARBAGE_SECTION.match(norm_lower):
        return _STYLE_GARBAGE

    if _RE_KEYWORD_CH.match(norm_lower):
        return _STYLE_KEYWORD_CH

    # Single-letter prefix (A., B., C., D. ...) checked BEFORE Roman so that
    # C./D./L./M. are not misidentified as Roman numerals C=100/D=500.
    if _RE_LETTER_PREFIX.match(norm):
        return _STYLE_LETTER_CH

    # Multi-char Romans (II., III., IV., ...) won't match LETTER_PREFIX above.
    if _RE_ROMAN_PREFIX.match(norm):
        return _STYLE_ROMAN_CH

    # Ambiguous keywords: Bài N, Phần N, Part N
    if _RE_WEAK_KW.match(norm_lower):
        return _STYLE_WEAK_CH

    # Decimal section: 1.1, 2.3.4
    if _RE_DECIMAL.match(norm):
        depth = len(norm.split()[0].split("."))
        return _STYLE_SEC_D3 if depth >= 3 else _STYLE_SEC_D2

    # ALL CAPS short title
    if title.strip().isupper() and 3 <= len(title.strip()) <= 80:
        return _STYLE_WEAK_CH

    # Numbered chapter: "1. TITLE"
    if _RE_NUMBER_DOT.match(norm):
        return _STYLE_WEAK_CH

    return _STYLE_UNKNOWN


def infer_heading_levels(headings: list[dict]) -> list[dict]:
    """
    Normalize heading levels using whole-document context.

    Input: list of dicts with at least {"level": int, "heading": str}
           (same format as extract_headings_with_context output).

    Returns a new list with corrected "level" values (1=chapter, 2=section,
    3=subsection) based on global title-pattern distribution, not individual
    heading markdown depth.

    O(n) time. No LLM.

    Algorithm:
      1. Classify each heading into style bucket.
      2. Find anchor markdown level (the depth at which chapter-style headings
         appear in THIS document — Gemini sometimes dumps all at ##).
      3. Map each heading to a true structural level based on style + anchor.
    """
    if not headings:
        return headings

    classified = [(h, _heading_style(h["heading"])) for h in headings]
    styles = {s for _, s in classified}

    _ch_styles = {_STYLE_KEYWORD_CH, _STYLE_LETTER_CH, _STYLE_ROMAN_CH}
    has_any_ch = bool(styles & _ch_styles)
    has_weak   = _STYLE_WEAK_CH in styles
    has_letter = _STYLE_LETTER_CH in styles

    if not has_any_ch and not has_weak:
        return headings  # no chapter signals — trust original markdown levels

    # Anchor: shallowest markdown level where a chapter-style heading lives.
    # Fixes Gemini outputs where all headings land at the same ## depth.
    if has_any_ch:
        anchor = min(h["level"] for h, s in classified if s in _ch_styles)
    else:
        anchor = min(h["level"] for h, s in classified if s == _STYLE_WEAK_CH)

    result: list[dict] = []
    for h, style in classified:
        new_h = dict(h)

        if style in {_STYLE_KEYWORD_CH, _STYLE_LETTER_CH}:
            new_h["level"] = 1

        elif style == _STYLE_ROMAN_CH:
            # When letter-prefix chapters (A., B., C.) exist, Romans are typically
            # sections under them. When no letters exist, Romans are top-level chapters.
            new_h["level"] = 2 if has_letter else 1

        elif style == _STYLE_WEAK_CH:
            new_h["level"] = 1 if not has_any_ch else 2

        elif style in (_STYLE_SEC_D2, _STYLE_GARBAGE):
            new_h["level"] = 2

        elif style == _STYLE_SEC_D3:
            new_h["level"] = 3

        else:  # UNKNOWN — use relative markdown depth against chapter anchor
            rel = h["level"] - anchor + 1
            computed = max(1, rel)
            if has_any_ch and computed == 1:
                computed = 2
            new_h["level"] = min(computed, 3)

        result.append(new_h)

    return result


def detect_heading_tree(markdown: str) -> dict:
    """
    Parse markdown heading tags (#, ##, ###) into a nested heading tree.
    Falls back to heuristic pattern detection if no # headings are found.

    Returns a dict with chapters/sections/subsections hierarchy per spec:
    {
      "chapters": [
        {
          "chapter_id": "ch1",
          "title": "Chương 1: Động lực học",
          "sections": [
            {"section_id": "ch1_sec1", "title": "1.1 Lực và phân loại lực", "subsections": []}
          ]
        }
      ]
    }
    """
    lines = markdown.split("\n")
    chapters: list[ChapterNode] = []
    current_chapter: ChapterNode | None = None
    current_section: SectionNode | None = None

    chapter_counter = 0
    found_any_heading = False

    # Pre-pass: globally normalize heading levels across the whole document
    _raw: list[dict] = [
        {"level": len(m.group(1)), "heading": m.group(2).strip(), "context": "", "line_number": i}
        for i, ln in enumerate(lines)
        if (m := re.match(r"^(#{1,3})\s+(.+)$", ln.strip()))
    ]
    _level_map: dict[int, int] = {
        h["line_number"]: h["level"] for h in infer_heading_levels(_raw)
    }

    for line_idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if not heading_match:
            continue

        found_any_heading = True
        level = _level_map.get(line_idx, len(heading_match.group(1)))
        title = heading_match.group(2).strip()

        if level == 1:
            chapter_counter += 1
            current_chapter = ChapterNode(
                chapter_id=f"ch{chapter_counter}",
                title=title,
                sections=[],
            )
            chapters.append(current_chapter)
            current_section = None

        elif level == 2:
            if current_chapter is None:
                chapter_counter = 1
                current_chapter = ChapterNode(
                    chapter_id=f"ch{chapter_counter}",
                    title="",
                    sections=[],
                )
                chapters.append(current_chapter)

            base = current_chapter.chapter_id
            current_section = SectionNode(
                section_id=f"{base}_sec{len(current_chapter.sections) + 1}",
                title=title,
                subsections=[],
            )
            current_chapter.sections.append(current_section)

        elif level == 3:
            if current_chapter is None:
                chapter_counter = 1
                current_chapter = ChapterNode(
                    chapter_id=f"ch{chapter_counter}",
                    title="",
                    sections=[],
                )
                chapters.append(current_chapter)

            if current_section is None:
                base = current_chapter.chapter_id
                current_section = SectionNode(
                    section_id=f"{base}_sec{len(current_chapter.sections) + 1}",
                    title="",
                    subsections=[],
                )
                current_chapter.sections.append(current_section)

            sub = SubsectionNode(
                section_id=f"{current_section.section_id}_sub{len(current_section.subsections) + 1}",
                title=title,
            )
            current_section.subsections.append(sub)

    # If no # headings were found, use heuristic fallback to detect
    # structure from numbered patterns, all-caps lines, etc.
    if not found_any_heading:
        logger.info("No # headings found, using heuristic pattern detection")
        heuristic_headings: list[tuple[int, str]] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            level = _is_likely_heading(stripped, idx, len(lines))
            if level > 0:
                heuristic_headings.append((level, stripped))

        if heuristic_headings:
            logger.info("Heuristic detected %d potential headings", len(heuristic_headings))
            return _build_tree_from_nodes(heuristic_headings)

    return {
        "chapters": [
            {
                "chapter_id": ch.chapter_id,
                "title": ch.title,
                "sections": [
                    {
                        "section_id": s.section_id,
                        "title": s.title,
                        "subsections": [
                            {"section_id": sub.section_id, "title": sub.title}
                            for sub in s.subsections
                        ],
                    }
                    for s in ch.sections
                ],
            }
            for ch in chapters
        ]
    }


def _sanitize_json_backslashes(s: str) -> str:
    """Double bare backslashes inside JSON strings so json.loads doesn't fail on LaTeX."""
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(s):
        c = s[i]
        if in_string:
            if c == "\\":
                nc = s[i + 1] if i + 1 < len(s) else ""
                if nc in '"\\/ bfnrtu':
                    result.append(c)
                    result.append(nc)
                    i += 2
                else:
                    result.append("\\\\")
                    i += 1
            elif c == '"':
                in_string = False
                result.append(c)
                i += 1
            else:
                result.append(c)
                i += 1
        else:
            if c == '"':
                in_string = True
            result.append(c)
            i += 1
    return "".join(result)


def _extract_partial_json(text: str) -> dict:
    """
    Recover partial JSON when the LLM response is truncated mid-string.
    Walks backwards from the end to find the last position where we can
    close the JSON structure cleanly, then appends the missing brackets.
    Returns {"chapters": []} on total failure.
    """
    import json

    # Try truncating at each '}' from the end
    for i in range(len(text) - 1, -1, -1):
        if text[i] == "}":
            candidate = text[: i + 1]
            # Count unclosed brackets to determine what to append
            opens = candidate.count("{") - candidate.count("}")
            arr_opens = candidate.count("[") - candidate.count("]")
            suffix = "]" * max(arr_opens, 0) + "}" * max(opens, 0)
            try:
                return json.loads(candidate + suffix)
            except json.JSONDecodeError:
                continue
    return {"chapters": []}


def _compress_pdf_for_vision(pdf_bytes: bytes) -> bytes:
    """
    Compress PDF trước khi gửi Gemini vision:
    - Downsample ảnh xuống 72 DPI (đủ để nhận diện heading, không cần hi-res)
    - Strip metadata thừa
    Trả về bytes gốc nếu compress thất bại.
    """
    try:
        import fitz  # PyMuPDF
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        dst = fitz.open()
        for page in src:
            # Render trang ở 72 DPI rồi embed lại thành ảnh JPEG
            mat = fitz.Matrix(72 / 72, 72 / 72)  # identity — giữ layout
            pix = page.get_pixmap(matrix=fitz.Matrix(72 / 96, 72 / 96), alpha=False)
            img_page = dst.new_page(width=pix.width, height=pix.height)
            img_page.insert_image(
                img_page.rect,
                stream=pix.tobytes(output="jpeg", jpg_quality=60),
            )
        compressed = dst.tobytes(deflate=True, garbage=4, clean=True)
        src.close()
        dst.close()
        ratio = len(compressed) / len(pdf_bytes) * 100
        logger.info(
            "[gemini_pdf] Compressed PDF: %.1f KB → %.1f KB (%.0f%%)",
            len(pdf_bytes) / 1024, len(compressed) / 1024, ratio,
        )
        return compressed
    except Exception as e:
        logger.warning("[gemini_pdf] Compress failed (%s), using original", e)
        return pdf_bytes


def _normalize_gemini_pdf_result(result: dict) -> dict:
    """Normalize chapter/section IDs từ raw Gemini PDF output."""
    import json as _json
    chapters = result.get("chapters", [])
    for i, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict):
            continue
        ch["chapter_id"] = f"ch{i}"
        ch.setdefault("title", f"Chapter {i}")
        ch.setdefault("sections", [])
        secs = []
        for j, sec in enumerate(ch.get("sections", []), 1):
            if isinstance(sec, str):
                sec = {"title": sec}
            if isinstance(sec, dict):
                sec["section_id"] = f"ch{i}_sec{j}"
                sec.setdefault("title", f"Section {j}")
                sec.setdefault("subsections", [])
                secs.append(sec)
        ch["sections"] = secs

    raw_prereqs = result.get("prerequisites", {})
    prerequisites: dict = {}
    for ch_idx_str, dep_list in (raw_prereqs.items() if isinstance(raw_prereqs, dict) else []):
        try:
            ch_id = f"ch{int(ch_idx_str)}"
            dep_ids = []
            for d in (dep_list if isinstance(dep_list, list) else []):
                try:
                    dep_ids.append(f"ch{int(d)}")
                except (ValueError, TypeError):
                    pass
            if dep_ids:
                prerequisites[ch_id] = dep_ids
        except (ValueError, TypeError):
            pass

    return {
        "chapters": [c for c in chapters if isinstance(c, dict) and c.get("chapter_id")],
        "prerequisites": prerequisites,
    }


async def _run_gemini_pdf_vision(pdf_bytes: bytes) -> dict | None:
    """
    Gửi PDF (đã compress) lên Gemini vision để nhận diện heading.
    Trả về normalized dict hoặc None nếu fail/timeout.
    """
    try:
        from app.rag.embedder import _get_gemini_client, settings as _emb_settings
        import json as _json
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        keys = _emb_settings.GEMINI_EMBED_KEYS
        if not keys:
            logger.warning("[gemini_pdf] No GEMINI_KEYS available")
            return None

        compressed = _compress_pdf_for_vision(pdf_bytes)

        key = keys[0]
        client = _get_gemini_client(key)

        prompt = (
            "Phân tích cấu trúc chương mục của tài liệu PDF này (có thể là scan).\n\n"
            "CHỈ trả về CHƯƠNG và MỤC có nội dung LÝ THUYẾT / KHÁI NIỆM thực sự.\n\n"
            "QUY TẮC BỎ QUA (không đưa vào JSON):\n"
            "- 'Bài 1.', 'Bài 2.', ... và mọi đề bài bài tập dạng 'Bài X. Cho một vật...'\n"
            "- Phần đáp số / hướng dẫn: 'ĐÁP SỐ', 'HƯỚNG DẪN', 'ĐÁP ÁN', 'Lời giải'\n"
            "- Tên trường, tên giáo viên, mục lục, lời nói đầu\n"
            "- Heading chỉ có số thứ tự, không có tiêu đề học thuật\n\n"
            "CHƯƠNG = tiêu đề lớn phân chia nội dung chính "
            "(ví dụ: 'I. TĨNH ĐIỆN', 'Chương 1: Cơ học', 'A. Quang hình học')\n"
            "MỤC = sub-topic lý thuyết trong chương "
            "(ví dụ: '1. Điện trường', '2.1 Định luật Coulomb')\n\n"
            "Giới hạn: tối đa 20 chương, mỗi chương tối đa 10 mục.\n\n"
            "NGOÀI RA: Với mỗi chương (đánh số từ 1), xác định các chương KHÁC mà nó PHỤ THUỘC "
            "kiến thức (cần học trước mới hiểu được chương này). Dùng số thứ tự chương (1-based). "
            "Chỉ liệt kê phụ thuộc thực sự. Nếu không có phụ thuộc nào thì trả {} cho 'prerequisites'.\n\n"
            "Trả về JSON thuần (KHÔNG markdown, KHÔNG giải thích):\n"
            '{"chapters": [{"title": "Tên chương", "sections": [{"title": "Tên mục"}]}], '
            '"prerequisites": {"4": [1, 2], "3": [1]}}'
        )

        loop = asyncio.get_running_loop()
        _pdf_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gemini_pdf")

        def _call_gemini():
            from google.genai import types as _gtypes
            from app.core.config import get_settings as _get_settings
            return client.models.generate_content(
                model=_get_settings().GEMINI_MODEL,
                contents=[
                    _gtypes.Part.from_bytes(data=compressed, mime_type="application/pdf"),
                    prompt,
                ],
            )

        logger.info("[gemini_pdf] Sending %.1f KB compressed PDF to Gemini for heading detection",
                    len(compressed) / 1024)
        response = await asyncio.wait_for(
            loop.run_in_executor(_pdf_executor, _call_gemini),
            timeout=180,  # 3 min — tăng vì file có thể nhiều trang
        )

        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = _sanitize_json_backslashes(text.strip())

        try:
            result = _json.loads(text)
        except _json.JSONDecodeError:
            result = _extract_partial_json(text)

        if isinstance(result, list):
            result = {"chapters": result}

        chapters = result.get("chapters", [])
        if not chapters:
            logger.warning("[gemini_pdf] Returned empty chapters")
            return None

        normalized = _normalize_gemini_pdf_result(result)
        logger.info(
            "[gemini_pdf] Detected %d chapters, %d prerequisite relations",
            len(normalized["chapters"]),
            sum(len(v) for v in normalized.get("prerequisites", {}).values()),
        )
        return normalized

    except Exception as e:
        logger.warning("[gemini_pdf] Failed: %s", e)
        return None


async def detect_heading_tree_gemini_pdf(
    pdf_bytes: bytes,
    markdown: str,
) -> dict:
    """
    Heading detector: chạy song song gemini_pdf (vision) và detect_heading_tree_llm (text).

    - Cả 2 chạy đồng thời qua asyncio.gather.
    - Ưu tiên kết quả gemini_pdf nếu thành công (đọc visual structure tốt hơn).
    - Nếu gemini_pdf timeout/fail → dùng kết quả LLM đã sẵn sàng, không mất thêm thời gian.
    """
    import asyncio

    gemini_task = asyncio.create_task(_run_gemini_pdf_vision(pdf_bytes))
    llm_task = asyncio.create_task(detect_heading_tree_llm(markdown))

    results = await asyncio.gather(gemini_task, llm_task, return_exceptions=True)

    gemini_result = results[0] if not isinstance(results[0], Exception) else None
    llm_result = results[1] if not isinstance(results[1], Exception) else None

    # Ưu tiên gemini_pdf nếu có chapters hợp lệ
    if gemini_result and gemini_result.get("chapters"):
        logger.info(
            "[heading_detect] Using gemini_pdf result (%d chapters)",
            len(gemini_result["chapters"]),
        )
        return gemini_result

    # Fallback: dùng LLM result
    if llm_result and llm_result.get("chapters"):
        logger.info(
            "[heading_detect] gemini_pdf failed/empty, using LLM result (%d chapters)",
            len(llm_result["chapters"]),
        )
        return llm_result

    # Cả 2 fail → heuristic
    logger.warning("[heading_detect] Both gemini_pdf and LLM failed, using heuristic")
    return detect_heading_tree(markdown)


async def detect_heading_tree_llm(markdown: str) -> dict:
    """
    LLM-based heading tree detection.

    1. Extract all # headings from markdown with content preview (1-3 lines after)
    2. Send heading + context to LLM to identify REAL chapters/sections
    3. LLM filters garbage (school names, TOC, answer keys)
    4. Returns clean heading tree
    5. Post-processing: rule-based clean + LLM consolidation if > 12 chapters

    Falls back to heuristic detect_heading_tree on failure.
    """
    headings = extract_headings_with_context(markdown, context_chars=250)

    if not headings:
        logger.info("[detect_heading_tree_llm] No headings found, falling back to heuristic")
        return detect_heading_tree(markdown)

    # Present headings as a numbered list WITHOUT markdown # levels.
    # The # depth from Gemini is unreliable — the LLM must classify purely
    # from title text and content preview, not from heading depth.
    heading_blocks: list[str] = []
    for i, h in enumerate(headings, 1):
        if h["context"]:
            heading_blocks.append(f"[{i}] {h['heading']}\n    Nội dung: {h['context']}")
        else:
            heading_blocks.append(f"[{i}] {h['heading']}\n    <không có nội dung>")

    heading_text = "\n".join(heading_blocks)

    prompt = (
        "Bạn là chuyên gia phân tích cấu trúc tài liệu giáo dục Việt Nam.\n\n"
        "Dưới đây là danh sách heading theo thứ tự xuất hiện, kèm nội dung ngay sau:\n\n"
        "---\n"
        f"{heading_text}\n"
        "---\n\n"
        "NHIỆM VỤ: Tổ chức thành CHƯƠNG và MỤC thật sự của tài liệu.\n\n"
        "⚠️ QUAN TRỌNG:\n"
        "- Số [n] và độ sâu '#' KHÔNG phản ánh cấp độ thực tế (do PDF được ghép từ nhiều phần độc lập).\n"
        "- Phán đoán DỰA VÀO TIÊU ĐỀ và NỘI DUNG, KHÔNG dựa vào số thứ tự hay '#'.\n"
        "- Tài liệu CÓ THỂ KHÔNG CÓ CHƯƠNG — chỉ có topics/sections. Trong trường hợp đó hãy treat mỗi topic/section như 1 chapter.\n\n"
        "QUY TẮC:\n"
        "1. CHƯƠNG = phần nội dung lớn phân chia tài liệu: có thể là chương lý thuyết, topic, chủ đề, bài học.\n"
        "   Không bắt buộc phải có từ 'Chương' — heading ngắn + có nội dung liền sau đều có thể là chapter.\n"
        "2. MỤC = tiểu mục, sub-topic, ví dụ minh họa, bài tập áp dụng BÊN TRONG chương.\n"
        "3. LOẠI BỎ hoàn toàn: tên trường, mục lục, lời nói đầu, phụ lục, tài liệu tham khảo, đáp án/đáp số standalone.\n"
        "4. 'Đáp số', 'Hướng dẫn', 'Đáp án' ngay sau nội dung bài → MỤC của chapter hiện tại, không phải chapter mới.\n"
        "5. Nếu một heading trông như CONTAINER (không có nội dung, ngay sau là nhiều heading con cùng cấp)\n"
        "   → bỏ qua container, dùng các heading con làm chapters.\n"
        "6. Tối đa 20 chapters, mỗi chapter tối đa 15 mục.\n\n"
        "VÍ DỤ:\n"
        "  [1] PHẦN I. <không có nội dung, ngay sau là A, B, C>   ← CONTAINER → bỏ qua\n"
        "  [2] A. BỔ TÚC VÉC TƠ. Nội dung: Véc tơ là...          ← CHAPTER\n"
        "  [3] I. Lực xuyên tâm. Nội dung: Lực hướng vào...       ← CHAPTER hoặc MỤC tùy ngữ cảnh\n"
        "  [4] Điện tích và điện trường. Nội dung: Điện tích...    ← CHAPTER (topic không có Chương N)\n"
        "  [5] HƯỚNG DẪN VÀ ĐÁP SỐ. Nội dung: Bài 1: 5m/s        ← MỤC của chapter trước\n\n"
        "Trả về JSON thuần (KHÔNG markdown code block):\n"
        '{"chapters": [{"chapter_id": "ch1", "title": "Tên chương", '
        '"sections": [{"section_id": "ch1_sec1", "title": "Tên mục"}]}]}'
    )

    try:
        from app.agents.llm import get_llm_client
        import json

        llm = get_llm_client()
        response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            role="planner",
            temperature=0.1,
            max_tokens=4000,
        )

        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

        # Sanitize LaTeX backslashes inside JSON strings so json.loads doesn't choke
        # on \vec, \frac, \alpha, etc. (common in Vietnamese physics heading titles).
        text = _sanitize_json_backslashes(text)

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Last resort: truncate at the last valid closing brace/bracket pair
            result = _extract_partial_json(text)
        if isinstance(result, list):
            result = {"chapters": result}

        chapters = result.get("chapters", [])
        if not chapters:
            logger.warning("[detect_heading_tree_llm] LLM returned empty, falling back")
            return detect_heading_tree(markdown)

        for i, ch in enumerate(chapters, 1):
            if not isinstance(ch, dict):
                continue
            ch["chapter_id"] = f"ch{i}"
            ch.setdefault("title", f"Chapter {i}")
            ch.setdefault("sections", [])
            secs = []
            for j, sec in enumerate(ch.get("sections", []), 1):
                if isinstance(sec, str):
                    sec = {"title": sec}
                if isinstance(sec, dict):
                    sec["section_id"] = f"ch{i}_sec{j}"
                    sec.setdefault("title", f"Section {j}")
                    sec.setdefault("subsections", [])
                    secs.append(sec)
            ch["sections"] = secs

        chapters = [ch for ch in chapters if isinstance(ch, dict) and ch.get("chapter_id")]
        result = {"chapters": chapters}

        logger.info(
            "[detect_heading_tree_llm] LLM detected %d chapters from %d headings",
            len(chapters), len(headings),
        )
        for ch in chapters:
            logger.info("  ch=%s: %s (%d sections)",
                        ch["chapter_id"], ch["title"], len(ch.get("sections", [])))

        # Post-process: rule-based clean + LLM consolidation if > 12 chapters
        result = await post_process_heading_tree(result)

        return result

    except Exception as e:
        logger.warning("[detect_heading_tree_llm] Failed: %s — falling back", e)
        return detect_heading_tree(markdown)


def _roman_to_int(roman: str) -> int | None:
    """Convert uppercase Roman numeral to integer. Returns None on failure."""
    val = 0
    roman = roman.upper()
    table = [
        ("CM", 900), ("D", 500), ("CD", 400), ("C", 100),
        ("XC", 90), ("L", 50), ("XL", 40), ("X", 10),
        ("IX", 9), ("V", 5), ("IV", 4), ("I", 1),
    ]
    for sym, num in table:
        while roman.startswith(sym):
            val += num
            roman = roman[len(sym):]
    return val if not roman else None


def normalize_chapter_id(raw: str) -> str:
    """
    Normalize a raw chapter identifier to the canonical "ch{n}" form.

    Supported input patterns:
      - "Chương 1: Động học"          → "ch1"
      - "Chương 10"                   → "ch10"
      - "ch1", "ch1_sec1"             → passthrough (already canonical)
      - "chuong-1", "chuong_1"        → "ch1"
      - "chapter-1", "chapter_1"      → "ch1"
      - "bai-1", "bai_1"              → "ch1"
      - "bài 1"                       → "ch1"
      - "A.QUANG HÌNH HỌC"            → "ch_a"
      - "B.CÁI GÌ ĐÓ"                 → "ch_b"
      - "1", "01"                     → "ch1"
      - Any input that doesn't match  → returned as-is + warning logged

    Vietnamese accented characters are stripped before matching.
    """
    import logging as _log
    _logger = _log.getLogger("rag.structure")

    if not raw:
        _logger.warning("[normalize_chapter_id] Received empty input")
        return ""

    original = raw
    s = raw.strip()

    # 1. Already canonical: starts with "ch" followed by digit
    m = re.match(r"^ch(\d+)(?:_sec(\d+))?(?:_sub(\d+))?$", s, re.IGNORECASE)
    if m:
        num = m.group(1).lstrip("0") or "0"
        result = f"ch{num}"
        if m.group(2):
            result += f"_sec{m.group(2)}"
        if m.group(3):
            result += f"_sub{m.group(3)}"
        return result

    # 2. Strip accents for Vietnamese character handling
    import unicodedata
    normalized = unicodedata.normalize("NFD", s)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    # 3. Extract chapter number from common patterns
    chapter_num: str | None = None

    # "Chương 1", "chuong-1", "chuong_1", "Chương 01"
    m2 = re.search(r"chuong[_\s-]?(\d+)", stripped, re.IGNORECASE)
    if not m2:
        # "Chapter 1", "chapter-1", "chapter_1"
        m2 = re.search(r"chapter[_\s-]?(\d+)", stripped, re.IGNORECASE)
    if not m2:
        # "Bài 1", "bai-1", "bai_1"
        m2 = re.search(r"bai[_\s-]?(\d+)", stripped, re.IGNORECASE)
    if not m2:
        # "Phần 1"
        m2 = re.search(r"phan[_\s-]?(\d+)", stripped, re.IGNORECASE)
    if not m2:
        # Roman numeral → Arabic conversion
        # Matches "II. LUONG CHAT...", "III. SOMETHING", "I. Title", etc.
        roman_match = re.match(r"^\s*[IVXLCMD]+\.", stripped, re.IGNORECASE)
        if roman_match:
            roman = re.match(r"^\s*([IVXLCMD]+)", stripped, re.IGNORECASE).group(1).upper()
            arabic = _roman_to_int(roman)
            if arabic:
                chapter_num = f"ch{arabic}"
    if not m2 and not chapter_num:
        # "A.QUANG HINH HOC", "B. CAI GI DO" -> ch_a, ch_b
        letter_match = re.match(r"^\s*([A-Z])\.\s*[A-Z]", stripped, re.IGNORECASE)
        if letter_match:
            chapter_num = f"ch_{letter_match.group(1).lower()}"
    if not m2 and not chapter_num:
        # "3. VA CHAM VAT RAN", "1. DONG HOC", "10. Title" → ch3, ch1, ch10
        m2 = re.match(r"^\s*(\d+)\.\s+\S", stripped)
    if not m2 and not chapter_num:
        # Standalone number: "1", "01", "1: Động học"
        m2 = re.search(r"(?:^|_|\s)(\d+)(?:\s|:|$)", stripped)

    if m2:
        num_str = m2.group(1).lstrip("0") or "0"
        chapter_num = f"ch{num_str}"

    if chapter_num:
        # Preserve _sec and _sub suffixes if present
        # e.g. "Chương 1: 1.1 Lực" → check for section pattern after chapter
        sec_match = re.search(r"_sec(\d+)", stripped, re.IGNORECASE)
        sub_match = re.search(r"_sub(\d+)", stripped, re.IGNORECASE)
        if sec_match:
            chapter_num += f"_sec{sec_match.group(1)}"
        if sub_match:
            chapter_num += f"_sub{sub_match.group(1)}"
        return chapter_num

    # 4. Fallback: return original, log warning
    _logger.warning(
        "[normalize_chapter_id] Could not normalize input '%s' — returning as-is. "
        "Known patterns: 'Chương N', 'Chapter N', 'Bài N', 'chuong-N', 'chN', "
        "'N', 'N: Title'",
        original,
    )
    return original


def flatten_heading_tree(tree: dict) -> list[dict]:
    """
    Flatten heading tree into a list of all heading units (chapters, sections, subsections)
    for scope selection.

    Each entry has: id, title, level (1=chapter, 2=section, 3=subsection), chapter_id, path
    """
    result: list[dict] = []
    for chapter in tree.get("chapters", []):
        result.append({
            "id": chapter["chapter_id"],
            "title": chapter["title"],
            "level": 1,
            "chapter_id": chapter["chapter_id"],
            "path": chapter["title"],
        })
        for section in chapter.get("sections", []):
            result.append({
                "id": section["section_id"],
                "title": section["title"],
                "level": 2,
                "chapter_id": chapter["chapter_id"],
                "path": f"{chapter['title']} > {section['title']}",
            })
            for sub in section.get("subsections", []):
                result.append({
                    "id": sub["section_id"],
                    "title": sub["title"],
                    "level": 3,
                    "chapter_id": chapter["chapter_id"],
                    "path": f"{chapter['title']} > {section['title']} > {sub['title']}",
                })
    return result


# ─────────────────────────────────────────────────────────────
# Heading tree post-processing (cleaning)
# ─────────────────────────────────────────────────────────────

# Patterns for meta / garbage headings that should NOT be chapters.
# Applied against the ORIGINAL title (with diacritics) so Vietnamese patterns match.
_META_PATTERNS = re.compile(
    r"^("
    r"TÀI LIỆU|GIÁO TRÌNH|SÁCH|BÀI GIẢNG|"
    r"TẬP\s*\d|"
    r"PHẦN\s+[A-Z]\.|PHẦN\s+[IVXLCDM]+\.?|PHẦN\s+\d+\.?|"  # PHẦN I., PHẦN 1., PHẦN A.
    r"TÓM TẮT|MỤC LỤC|LỜI NÓI ĐẦU|LỜI MỞ ĐẦU|GIỚI THIỆU|"
    r"PHỤ LỤC|TÀI LIỆU THAM KHẢO"
    r")",
    re.IGNORECASE,
)

_ANSWER_PATTERNS = re.compile(
    r"("
    r"\b[ĐD]AP SO\.?\b|\b[ĐD]AP AN\.?\b|\bHUONG DAN\b|\bLOI GIAI\b|"
    r"\bBAI TAP AP DUNG\b|"
    r"\bDAPSO\b|\bDAPAN\b|\bHUONGDAN\b|\bLOIGIAI\b"
    r")",
    re.IGNORECASE,
)


def _strip_diacritics(s: str) -> str:
    """Strip Vietnamese diacritics for pattern matching."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _is_garbage_title(title: str) -> bool:
    """Check if a chapter title is garbage (too short, symbols-only, etc.)."""
    stripped = title.strip()
    if len(stripped) < 3:
        return True
    # Titles that are just "ĐS:", "ĐS: $R_0$", "a. vô cùng." etc.
    clean = re.sub(r"[\$\{\}\\]", "", stripped)  # remove LaTeX
    clean = re.sub(r"[^a-zA-ZÀ-ỹ0-9\s]", "", clean).strip()
    if len(clean) < 3:
        return True
    # Single lowercase letter followed by period: "a. something"
    if re.match(r"^[a-z]\.\s", stripped):
        return True
    return False


def _extract_roman_prefix(title: str) -> str | None:
    """Extract Roman numeral prefix from title like 'III. TỪ TRƯỜNG'."""
    m = re.match(r"^\s*([IVXLCDM]+)\.\s", title, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


def clean_heading_tree(tree: dict) -> dict:
    """Rule-based post-processing to clean a noisy heading tree.

    Steps:
    1. Remove garbage titles (too short, symbols-only)
    2. Demote meta headings (book titles, preamble) to be ignored
    3. Demote answer key chapters to sections of the previous real chapter
    4. Deduplicate Roman numeral chapters (I appears twice → merge)
    5. Re-number chapter IDs sequentially

    Returns a new cleaned heading tree dict.
    """
    chapters = tree.get("chapters", [])
    if len(chapters) <= 1:
        return tree  # Nothing to clean

    original_count = len(chapters)

    # ── Step 1 & 2: Filter out garbage + meta chapters ──
    # These get completely removed (not demoted to sections)
    filtered: list[dict] = []
    for ch in chapters:
        title = ch.get("title", "").strip()

        # Garbage
        if _is_garbage_title(title):
            logger.info("[clean_heading_tree] Removing garbage chapter: %r", title)
            continue

        # Meta headings — match against original title since the pattern has diacritics
        if _META_PATTERNS.search(title):
            logger.info("[clean_heading_tree] Removing meta chapter: %r", title)
            continue

        filtered.append(ch)

    # ── Step 3: Demote answer key chapters to sections of previous chapter ──
    merged: list[dict] = []
    for ch in filtered:
        title = ch.get("title", "")

        if _ANSWER_PATTERNS.search(_strip_diacritics(title)) and merged:
            # Demote to section of previous chapter
            prev = merged[-1]
            sections = prev.get("sections", [])
            sec_id = f"{prev['chapter_id']}_sec{len(sections) + 1}"
            sections.append({
                "section_id": sec_id,
                "title": title,
                "subsections": ch.get("sections", []),  # move subsections too
            })
            prev["sections"] = sections
            logger.info(
                "[clean_heading_tree] Demoted answer chapter %r → section of %r",
                title, prev.get("title"),
            )
            continue

        merged.append(ch)

    # ── Step 4: Deduplicate Roman numeral chapters ──
    # If Roman numeral "I" appears twice (e.g., "I. TĨNH ĐIỆN" and
    # "I. ĐIỆN TRƯỜNG - ĐIỆN THẾ"), merge the second occurrence as
    # a section of the first.
    seen_roman: dict[str, int] = {}  # roman → index in deduped list
    deduped: list[dict] = []

    for ch in merged:
        title = ch.get("title", "")
        roman = _extract_roman_prefix(title)

        if roman and roman in seen_roman:
            # This Roman numeral already appeared — merge as section
            parent_idx = seen_roman[roman]
            parent = deduped[parent_idx]
            sections = parent.get("sections", [])
            sec_id = f"{parent['chapter_id']}_sec{len(sections) + 1}"
            sections.append({
                "section_id": sec_id,
                "title": title,
                "subsections": ch.get("sections", []),
            })
            parent["sections"] = sections
            logger.info(
                "[clean_heading_tree] Merged duplicate Roman %s: %r → section of %r",
                roman, title, parent.get("title"),
            )
        else:
            if roman:
                seen_roman[roman] = len(deduped)
            deduped.append(ch)

    # ── Step 5: Re-number chapter IDs sequentially ──
    for i, ch in enumerate(deduped, 1):
        old_id = ch.get("chapter_id", "")
        new_id = f"ch{i}"
        ch["chapter_id"] = new_id
        # Update section IDs too
        for j, sec in enumerate(ch.get("sections", []), 1):
            sec["section_id"] = f"{new_id}_sec{j}"
            for k, sub in enumerate(sec.get("subsections", []), 1):
                if isinstance(sub, dict):
                    sub["section_id"] = f"{new_id}_sec{j}_sub{k}"

    logger.info(
        "[clean_heading_tree] Cleaned %d → %d chapters",
        original_count, len(deduped),
    )

    return {"chapters": deduped}


async def llm_consolidate_heading_tree(
    tree: dict,
    max_chapters: int = 12,
) -> dict:
    """Use LLM to consolidate a heading tree that still has too many chapters.

    Only called when rule-based cleaning didn't reduce enough.
    Sends only chapter/section TITLES (very small token count).

    Returns a new heading tree with consolidated chapters.
    """
    chapters = tree.get("chapters", [])
    if len(chapters) <= max_chapters:
        return tree  # Already within limit

    logger.info(
        "[llm_consolidate] %d chapters > %d max — calling LLM to consolidate",
        len(chapters), max_chapters,
    )

    # Build compact representation of current tree (titles only)
    lines: list[str] = []
    for ch in chapters:
        title = ch.get("title", "")
        sections = ch.get("sections", [])
        sec_titles = [s.get("title", "") for s in sections if s.get("title")]
        if sec_titles:
            lines.append(f"- {title} (sections: {', '.join(sec_titles[:5])})")
        else:
            lines.append(f"- {title}")

    tree_text = "\n".join(lines)

    prompt = f"""Đây là heading tree thô từ một tài liệu giáo dục.
Nó có {len(chapters)} chapters nhưng nhiều cái thực ra là sections/subsections chứ không phải chapter riêng.

Heading tree hiện tại:
{tree_text}

Nhiệm vụ: Gộp (consolidate) các headings thành ĐÚNG cấu trúc chapter thật.
Quy tắc:
1. Chỉ giữ lại các CHAPTER THẬT (chủ đề chính, không phải tiểu mục)
2. Các heading nhỏ hơn → demote thành sections của chapter gần nhất
3. Trả về tối đa {max_chapters} chapters
4. Giữ nguyên title gốc, không sửa tên

Trả về JSON:
{{"chapters": [
  {{"title": "...", "sections": [{{"title": "..."}}]}}
]}}

CHỈ trả JSON, không giải thích."""

    try:
        from app.agents.llm import get_llm_client
        llm = get_llm_client()
        response = await llm.chat(
            messages=[
                {"role": "system", "content": "Bạn là trợ lý phân tích cấu trúc tài liệu. Trả về JSON."},
                {"role": "user", "content": prompt},
            ],
            role="outline",
            max_tokens=2000,
            temperature=0.1,
        )

        import json
        # Strip markdown fences if present
        clean = response.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            clean = "\n".join(lines).strip()

        result = json.loads(clean)

        # Handle both {"chapters": [...]} and bare [...] responses
        if isinstance(result, list):
            new_chapters = result
        elif isinstance(result, dict):
            new_chapters = result.get("chapters", [])
        else:
            logger.warning("[llm_consolidate] Unexpected LLM response type: %s", type(result).__name__)
            return tree

        if not new_chapters:
            logger.warning("[llm_consolidate] LLM returned empty chapters — keeping original")
            return tree

        # Re-assign chapter_id and section_id
        for i, ch in enumerate(new_chapters, 1):
            if not isinstance(ch, dict):
                continue
            ch["chapter_id"] = f"ch{i}"
            # Normalize sections: could be list of dicts or list of strings
            raw_sections = ch.get("sections", [])
            normalized_sections = []
            for j, sec in enumerate(raw_sections, 1):
                if isinstance(sec, str):
                    sec = {"title": sec}
                if not isinstance(sec, dict):
                    continue
                sec["section_id"] = f"ch{i}_sec{j}"
                sec.setdefault("subsections", [])
                for k, sub in enumerate(sec.get("subsections", []), 1):
                    if isinstance(sub, str):
                        sec["subsections"][k-1] = {"section_id": f"ch{i}_sec{j}_sub{k}", "title": sub}
                    elif isinstance(sub, dict):
                        sub["section_id"] = f"ch{i}_sec{j}_sub{k}"
                normalized_sections.append(sec)
            ch["sections"] = normalized_sections

        # Filter out any non-dict entries
        new_chapters = [ch for ch in new_chapters if isinstance(ch, dict) and ch.get("chapter_id")]

        logger.info(
            "[llm_consolidate] Consolidated %d → %d chapters via LLM",
            len(chapters), len(new_chapters),
        )
        return {"chapters": new_chapters}

    except Exception as e:
        logger.warning("[llm_consolidate] LLM consolidation failed: %s — keeping rule-based result", e)
        return tree


async def post_process_heading_tree(
    tree: dict,
    max_chapters: int = 12,
) -> dict:
    """Full heading tree post-processing pipeline.

    1. Rule-based cleaning (fast, deterministic)
    2. LLM consolidation (only if still > max_chapters)

    Called once during document upload/processing.
    """
    # Step 1: Rule-based
    cleaned = clean_heading_tree(tree)

    num_chapters = len(cleaned.get("chapters", []))
    logger.info("[post_process_heading_tree] After rule-based: %d chapters", num_chapters)

    # Step 2: LLM consolidation if still too many
    if num_chapters > max_chapters:
        cleaned = await llm_consolidate_heading_tree(cleaned, max_chapters)

    return cleaned

