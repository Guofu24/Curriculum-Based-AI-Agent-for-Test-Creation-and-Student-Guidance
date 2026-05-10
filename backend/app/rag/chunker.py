"""Semantic chunking using LlamaIndex."""

import logging
import re
from typing import Any

from app.rag.structure import _is_heading_chapter_level

logger = logging.getLogger("app.rag.chunker")


def semantic_chunk(
    markdown: str,
    heading_tree: dict,
    embed_model: Any | None = None,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
) -> list[dict]:
    """
    Split document into semantic chunks using LlamaIndex SemanticSplitterNodeParser.

    Returns list of dicts per spec:
    [{
      "chunk_id": str,
      "document_id": str,
      "chapter": str,
      "chapter_id": str,
      "section": str,
      "section_id": str,
      "content_type": str,  # text | formula | image_description
      "page_number": int | None,
      "latex_repr": str | None,
      "content": str,
    }]

    Each chunk metadata per spec:
    - chunk_id, document_id, chapter, chapter_id, section, section_id,
      content_type, page_number, latex_repr
    """
    try:
        from llama_index.core.node_parser import SemanticSplitterNodeParser
        from llama_index.core.schema import Document as LLDocument

        ll_doc = LLDocument(text=markdown)
        # Only use SemanticSplitterNodeParser when a real embedder is provided.
        # Passing embed_model=None causes a Pydantic ValidationError in newer
        # LlamaIndex versions — catch it so we fall through to _simple_chunk.
        parser = SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=embed_model,  # None → falls to except
        )
        nodes = parser.get_nodes_from_documents([ll_doc])

        chunks = []
        for i, node in enumerate(nodes):
            text = node.text.strip()
            chapter, chapter_id, section, section_id = _get_heading_context(
                node.metadata, heading_tree
            )
            content_type = _detect_content_type(text)
            latex_repr = _extract_latex_from_content(text)
            page_number = _extract_page_number(text)

            chunks.append({
                "chunk_id": f"chunk_{chapter_id}_{i:04d}" if chapter_id else f"chunk_{i:04d}",
                "document_id": "",
                "chapter": chapter,
                "chapter_id": chapter_id,
                "section": section,
                "section_id": section_id,
                "content_type": content_type,
                "page_number": page_number,
                "latex_repr": latex_repr,
                "content": text,
            })

        return chunks

    except Exception:
        # SemanticSplitterNodeParser raises ValidationError when embed_model=None,
        # ImportError when llama_index is absent, or other runtime errors.
        # In all cases fall back to simple paragraph-based chunking.
        return _simple_chunk(markdown, heading_tree, chunk_size, chunk_overlap)


