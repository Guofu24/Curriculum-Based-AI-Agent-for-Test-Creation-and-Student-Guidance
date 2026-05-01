"""Markdown cleaner: normalize headings, remove noise, prepare for structure detection."""

import re
from typing import NamedTuple


class CleanerResult(NamedTuple):
    cleaned: str
    stats: dict


def clean_markdown(raw: str) -> CleanerResult:
    """
    Clean raw markdown from Gemini/Marker/PyMuPDF so heading tree detection
    is accurate. Apply 6 rules in order:

      1. Remove noise artifacts       — page numbers, footers, headers
      2. Detect PART / CHAPTER level  — promote all-caps / letter-prefix lines to #
      3. Fix heading level jumps      — correct ### immediately after # (missing ##)
      4. Fix bold sub-headings        — **bold text:** that starts a section → ####
      5. Remove duplicate headings    — same heading title appearing twice in a row
      6. Normalize spacing            — collapse excess blank lines
    """
    lines = raw.split("\n")
    stats = {
        "removed_noise": 0,
        "promoted_parts": 0,
        "fixed_levels": 0,
        "fixed_bolds": 0,
        "removed_duplicates": 0,
        "normalized_spacing": 0,
    }

    # ── Rule 1: Remove noise artifacts ─────────────────────────────────────────
    lines, count = _remove_noise(lines)
    stats["removed_noise"] = count

    # ── Rule 2: Detect PART / CHAPTER and promote to # ──────────────────────────
    lines, count = _promote_part_chapter(lines)
    stats["promoted_parts"] = count

    # ── Rule 3: Fix heading level jumps ─────────────────────────────────────────
    lines, count = _fix_level_jumps(lines)
    stats["fixed_levels"] = count

    # ── Rule 4: Fix bold sub-headings ───────────────────────────────────────────
    lines, count = _fix_bold_subheadings(lines)
    stats["fixed_bolds"] = count

    # ── Rule 5: Remove duplicate headings ──────────────────────────────────────
    lines, count = _remove_duplicate_headings(lines)
    stats["removed_duplicates"] = count

    # ── Rule 6: Normalize spacing ───────────────────────────────────────────────
    lines, count = _normalize_spacing(lines)
    stats["normalized_spacing"] = count

    cleaned = "\n".join(lines)
    return CleanerResult(cleaned=cleaned, stats=stats)


# ─── Rule 1: Remove noise artifacts ────────────────────────────────────────────

def _remove_noise(lines: list[str]) -> tuple[list[str], int]:
    """Strip page markers, footers, headers, watermark-like lines."""
    cleaned: list[str] = []
    removed = 0

    for line in lines:
        stripped = line.strip()
        skip = False

        # Standalone page numbers: "1", "2", ... at start of a block
        if re.fullmatch(r"\d+", stripped):
            removed += 1
            continue

        # Footer/header patterns commonly injected by PDF parsers
        skip_patterns = [
            r"^TRƯỜNG\s+PHỔ\s+THÔNG",         # School name header
            r"^TRƯỜNG\s+ĐẠI\s+HỌC",
            r"^GV\.",                            # Teacher attribution "GV.PHẠM VŨ KIM HOÀNG"
            r"^TS\.",
            r"^ThS\.",
            r"^PAGE\s*\d+",                     # Page N markers
            r"^–\s*–\s*–",                      # Decorative dividers
            r"^\s*\*+\s*$",                     # Lines with only asterisks
            r"^\s*•\s*$",                       # Bullet-only empty lines
            r"^\[\s*\]\(\s*\)",                  # Empty markdown image refs
            r"!\[\]\(data:image.*?\)",          # Broken image base64 refs
            # ── LaTeX-only lines ────────────────────────────────────────────
            r"^\s*\$\$.*\$\$\s*$",               # Standalone display math
            r"^\s*\$\([^)]+\)\s*\$\s*$",        # Standalone inline math $...$
            # ── Bold text noise (standalone bold lines that are NOT real headings) ──
            r"^\s*\*\*GV\.",                     # **GV.PHẠM VŨ KIM HOÀNG**
            r"^\s*\*\*\s*VD\.\s*\*\*",            # **VD.**
            r"^\s*\*\*\s*HD:\s*\*\*",            # **HD:**
            r"^\s*\*\*\s*ĐS:\s*\*\*",            # **ĐS:**
            r"^\s*\*\*\s*Lưu ý\s*:\s*\*\*",      # **Lưu ý:**
            r"^\s*\*\*\s*TA XÉT.*",              # **TA XÉT SỰ GIAO THOA...
            r"^\s*\*\*\s*HƯỚNG DẪN VÀ ĐÁP SỐ\s*\*\*",  # **HƯỚNG DẪN VÀ ĐÁP SỐ**
            r"^\s*\*\*\s*III\. CHIẾT SUẤT.*",    # **III. CHIẾT SUẤT THAY ĐỔI**
            # ── Backtick-wrapped noise (Gemini output artifact) ────────────────
            r"^\s*`\s*TRƯỜNG\s+PHỔ\s+THÔNG",
            r"^\s*`\s*TRƯỜNG\s+ĐẠI\s+HỌC",
            r"^\s*`\s*GV\.",
            r"^\s*`\s*HƯỚNG DẪN",
            r"^\s*`\s*ĐÁP SỐ",
            r"^\s*`\s*HD",
            r"^\s*`\s*ĐS",
            r"^\s*`\s*Phần\s+[IVX]+\b",       # `Phần I`, `Phần IV`, `Phần X`, etc.
            r"^\s*`\s*Phần\s+\d+\b",          # `Phần 1`, `Phần 2`, etc.
            # ── Lines in backticks that contain footer/content keywords ────────────
            r"^\s*`.*TRƯỜNG\s+PHỔ\s+THÔNG",
            r"^\s*`.*TRƯỜNG\s+ĐẠI\s+HỌC",
            r"^\s*`.*GV\.",
            r"^\s*`.*HƯỚNG\s+DẪN",
            r"^\s*`.*ĐÁP\s+SỐ",
        ]
        for pat in skip_patterns:
            if re.search(pat, stripped, re.IGNORECASE):
                removed += 1
                skip = True
                break
        if skip:
            continue

        cleaned.append(line)

    return cleaned, removed


