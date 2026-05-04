"""Markdown cleaner: normalize headings, remove noise, prepare for structure detection."""

import re
from typing import NamedTuple


class CleanerResult(NamedTuple):
    cleaned: str
    stats: dict


def clean_markdown(raw: str) -> CleanerResult:
    """
    Clean raw markdown from Gemini/Marker/PyMuPDF so heading tree detection
    is accurate. Apply rules in order:

      1.  Remove noise artifacts        — page numbers, footers, school names
      1.5 Demote false headings         — numbered/parenthetical list items wrongly marked as ##
      2.  Detect PART / CHAPTER level   — promote ONLY clear chapter-keyword lines to #
      2.5 Flatten PHẦN prefix           — PHẦN + A./I. sub-headings → combined chapter titles
      3.  Fix heading level jumps       — correct ### immediately after # (missing ##)
      4.  Fix bold sub-headings         — **bold text:** that starts a section → ####
      5.  Remove duplicate headings     — same heading title appearing twice in a row
      6.  Normalize spacing             — collapse excess blank lines
    """
    lines = raw.split("\n")
    stats = {
        "removed_noise": 0,
        "demoted_false": 0,
        "promoted_parts": 0,
        "flattened_parts": 0,
        "normalized_sequences": 0,
        "fixed_levels": 0,
        "fixed_bolds": 0,
        "removed_duplicates": 0,
        "normalized_spacing": 0,
    }

    # ── Rule 1: Remove noise artifacts ──────────────────────────────────────────
    lines, count = _remove_noise(lines)
    stats["removed_noise"] = count

    # ── Rule 1.5: Demote false headings (parenthetical sub-items) ───────────
    lines, count = _demote_false_headings(lines)
    stats["demoted_false"] = count

    # ── Rule 2: Detect PART / CHAPTER and promote to # ──────────────────────────
    lines, count = _promote_part_chapter(lines)
    stats["promoted_parts"] = count

    # ── Rule 2.5: Flatten PHẦN prefix headings ──────────────────────────────────
    # Must run AFTER promote so PHẦN headings are already at # level.
    # Turns:  # PHẦN X + # A. TOPIC  →  # PHẦN X. TOPIC
    lines, count = _flatten_part_prefix_headings(lines)
    stats["flattened_parts"] = count

    # ── Rule 2.7: Normalize consecutive numbered sequences ──────────────────────
    # Fix: ## 1. Title, ### 2. Title, ### 3. Title → make all siblings same level
    lines, count = _normalize_numbered_sequences(lines)
    stats["normalized_sequences"] = count

    # ── Rule 3: Fix heading level jumps ─────────────────────────────────────────
    lines, count = _fix_level_jumps(lines)
    stats["fixed_levels"] = count

    # ── Rule 4: Fix bold sub-headings ───────────────────────────────────────────
    lines, count = _fix_bold_subheadings(lines)
    stats["fixed_bolds"] = count

    # ── Rule 5: Remove duplicate headings ───────────────────────────────────────
    lines, count = _remove_duplicate_headings(lines)
    stats["removed_duplicates"] = count

    # ── Rule 6: Normalize spacing ────────────────────────────────────────────────
    lines, count = _normalize_spacing(lines)
    stats["normalized_spacing"] = count

    cleaned = "\n".join(lines)
    return CleanerResult(cleaned=cleaned, stats=stats)


# ─── Rule 1: Remove noise artifacts ────────────────────────────────────────────

