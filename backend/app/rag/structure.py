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