# ─── Rule 2: Promote PART / CHAPTER to # ──────────────────────────────────────

def _promote_part_chapter(lines: list[str]) -> tuple[list[str], int]:
    """
    Promote lines that look like PART or CHAPTER headings (no # prefix yet)
    to # (PART) or # (CHAPTER).

    Patterns detected:
      - ALL CAPS short line (likely PART)
      - Letter-prefix: "A. TITLE", "B. QUANG HÌNH HỌC"
      - "PHẦN N: Title", "CHAPTER N: Title"
      - Standalone Roman numeral or letter: "I.", "II.", "A)", "B)"
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
                new_level = len(promoted_line.split()[0])
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
    """Return #-prefixed heading if text matches PART/CHAPTER pattern, else None."""

    # ── Reject lines that look like noise even if uppercase ──────────────────
    if re.search(r"^\s*\|", text):          # starts with | (table row)
        return None
    if re.search(r"^\s*\$", text):           # starts with $ (LaTeX)
        return None
    if re.search(r"^\s*`", text):            # starts with ` (inline code / backtick artifact)
        return None
    if re.search(r"\s*[-:=]+\s*\|", text):   # has table separator
        return None
    # ── School name / footer noise (ALL CAPS but NOT real headings) ───────────
    if re.match(r"TRƯỜNG\s+PHỔ\s+THÔNG", text):  # School name header
        return None
    if re.match(r"TRƯỜNG\s+ĐẠI\s+HỌC", text):   # University name
        return None
    if re.match(r"GV\.", text):                    # Teacher attribution
        return None
    if re.match(r"TS\.", text):                    # Dr./Prof.
        return None
    if re.match(r"ThS\.", text):                   # Master
        return None
    if re.match(r"PAGE\s*\d+", text, re.IGNORECASE):  # Page markers
        return None
    m = re.match(r"^([A-ZÀ-Ỳ])\s*[.)]\s+(.+)$", text, re.IGNORECASE)
    if m:
        letter = m.group(1)
        title = m.group(2).strip()
        # Skip if it looks like a sentence (contains lowercase, long sentence)
        if len(title) > 10 and re.search(r"[a-zà-ỹ]", title):
            return None
        return f"# {m.group(0)}"

    # Pattern: "PHẦN BỔ SUNG", "PART ONE" → # PHẦN BỔ SUNG
    if re.match(r"^(PHẦN|CHƯƠNG|CHAPTER|PART)\s+", text, re.IGNORECASE):
        return f"# {text}"

    # Pattern: Roman numerals: "I.", "II.", "III."
    if re.match(r"^(I{1,3}|IV|V|VI{0,3})\.\s*(.*)$", text, re.IGNORECASE):
        return f"# {text}"

    # ALL CAPS line, short, likely a heading
    if (text.isupper()
            and 3 <= len(text) <= 80
            and not re.search(r"[.,;:]\s*\S{20,}", text)  # not a long sentence
            and not re.search(r"\d{4,}", text)):            # not a year/number list
        return f"# {text}"

    return None


# ─── Rule 3: Fix heading level jumps ──────────────────────────────────────────

def _fix_level_jumps(lines: list[str]) -> tuple[list[str], int]:
    """
    When a ### immediately follows a # (no ## between them),
    demote ### → ##. This fixes "PART → Section → SubSection" structure
    that should be "PART → Chapter → Section".
    """
    result: list[str] = []
    fixed = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            title = m.group(2)

            # Look at previous actual heading (skip non-heading lines)
            prev_idx = i - 1
            prev_level = 0
            while prev_idx >= 0 and not re.match(r"^#{1,6}\s+", result[prev_idx].strip()):
                prev_idx -= 1
            if prev_idx >= 0:
                prev_m = re.match(r"^(#{1,6})\s+", result[prev_idx].strip())
                if prev_m:
                    prev_level = len(prev_m.group(1))

            # If current level skips more than 1 level from previous, fix it
            if prev_level > 0 and level > prev_level + 1:
                new_level = prev_level + 1
                result.append(re.sub(r"^#{1,6}", "#" * new_level, line))
                fixed += 1
            else:
                result.append(line)
        else:
            result.append(line)

        i += 1

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