# Noise patterns applied to the CONTENT of a line (with # markers stripped).
# This allows catching noise that the parser has already promoted to headings.
_NOISE_CONTENT_PATTERNS = [
    r"^TRƯỜNG\s+PHỔ\s+THÔNG",         # School name
    r"^TRƯỜNG\s+ĐẠI\s+HỌC",
    r"^GV\.",                            # Teacher attribution
    r"^TS\.",
    r"^ThS\.",
    r"^PAGE\s*\d+",
    r"^–\s*–\s*–",
    r"^\*+\s*$",
    r"^•\s*$",
    r"^\[\s*\]\(\s*\)",
    r"!?\[\]\(data:image.*?\)",
    r"^\*\*GV\.",
    r"^\*\*\s*VD\.\s*\*\*",
    r"^\*\*\s*HD:\s*\*\*",
    r"^\*\*\s*ĐS:\s*\*\*",
    r"^\*\*\s*Lưu ý\s*:\s*\*\*",
    r"^\*\*\s*TA XÉT",
    r"^\*\*\s*HƯỚNG DẪN VÀ ĐÁP SỐ\s*\*\*",
    r"^`\s*TRƯỜNG\s+PHỔ\s+THÔNG",
    r"^`\s*TRƯỜNG\s+ĐẠI\s+HỌC",
    r"^`\s*GV\.",
    r"^`\s*HƯỚNG DẪN",
    r"^`\s*ĐÁP SỐ",
    r"^`\s*HD",
    r"^`\s*ĐS",
    r"^`\s*Phần\s+[IVX]+\b",
    r"^`\s*Phần\s+\d+\b",
    r"^`.*TRƯỜNG\s+PHỔ\s+THÔNG",
    r"^`.*TRƯỜNG\s+ĐẠI\s+HỌC",
    r"^`.*GV\.",
    r"^`.*HƯỚNG\s+DẪN",
    r"^`.*ĐÁP\s+SỐ",
    # ── Standalone guide/answer headings that are NOT inside a PHẦN context ────
    # Rule 2.5 handles these when inside a PHẦN group (demotes to ##).
    # Here we catch any that escaped that context.
    r"^HƯỚNG\s+DẪN\b",
    r"^HƯỚNG\s+DẪN\s+VÀ\s+ĐÁP\s+SỐ\b",
    r"^ĐÁP\s+SỐ\b",
    r"^ĐÁP\s+ÁN\b",
]

_NOISE_CONTENT_RES = [re.compile(p, re.IGNORECASE) for p in _NOISE_CONTENT_PATTERNS]

# Pattern to strip leading # markers from a line to get plain content
_HEADING_STRIP_RE = re.compile(r"^#{1,6}\s*")


def _remove_noise(lines: list[str]) -> tuple[list[str], int]:
    """Strip page markers, footers, headers, watermark-like lines.

    Checks content BOTH with and WITHOUT leading # markers so that headings
    the parser already marked (e.g. '# TRƯỜNG PHỔ THÔNG...') are also removed.

    NOTE: Do NOT remove display math ($$...$$) — those are real content.
    """
    cleaned: list[str] = []
    removed = 0

    for line in lines:
        stripped = line.strip()

        # Standalone page numbers: "1", "2", ... as the entire line
        if re.fullmatch(r"\d+", stripped):
            removed += 1
            continue

        # Get the content without leading # markers for heading-aware matching
        content = _HEADING_STRIP_RE.sub("", stripped)

        skip = False
        for pat_re in _NOISE_CONTENT_RES:
            if pat_re.search(content):
                removed += 1
                skip = True
                break
        if skip:
            continue

        cleaned.append(line)

    return cleaned, removed


# ─── Rule 1.5: Demote false headings ──────────────────────────────────────────
#
# ONLY demote parenthetical sub-items that are CLEARLY not real sections:
#   ## b) Cường độ sáng $I$     → b) Cường độ sáng $I$      (letter-paren)
#   ## (2) Công thức             → (2) Công thức              (number-paren)
#
# We do NOT demote ## 1. patterns — those can be real numbered sections.
# Problem 2 (wrong level of 2.-7.) is handled by Rule 2.7 instead.

_FALSE_HEADING_PATTERNS = [
    # Lowercase/uppercase letter + ) — Vietnamese sub-item style  (b) Something)
    re.compile(r"^#{2,6}\s+[a-zA-Z]\)\s+"),
    # Parenthetical number: (1), (2), ...
    re.compile(r"^#{2,6}\s+\(\d+\)\s+"),
]

_SUBNUMBERED_RE = re.compile(r"^#{1,6}\s+\d+\.\d+")


