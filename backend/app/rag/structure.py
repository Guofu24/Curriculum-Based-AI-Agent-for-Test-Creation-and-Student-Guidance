"""Structure detection: heading tree building from markdown."""

import re
from dataclasses import dataclass, field
from typing import Any

logger = __import__("logging").getLogger("rag.structure")


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

    for line in lines:
        line = line.strip()
        if not line:
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if not heading_match:
            continue

        found_any_heading = True
        level = len(heading_match.group(1))
        title = heading_match.group(2).strip()

        # Roman numeral or letter-prefixed headings are ALWAYS chapter-level (level 1)
        # regardless of their # depth, so they become top-level chapters in the tree.
        # e.g. "## II. LƯỠNG CHẤT PHẲNG" → chapter "II. LƯỠNG..." with chapter_id=ch5
        if level >= 2 and _is_heading_chapter_level(title):
            level = 1

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


async def detect_heading_tree_llm(markdown: str) -> dict:
    """
    LLM-based heading tree detection.

    1. Extract all # headings from markdown
    2. Send heading list to LLM to identify REAL chapters/sections
    3. LLM filters garbage (school names, TOC, answer keys)
    4. Returns clean heading tree

    Falls back to heuristic detect_heading_tree on failure.
    """
    heading_lines: list[str] = []
    for line in markdown.split("\n"):
        line_s = line.strip()
        m = re.match(r"^(#{1,4})\s+(.+)$", line_s)
        if m and len(m.group(2).strip()) > 1:
            heading_lines.append(line_s)

    if not heading_lines:
        logger.info("[detect_heading_tree_llm] No headings found, falling back to heuristic")
        return detect_heading_tree(markdown)

    heading_text = "\n".join(heading_lines)

    prompt = (
        "Ban la chuyen gia phan tich cau truc sach giao khoa.\n\n"
        "Danh sach TAT CA heading tu tai lieu:\n\n"
        "---\n"
        f"{heading_text}\n"
        "---\n\n"
        "NHIEM VU: To chuc lai thanh CHUONG (chapter) va BAI/MUC (section) THAT SU.\n\n"
        "QUY TAC:\n"
        "1. CHI giu heading mang NOI DUNG HOC THUAT (chuong, bai, kien thuc)\n"
        "2. LOAI BO: ten truong, muc luc, loi noi dau, dap an, huong dan giai, phu luc, tai lieu tham khao\n"
        "3. BAI TAP cua chuong -> merge vao chuong do (thanh section), KHONG tach chapter rieng\n"
        "4. Title chapter phai mo ta noi dung (vd: 'Dong hoc chat diem'), KHONG dung 'Phan I' hay 'Chuong 1'\n"
        "5. Sections = bai hoc/chu de CON that su\n"
        "6. Neu co 'Phan I', 'Phan II' la grouping lon -> dung muc con ben trong lam chapters\n"
        "7. Toi da 15 chapters, moi chapter toi da 10 sections\n\n"
        "TRA VE JSON THUAN (KHONG markdown code block):\n"
        '{"chapters": [{"chapter_id": "ch1", "title": "Ten chuong", '
        '"sections": [{"section_id": "ch1_sec1", "title": "Ten bai"}]}]}'
    )

    try:
        from app.agents.llm import get_llm_client
        import json

        llm = get_llm_client()
        response = await llm.agenerate(
            prompt=prompt,
            role="planner",
            temperature=0.1,
            max_tokens=2000,
        )

        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

        result = json.loads(text)
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
            len(chapters), len(heading_lines),
        )
        for ch in chapters:
            logger.info("  ch=%s: %s (%d sections)",
                        ch["chapter_id"], ch["title"], len(ch.get("sections", [])))

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

    Each entry has: id, title, level (1=chapter, 2=section, 3=subsection),
    chapter_id, parent_id, path
    """
    result: list[dict] = []
    for chapter in tree.get("chapters", []):
        result.append({
            "id": chapter["chapter_id"],
            "title": chapter["title"],
            "level": 1,
            "chapter_id": chapter["chapter_id"],
            "parent_id": None,
            "path": chapter["title"],
        })
        for section in chapter.get("sections", []):
            result.append({
                "id": section["section_id"],
                "title": section["title"],
                "level": 2,
                "chapter_id": chapter["chapter_id"],
                "parent_id": chapter["chapter_id"],
                "path": f"{chapter['title']} > {section['title']}",
            })
            for sub in section.get("subsections", []):
                result.append({
                    "id": sub["section_id"],
                    "title": sub["title"],
                    "level": 3,
                    "chapter_id": chapter["chapter_id"],
                    "parent_id": section["section_id"],
                    "path": f"{chapter['title']} > {section['title']} > {sub['title']}",
                })
    return result


# ─────────────────────────────────────────────────────────────
# Heading tree post-processing (cleaning)
# ─────────────────────────────────────────────────────────────

# Patterns for meta / garbage headings that should NOT be chapters
_META_PATTERNS = re.compile(
    r"^("
    r"TÀI LIỆU|GIÁO TRÌNH|SÁCH|BÀI GIẢNG|"   # Book/course titles
    r"TẬP\s*\d|PHẦN\s*[A-Z]\.|"                 # Volume / Part markers
    r"TÓM TẮT|MỤC LỤC|LỜI NÓI ĐẦU|LỜI MỞ ĐẦU|GIỚI THIỆU|"  # Preamble
    r"PHỤ LỤC|TÀI LIỆU THAM KHẢO"              # Appendix / References
    r")",
    re.IGNORECASE,
)

_ANSWER_PATTERNS = re.compile(
    r"("
    r"ĐÁP SỐ|ĐÁP ÁN|HƯỚNG DẪN|LỜI GIẢI|"
    r"DAP SO|DAP AN|HUONG DAN|LOI GIAI"
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

        # Meta headings (book title, preamble, etc.)
        if _META_PATTERNS.search(_strip_diacritics(title)):
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