def _build_heading_tree_lookup(
    heading_tree: dict,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """
    Build lookup maps from heading_tree:
      - title_to_chapter_id: {lowercase_chapter_title -> canonical chapter_id}
      - ch_sec_lookup:       {chapter_id -> {lowercase/norm_section_title -> section_id}}

    Using per-chapter section lookup prevents cross-chapter title collisions
    (e.g. two chapters both having a section named "Bài tập").

    Returns (title_to_chapter_id, ch_sec_lookup).
    """
    import unicodedata

    def _norm(s: str) -> str:
        nfd = unicodedata.normalize("NFD", s.strip().lower())
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    title_to_chapter_id: dict[str, str] = {}
    ch_sec_lookup: dict[str, dict[str, str]] = {}  # chapter_id → {sec_title_norm → sec_id}

    for ch in heading_tree.get("chapters", []):
        ch_title = ch.get("title", "").strip()
        ch_id = ch.get("chapter_id", "")
        if ch_title and ch_id:
            title_to_chapter_id[ch_title.lower()] = ch_id
            title_to_chapter_id[_norm(ch_title)] = ch_id
        if ch_id:
            sec_map: dict[str, str] = {}
            for sec in ch.get("sections", []):
                sec_title = sec.get("title", "").strip()
                sec_id = sec.get("section_id", "")
                if sec_title and sec_id:
                    sec_map[sec_title.lower()] = sec_id
                    sec_map[_norm(sec_title)] = sec_id
            ch_sec_lookup[ch_id] = sec_map

    return title_to_chapter_id, ch_sec_lookup


def _normalize_title(s: str) -> str:
    """Normalize a heading title for canonical matching.

    Steps (order matters):
    1. Strip leading/trailing whitespace
    2. NFD decompose + drop combining marks (strips Vietnamese diacritics)
    3. Lowercase
    4. Remove leading numbering prefix:
       - Roman numerals:  I., II., III., ... (up to 8 chars)
       - Single letter:   A., B., C., ...
       - Decimal number:  1., 2., 1.1., 2.3.4., ...
       Each must be followed by a space or end of string.
    5. Strip trailing punctuation / parentheses
    6. Collapse internal whitespace
    """
    import unicodedata
    s = s.strip()
    nfd = unicodedata.normalize("NFD", s)
    s = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    s = s.lower()
    # Remove leading numbering: roman (i–viii), letter (a–z), decimal (1.2.3)
    s = re.sub(r"^(?:[ivxlcdm]{1,8}|[a-z]|\d+(?:\.\d+)*)[\.\):]\s*", "", s)
    # Strip trailing punctuation
    s = s.rstrip(".,;:!?()-\u2019 ")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_canonical_lookup(
    heading_tree: dict,
) -> dict[str, tuple[str, str, str, str]]:
    """Build a flat normalized-title → (chapter_id, chapter_title, section_id, section_title) map.

    chapter-level entries have section_id = section_title = "".
    Both the raw-lower and the fully normalized form of each title are stored,
    so a single lookup call finds either form.
    """
    lookup: dict[str, tuple[str, str, str, str]] = {}

    for ch in heading_tree.get("chapters", []):
        ch_id = ch.get("chapter_id", "")
        ch_title = ch.get("title", "").strip()
        if ch_id and ch_title:
            for key in (ch_title.lower(), _normalize_title(ch_title)):
                if key:
                    lookup[key] = (ch_id, ch_title, "", "")

        for sec in ch.get("sections", []):
            sec_id = sec.get("section_id", "")
            sec_title = sec.get("title", "").strip()
            if ch_id and sec_id and sec_title:
                for key in (sec_title.lower(), _normalize_title(sec_title)):
                    if key:
                        lookup[key] = (ch_id, ch_title, sec_id, sec_title)

    return lookup


def _audit_chunks(chunks: list[dict], heading_tree: dict) -> None:
    """Log warnings when chunk distribution looks wrong.

    Checks:
    - Any canonical chapter in heading_tree with 0 chunks
    - Any single chapter holding >80% of all chunks
    - All chunks missing section_id
    - More than 10% of chunks missing chapter_id
    """
    if not chunks:
        return

    total = len(chunks)
    ch_counts: dict[str, int] = {}
    no_section = 0
    no_chapter = 0

    for c in chunks:
        ch_id = c.get("chapter_id", "")
        ch_counts[ch_id] = ch_counts.get(ch_id, 0) + 1
        if not c.get("section_id"):
            no_section += 1
        if not ch_id:
            no_chapter += 1

    for ch in heading_tree.get("chapters", []):
        ch_id = ch.get("chapter_id", "")
        count = ch_counts.get(ch_id, 0)
        if count == 0:
            logger.warning(
                "[chunker audit] chapter %r has 0 chunks — heading may not have been detected in markdown",
                ch_id,
            )

    for ch_id, count in ch_counts.items():
        ratio = count / total
        if ratio > 0.80 and len(ch_counts) > 1:
            logger.warning(
                "[chunker audit] chapter %r holds %.0f%% of all %d chunks — other chapters may be missing",
                ch_id, ratio * 100, total,
            )

    if no_section == total:
        logger.warning("[chunker audit] ALL %d chunks are missing section_id", total)

    if no_chapter > total * 0.10:
        logger.warning(
            "[chunker audit] %d/%d chunks are missing chapter_id",
            no_chapter, total,
        )

    logger.info(
        "[chunker audit] %d chunks | chapters: %s",
        total,
        {k: v for k, v in sorted(ch_counts.items())},
    )


def _simple_chunk(
    markdown: str,
    heading_tree: dict,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
) -> list[dict]:
    """Fallback chunker when LlamaIndex is unavailable.

    Design invariants enforced:
    - chunk["chapter_id"] ∈ {canonical chapter_ids from heading_tree} always
    - chunk["section_id"] ∈ {canonical section_ids from heading_tree} always
    - Content before the first canonical heading is discarded (preamble)
    - Unrecognized headings NEVER change chapter_id or section_id
    - No slug IDs are ever generated from raw heading text

    Heading detection (in priority order for each line):
    1. Markdown heading (# / ## / ###) whose stripped title matches canonical
    2. Plain-text line (≤120 chars) whose normalized form matches canonical
    3. Everything else → content (or preamble discard if no chapter anchored yet)
    """
    canonical_lookup = _build_canonical_lookup(heading_tree)
    ch_lookup: dict[str, dict] = {
        ch["chapter_id"]: ch
        for ch in heading_tree.get("chapters", [])
        if ch.get("chapter_id")
    }

    lines = markdown.split("\n")
    chunks: list[dict] = []

    # ---- mutable state -------------------------------------------------
    in_preamble = True          # discard content until first canonical heading
    current_chapter = ""
    current_chapter_id = ""
    current_section = ""
    current_section_id = ""
    current_lines: list[str] = []
    current_size = 0
    chunk_index = 0
    # --------------------------------------------------------------------

    def flush() -> None:
        nonlocal current_lines, current_size, chunk_index
        if not current_lines:
            return
        content = "\n".join(current_lines).strip()
        if not content:
            current_lines = []
            current_size = 0
            return
        chunks.append({
            "chunk_id": f"chunk_{current_chapter_id}_{chunk_index:04d}",
            "document_id": "",
            "chapter": current_chapter,
            "chapter_id": current_chapter_id,
            "section": current_section,
            "section_id": current_section_id,
            "content_type": _detect_content_type(content),
            "page_number": _extract_page_number(content),
            "latex_repr": _extract_latex_from_content(content),
            "content": content,
        })
        chunk_index += 1
        current_lines = []
        current_size = 0

    def _match(title: str) -> tuple[str, str, str, str] | None:
        """Return (ch_id, ch_title, sec_id, sec_title) or None."""
        for key in (title.lower(), _normalize_title(title)):
            if key and key in canonical_lookup:
                return canonical_lookup[key]
        # Prefix containment: canonical is an unambiguous prefix of the parsed title
        norm = _normalize_title(title)
        if norm and len(norm) >= 4:
            for canon_key, entry in canonical_lookup.items():
                if len(canon_key) >= 4 and norm.startswith(canon_key):
                    return entry
        return None

    def _apply_match(match: tuple[str, str, str, str]) -> None:
        """Switch chapter/section state to the matched canonical entry."""
        nonlocal in_preamble
        nonlocal current_chapter, current_chapter_id
        nonlocal current_section, current_section_id
        ch_id, ch_raw_title, sec_id, sec_raw_title = match
        ch_node = ch_lookup.get(ch_id, {})
        ch_title = ch_node.get("title", ch_raw_title)
        flush()
        in_preamble = False
        current_chapter_id = ch_id
        current_chapter = ch_title
        if sec_id:
            current_section_id = sec_id
            current_section = sec_raw_title
        else:
            current_section_id = ""
            current_section = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # ---- try to extract a heading title ----------------------------
        title: str | None = None
        md_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if md_match:
            title = md_match.group(2).strip()
        elif len(line) <= 120:
            title = line

        # ---- canonical match? ------------------------------------------
        if title is not None:
            entry = _match(title)
            if entry is not None:
                _apply_match(entry)
                continue   # heading line itself is not content
            else:
                logger.debug(
                    "[chunker] unmatched heading-like line %r — kept as content",
                    line[:80],
                )
                # Fall through to content handling below

        # ---- content line ----------------------------------------------
        if in_preamble:
            logger.debug("[chunker] preamble discard: %r", line[:60])
            continue

        if current_size + len(line) > chunk_size and current_lines:
            flush()
            overlap = current_lines[-3:] if len(current_lines) >= 3 else current_lines[:]
            current_lines = overlap + [line]
            current_size = sum(len(l) for l in current_lines)
        else:
            current_lines.append(line)
            current_size += len(line)

    flush()
    _audit_chunks(chunks, heading_tree)
    return chunks



def _get_heading_context(metadata: dict, heading_tree: dict) -> tuple[str, str, str, str]:
    """
    Extract heading context (chapter, chapter_id, section, section_id)
    from LlamaIndex node metadata and heading tree.

    section_id is now resolved from heading_tree canonical IDs (e.g. "ch1_sec2")
    instead of a slug derived from the raw title text.

    Returns (chapter, chapter_id, section, section_id).
    chapter_id is guaranteed non-empty if heading_tree has chapters.
    """
    import unicodedata

    def _norm(s: str) -> str:
        nfd = unicodedata.normalize("NFD", s.strip().lower())
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    chapter = ""
    chapter_id = ""
    section = ""
    section_id = ""

    # Build canonical lookup maps from heading_tree (per-chapter for sections)
    _, ch_sec_lookup = _build_heading_tree_lookup(heading_tree)
    title_to_ch_id: dict[str, str] = {}
    for ch in heading_tree.get("chapters", []):
        ch_title = ch.get("title", "").strip()
        ch_id = ch.get("chapter_id", "")
        if ch_title and ch_id:
            title_to_ch_id[ch_title.lower()] = ch_id
            title_to_ch_id[_norm(ch_title)] = ch_id

    prev_heading = metadata.get("prev_heading", "")
    if prev_heading:
        match = re.match(r"^(#{1,3})\s+(.+)$", prev_heading)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            if level == 1:
                chapter = title
                chapter_id = (
                    title_to_ch_id.get(title.lower())
                    or title_to_ch_id.get(_norm(title))
                    # No _title_to_id fallback — unrecognized level-1 headings must not
                    # produce dirty slugs. Fall through to the canonical-first-chapter
                    # fallback below instead.
                )
            elif level == 2:
                section = title
                chapter_id = metadata.get("chapter_id", "")
                # Lookup section_id scoped to resolved chapter_id
                _ch_sec_map = ch_sec_lookup.get(chapter_id, {})
                section_id = (
                    _ch_sec_map.get(title.lower())
                    or _ch_sec_map.get(_norm(title))
                    # No _title_to_id fallback for section either — unrecognized
                    # section headings leave section_id as empty string.
                )

    # Fallback: ensure chapter_id is NEVER empty
    if not chapter_id and heading_tree:
        chapters = heading_tree.get("chapters", [])
        if chapters:
            first_ch = chapters[0]
            chapter_id = first_ch.get("chapter_id", "")
            chapter = first_ch.get("title", "")
    if not chapter_id:
        # Ultimate fallback — should never happen if heading_tree is populated
        chapter_id = "ch_unknown"

    return chapter, chapter_id, section, section_id


def _detect_content_type(text: str) -> str:
    """Detect the primary content type of a text chunk."""
    if "$$" in text or re.search(r"\$.*\$", text):
        return "formula"
    if any(kw in text.lower() for kw in ["hình ", "sơ đồ", "đồ thị", "minh họa"]):
        if len(text) < 500:
            return "image_description"
    return "text"


def _extract_latex_from_content(text: str) -> str | None:
    """Extract LaTeX formulas from content text."""
    formulas = re.findall(r"\$\$(.+?)\$\$|\$(.+?)\$", text, re.DOTALL)
    for f in formulas:
        if f[0]:
            return f[0].strip()
        if f[1]:
            return f[1].strip()
    return None


def _extract_page_number(text: str) -> int | None:
    """Extract page number from <!-- Page N --> marker."""
    match = re.search(r"<!--\s*Page\s*(\d+)\s*-->", text)
    return int(match.group(1)) if match else None


def _title_to_id(title: str) -> str:
    """Convert heading title to a safe ASCII-only ID string."""
    # Step 1: strip non-ASCII (Vietnamese diacritics, emoji, etc.)
    ascii_chars = []
    for ch in title:
        code = ord(ch)
        if code < 128:
            ascii_chars.append(ch)
        elif ch.isalnum():
            ascii_chars.append(ch)  # keep alphanum chars from any script
        # else: drop punctuation/symbols
    normalized = "".join(ascii_chars)
    normalized = re.sub(r"\s+", "_", normalized.strip().lower())
    result = normalized[:50]
    if not result:
        result = "untitled"
    return result


def _title_to_chapter_id(title: str) -> str:
    """Convert heading title to chapter_id (ch1, ch2 format)."""
    title_lower = title.lower()
    if title_lower.startswith("chương"):
        parts = title.split()
        for part in parts:
            if part.rstrip(".").isdigit():
                return f"ch{part.rstrip('.')}"
    # If title is empty or doesn't match, use a hash-based fallback
    # so chapter_id is NEVER an empty string
    result = _title_to_id(title)
    if not result:
        import hashlib
        result = "ch_" + hashlib.md5(title.encode()).hexdigest()[:6]
    return result


def _count_sections(existing_chunks: list[dict], chapter_id: str) -> int:
    """Count how many UNIQUE sections already exist for a chapter.

    Uses a set of section_ids to avoid over-counting: a section with 5 chunks
    must still count as 1, not 5.
    """
    return len({
        c["section_id"]
        for c in existing_chunks
        if c.get("chapter_id") == chapter_id and c.get("section_id")
    })