def _demote_false_headings(lines: list[str]) -> tuple[list[str], int]:
    """Strip heading markers from lines that are list items, not real headings.

    Returns the line as plain text (removes the '## ' or '### ' prefix).
    Only applies to ## and ### level — # level is left alone (already filtered
    by Rule 1 and validated by Rule 2).
    """
    result: list[str] = []
    demoted = 0

    for line in lines:
        stripped = line.strip()

        # Never touch # level (chapter) lines
        if re.match(r"^#\s", stripped) and not re.match(r"^#{2}", stripped):
            result.append(line)
            continue

        # Skip sub-numbered patterns (1.1, 2.3 etc. — real sections)
        if _SUBNUMBERED_RE.match(stripped):
            result.append(line)
            continue

        demoted_flag = False
        for pat in _FALSE_HEADING_PATTERNS:
            if pat.match(stripped):
                # Strip heading markers → plain text
                plain = _HEADING_STRIP_RE.sub("", stripped)
                result.append(plain)
                demoted += 1
                demoted_flag = True
                break

        if not demoted_flag:
            result.append(line)

    return result, demoted


# ─── Rule 2.7: Normalize consecutive numbered heading sequences ────────────────
#
# Problem: PDF parsers sometimes emit a numbered list where item 1 is at ##
# but items 2-N are at ###, making them subsections of item 1 instead of siblings.
#
#   Before:   ## 1. Title A    ## 2. Title B (should be sibling of 1)
#             ### 2. Title B    becomes subsection of 1 — WRONG
#             ### 3. Title C
#
#   After:    ## 1. Title A
#             ## 2. Title B    (promoted to same level as 1)
#             ## 3. Title C
#
# Algorithm: scan for a heading with a digit prefix (1., 2., ...).
# If the NEXT heading has the NEXT sequential digit at a DEEPER level,
# promote it to the same level as the first.

_NUM_HEADING_RE = re.compile(r"^(#{1,6})\s+(\d+)\.\s+")


def _normalize_numbered_sequences(lines: list[str]) -> tuple[list[str], int]:
    """Ensure consecutive numbered headings (1., 2., 3.) are siblings, not nested."""
    result = list(lines)   # work in place on a copy
    fixed = 0

    # Find all heading line indices and their (level, digit) if they have one
    heading_info: list[tuple[int, int, int]] = []  # (line_idx, heading_level, digit)
    for idx, line in enumerate(result):
        m = _NUM_HEADING_RE.match(line.strip())
        if m:
            heading_info.append((idx, len(m.group(1)), int(m.group(2))))

    # Look for sequences where digit increments but level jumps down
    i = 0
    while i < len(heading_info) - 1:
        idx1, lvl1, dig1 = heading_info[i]
        idx2, lvl2, dig2 = heading_info[i + 1]

        # Consecutive digits (1→2, 2→3, etc.) but level jumped deeper
        if dig2 == dig1 + 1 and lvl2 > lvl1:
            # Promote heading at idx2 from lvl2 to lvl1
            old_line = result[idx2].strip()
            new_line = re.sub(r"^#{1,6}", "#" * lvl1, old_line)
            result[idx2] = new_line
            # Update heading_info entry
            heading_info[i + 1] = (idx2, lvl1, dig2)
            fixed += 1

        i += 1

    return result, fixed


# ─── Rule 2: Promote PART / CHAPTER to # ──────────────────────────────────────

# Valid Roman numerals (I through XX) — explicit whitelist to avoid false positives
_VALID_ROMAN = frozenset({
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
})


def _promote_part_chapter(lines: list[str]) -> tuple[list[str], int]:
    """
    Promote lines that look like PART or CHAPTER headings (no # prefix yet)
    to # (PART) or # (CHAPTER).

    CONSERVATIVE rules — only promote when we are 100% sure:
      - Explicit keyword prefix: "Chương N", "PHẦN N", "Chapter N", "Part N"
      - Valid Roman numeral prefix (I–XX) with a title following: "III. SOMETHING"
      - Single uppercase letter prefix with ALL-CAPS title: "A. QUANG HÌNH HỌC"

    We deliberately do NOT promote generic ALL CAPS lines — that's too noisy.
    The LLM in detect_heading_tree_llm handles fine-grained classification.
    """
    promoted = 0
    result: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Fast path: skip long lines (paragraphs, formulas) immediately ────
        if len(stripped) > 120 or len(stripped) < 2:
            result.append(line)
            i += 1
            continue

        # ── Handle already-marked headings: promote ## that should be # ────
        m2 = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m2:
            level = len(m2.group(1))
            title = m2.group(2)
            promoted_line = _try_promote(title)
            if promoted_line:
                new_level = len(re.match(r"^(#+)", promoted_line).group(1))
                if level != new_level:
                    result.append(re.sub(r"^#{1,6}", "#" * new_level, line))
                    promoted += 1
                    i += 1
                    continue
            result.append(line)
            i += 1
            continue

        # ── Try to promote non-heading lines ────
        promoted_line = _try_promote(stripped)
        if promoted_line is not None:
            result.append(promoted_line)
            promoted += 1
        else:
            result.append(line)

        i += 1

    return result, promoted


def _try_promote(text: str) -> str | None:
    """Return #-prefixed heading ONLY if text is unambiguously a chapter-level heading.

    Conservative rules:
    1. Explicit chapter keyword (Chương N, PHẦN N, Chapter N, Part N)
    2. Valid Roman numeral (I–XX) followed by a title
    3. Single uppercase letter (A–Z) followed by ALL-CAPS or no-accent title

    Does NOT promote generic ALL-CAPS lines — too error-prone.
    """

    # ── Reject noise unconditionally ────────────────────────────────────────
    if re.search(r"^\s*\|", text):           # table row
        return None
    if re.search(r"^\s*\$", text):           # LaTeX
        return None
    if re.search(r"^\s*`", text):            # backtick artifact
        return None
    if re.search(r"\s*[-:=]+\s*\|", text):   # table separator
        return None
    if re.match(r"TRƯỜNG\s+(PHỔ\s+THÔNG|ĐẠI\s+HỌC)", text, re.IGNORECASE):
        return None
    if re.match(r"GV\.", text):
        return None
    if re.match(r"(TS|ThS)\.", text):
        return None
    if re.match(r"PAGE\s*\d+", text, re.IGNORECASE):
        return None
    if re.match(r"(HƯỚNG\s+DẪN|ĐÁP\s+SỐ|ĐÁP\s+ÁN)\b", text, re.IGNORECASE):
        return None

    # ── Rule 1: Explicit chapter keyword with number ──────────────────────────
    # "Chương 1: ...", "PHẦN 3", "Chapter 2 — Title", "Part I"
    if re.match(r"^(PHẦN|CHƯƠNG|CHAPTER|PART|MODULE|UNIT)\s+\S", text, re.IGNORECASE):
        return f"# {text}"

    # ── Rule 2: Valid Roman numeral (I–XX) followed by period and title ───────
    # Strict whitelist — avoids matching random letters like l., d., c., m.
    roman_m = re.match(r"^([IVXivx]+)\.\s+(.+)$", text)
    if roman_m:
        roman_part = roman_m.group(1).upper()
        title_part = roman_m.group(2).strip()
        if roman_part in _VALID_ROMAN and len(title_part) >= 2:
            return f"# {text}"

    # ── Rule 3: Single UPPERCASE letter (A–Z) + ALL-CAPS / no-lowercase title ─
    # Only accept A. TITLE when TITLE has no lowercase letters (truly uppercase heading)
    letter_m = re.match(r"^([A-Z])\.\s+(.+)$", text)  # strict: NO re.IGNORECASE
    if letter_m:
        title_part = letter_m.group(2).strip()
        # Title must be mostly uppercase (no mixed-case sentences)
        has_lower = bool(re.search(r"[a-zà-ỹ]", title_part))
        if not has_lower and len(title_part) >= 2:
            return f"# {text}"

    return None


# ─── Rule 2.5: Flatten PHẦN prefix headings ──────────────────────────────────
#
# Vietnamese physics/maths books often use a two-tier heading structure:
#
#   # PHẦN BỔ SUNG LÝ THUYẾT          ← grouping label (no body text)
#   # A. QUANG HÌNH HỌC               ← actual topic chapter
#   [content]
#   # B. GIAO THOA ĐỊNH XỨ            ← actual topic chapter
#   [content]
#   # PHẦN BÀI TẬP                    ← another grouping label
#   # I. PHẢN XẠ ÁNH SÁNG             ← actual topic chapter
#   [content]
#
# The desired output is FLAT chapters named "PHẦN X. TOPIC" (Roman/letter
# prefix stripped from the sub-heading):
#
#   # PHẦN BỔ SUNG LÝ THUYẾT. QUANG HÌNH HỌC
#   [content]
#   # PHẦN BỔ SUNG LÝ THUYẾT. GIAO THOA ĐỊNH XỨ
#   [content]
#   # PHẦN BÀI TẬP. PHẢN XẠ ÁNH SÁNG
#   [content]
#
# Detection criterion for "grouping label": a # PHẦN heading whose immediately
# following non-blank line is another # heading (no body text of its own).

_PHAN_RE = re.compile(
    r"^(#{1,3})\s+((?:PHẦN|PART)\b.+)$",
    re.IGNORECASE,
)
_LETTER_SUB_RE = re.compile(r"^(#{1,3})\s+[A-Z]\.\s+(.+)$")
_ROMAN_SUB_RE = re.compile(
    r"^(#{1,3})\s+(?:I{1,3}|IV|VI{0,3}|IX|XI{0,3}|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)\.\s+(.+)$",
    re.IGNORECASE,
)
# "HƯỚNG DẪN …" / "ĐÁP SỐ …" lines under a PHẦN — demote to section level
_GUIDE_RE = re.compile(
    r"^(#{1,3})\s+(HƯỚNG\s+DẪN|ĐÁP\s+SỐ|ĐÁP\s+ÁN|GỢI\s+Ý)\b",
    re.IGNORECASE,
)


def _flatten_part_prefix_headings(lines: list[str]) -> tuple[list[str], int]:
    """Flatten PHẦN grouping labels into combined chapter titles.

    A PHẦN heading is considered a *grouping label* (not a real chapter) when
    the very next non-blank line is another # heading.  In that case we:

      1. Remember the PHẦN title as the current prefix.
      2. For every subsequent A./B./C. or I./II./III. sub-heading at the same
         # level, emit  `# PHẦN. TOPIC`  (strip the letter/roman prefix).
      3. For HƯỚNG DẪN / ĐÁP SỐ sub-headings: demote to section (##).
      4. Any non-# body text is emitted unchanged.
      5. A new PHẦN heading updates the current prefix.
      6. A # heading that is NOT a letter/roman/HƯỚNG DẪN clears the context
         (we have left the PHẦN group).
    """
    result: list[str] = []
    flattened = 0
    current_phan: str = ""       # active PHẦN prefix
    current_phan_hashes: str = "#"  # heading level of the active PHẦN heading

    def _is_heading(s: str) -> bool:
        return bool(re.match(r"^#{1,6}\s", s))

    def _next_nonblank_idx(idx: int) -> int:
        j = idx + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        return j

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Is this a PHẦN heading? ──────────────────────────────────────────
        phan_m = _PHAN_RE.match(stripped)
        if phan_m:
            hashes = phan_m.group(1)
            phan_title = phan_m.group(2).strip().rstrip(".:,")

            # Check if it is a grouping label (next non-blank is another heading)
            j = _next_nonblank_idx(i)
            next_stripped = lines[j].strip() if j < len(lines) else ""
            if _is_heading(next_stripped):
                # Grouping label — remember as prefix, don't emit
                current_phan = phan_title
                current_phan_hashes = hashes
                flattened += 1
                i += 1
                continue
            else:
                # Has its own content — treat as a normal chapter, clear prefix
                current_phan = ""
                result.append(line)
                i += 1
                continue

        # ── Inside an active PHẦN context ───────────────────────────────────
        if current_phan and _is_heading(stripped):
            phan_level = len(current_phan_hashes)
            heading_m = re.match(r"^(#{1,6})\s", stripped)
            heading_level = len(heading_m.group(1)) if heading_m else 99

            if heading_level == phan_level:
                # Same level as PHẦN → check if it's a sub-chapter (A./I.) or guide
                letter_m = _LETTER_SUB_RE.match(stripped)
                roman_m = _ROMAN_SUB_RE.match(stripped)
                guide_m = _GUIDE_RE.match(stripped)

                if letter_m:
                    topic = letter_m.group(2).strip()
                    result.append(f"{current_phan_hashes} {current_phan}. {topic}")
                    flattened += 1
                    i += 1
                    continue
                elif roman_m:
                    topic = roman_m.group(2).strip()
                    result.append(f"{current_phan_hashes} {current_phan}. {topic}")
                    flattened += 1
                    i += 1
                    continue
                elif guide_m:
                    # Demote HƯỚNG DẪN / ĐÁP SỐ to section (##)
                    guide_text = stripped[len(guide_m.group(1)):].strip()
                    deeper = "#" * (phan_level + 1)
                    result.append(f"{deeper} {guide_text}")
                    flattened += 1
                    i += 1
                    continue
                else:
                    # Same-level heading that's not A./I./HƯỚNG DẪN → exit PHẦN
                    current_phan = ""
                    result.append(line)
                    i += 1
                    continue
            else:
                # Deeper heading (##, ### etc.) = section/subsection inside current chapter.
                # Do NOT clear PHẦN context — next # B./# II. should still be flattened.
                result.append(line)
                i += 1
                continue


        # ── Not a heading (body text) — emit as-is ───────────────────────────
        result.append(line)
        i += 1

    return result, flattened


# ─── Rule 3: Fix heading level jumps ──────────────────────────────────────────

def _fix_level_jumps(lines: list[str]) -> tuple[list[str], int]:
    """
    When a heading at level N+2 or deeper immediately follows a heading at level N
    (skipping a level), demote it to level N+1.

    Example: # Chapter → ### Section  becomes  # Chapter → ## Section
    """
    result: list[str] = []
    fixed = 0
    prev_heading_level = 0  # track last heading level seen

    for line in lines:
        stripped = line.strip()
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))

            # If current level skips more than 1 level from previous heading, fix it
            if prev_heading_level > 0 and level > prev_heading_level + 1:
                new_level = prev_heading_level + 1
                result.append(re.sub(r"^#{1,6}", "#" * new_level, line))
                fixed += 1
                prev_heading_level = new_level
            else:
                result.append(line)
                prev_heading_level = level
        else:
            result.append(line)

    return result, fixed


# ─── Rule 4: Fix bold sub-headings ────────────────────────────────────────────

def _fix_bold_subheadings(lines: list[str]) -> tuple[list[str], int]:
    """
    Convert markdown bold lines that look like sub-section headings to ####.

    Pattern: **a. Định nghĩa:** or **b. Công thức:** and similar
    where the line is short and followed by indented content.
    """
    fixed = 0
    result: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        m = re.match(r"^\*\*(.+?)\*\*[.:]?\s*$", stripped)
        if m:
            inner = m.group(1).strip()
            # Check if it looks like a sub-heading:
            # - Short (under 60 chars)
            # - Has letter/number prefix (a., b., 1., 2., ...)
            # - NOT a full sentence (no verb ending with . in middle)
            if (len(inner) < 60
                    and re.match(r"^[\(\[]?[a-zà-ỹ\d]+[.\):\)\]]", inner, re.IGNORECASE)
                    and not re.match(r"^.+\s+\w+\s+.{20,}", inner)):
                result.append(f"#### {inner}")
                fixed += 1
                continue

        result.append(line)

    return result, fixed


# ─── Rule 5: Remove duplicate headings ────────────────────────────────────────

def _remove_duplicate_headings(lines: list[str]) -> tuple[list[str], int]:
    """
    Remove heading lines that are exact duplicates of the immediately
    preceding heading (same level, same title).
    """
    result: list[str] = []
    removed = 0
    prev_key = ""

    for line in lines:
        stripped = line.strip()
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            key = f"{level}:{title}"
            if key == prev_key:
                removed += 1
                continue
            prev_key = key
        else:
            prev_key = ""  # reset on non-heading
        result.append(line)

    return result, removed


# ─── Rule 6: Normalize spacing ─────────────────────────────────────────────────

def _normalize_spacing(lines: list[str]) -> tuple[list[str], int]:
    """
    Collapse multiple consecutive blank lines down to at most 2.
    Also strip trailing whitespace from every line.
    """
    collapsed: list[str] = []
    blank_count = 0
    removed = 0

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            blank_count += 1
            if blank_count <= 2:
                collapsed.append("")
        else:
            blank_count = 0
            collapsed.append(stripped)

    # Count removed extras
    removed = len([l for l in lines if not l.strip()]) - len([l for l in collapsed if not l])

    return collapsed, max(removed, 0)
