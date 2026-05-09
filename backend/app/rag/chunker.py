"""Semantic chunking using LlamaIndex."""

import re
from typing import Any

from app.rag.structure import _is_heading_chapter_level


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


def _simple_chunk(
    markdown: str,
    heading_tree: dict,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
) -> list[dict]:
    """
    Fallback simple chunking when LlamaIndex is not available.
    Splits by paragraphs while preserving heading context.
    Uses heading_tree to get canonical chapter_id and section_id for each heading.
    """
    import unicodedata

    def _norm(s: str) -> str:
        nfd = unicodedata.normalize("NFD", s.strip().lower())
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    # Build canonical lookups from heading_tree (per-chapter for sections)
    title_to_chapter_id, ch_sec_lookup = _build_heading_tree_lookup(heading_tree)

    # Legacy compat: title_to_chapter_id already contains lowercase chapter titles
    title_to_canonical_id_compat = title_to_chapter_id

    lines = markdown.split("\n")
    chunks: list[dict] = []
    current_chunks: list[str] = []
    current_size = 0
    current_chapter = ""
    current_chapter_id = ""
    current_section = ""
    current_section_id = ""
    chunk_index = 0

    def flush() -> dict:
        nonlocal current_chunks, current_size, chunk_index, current_chapter_id
        content = "\n".join(current_chunks)
        chunk_id = f"chunk_{current_chapter_id}_{chunk_index:04d}" if current_chapter_id else f"chunk_{chunk_index:04d}"
        # Guarantee chapter_id is never empty string
        safe_chapter_id = current_chapter_id or "ch_unknown"
        chunk = {
            "chunk_id": chunk_id,
            "document_id": "",
            "chapter": current_chapter,
            "chapter_id": safe_chapter_id,
            "section": current_section,
            "section_id": current_section_id,
            "content_type": _detect_content_type(content),
            "page_number": _extract_page_number(content),
            "latex_repr": _extract_latex_from_content(content),
            "content": content,
        }
        chunk_index += 1
        return chunk

    for line in lines:
        line = line.strip()
        if not line:
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            # Roman numeral or letter-prefixed headings are chapter-level regardless of # depth
            if level >= 2 and _is_heading_chapter_level(title):
                level = 1

            if level == 1:
                if current_chunks:
                    chunks.append(flush())
                    current_chunks = []
                    current_size = 0
                current_chapter = title
                # Use canonical chapter_id from heading_tree if available
                canonical = title_to_canonical_id_compat.get(title.lower())
                if canonical:
                    current_chapter_id = canonical
                else:
                    current_chapter_id = _title_to_chapter_id(title)
                current_section = ""
                current_section_id = ""

            elif level == 2:
                if current_chunks:
                    chunks.append(flush())
                    overlap_lines = current_chunks[-3:] if len(current_chunks) >= 3 else current_chunks
                    current_chunks = overlap_lines + [line]
                    current_size = sum(len(l) for l in current_chunks)
                else:
                    current_chunks = [line]
                    current_size = len(line)
                current_section = title
                # Lookup canonical section_id per current chapter (avoids cross-chapter collisions)
                _ch_sec_map = ch_sec_lookup.get(current_chapter_id, {})
                _sec_id = _ch_sec_map.get(title.lower()) or _ch_sec_map.get(_norm(title))
                current_section_id = _sec_id or f"{current_chapter_id}_sec{_count_sections(chunks, current_chapter_id) + 1}"

            elif level == 3:
                current_chunks.append(line)
                current_size += len(line)

        elif current_size + len(line) > chunk_size and current_chunks:
            chunks.append(flush())
            overlap_lines = current_chunks[-3:] if len(current_chunks) >= 3 else current_chunks
            current_chunks = overlap_lines + [line]
            current_size = sum(len(l) for l in current_chunks)
        else:
            current_chunks.append(line)
            current_size += len(line)

    if current_chunks:
        chunks.append(flush())

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
                    or _title_to_id(title)
                )
            elif level == 2:
                section = title
                chapter_id = metadata.get("chapter_id", "")
                # Lookup section_id scoped to resolved chapter_id
                _ch_sec_map = ch_sec_lookup.get(chapter_id, {})
                section_id = (
                    _ch_sec_map.get(title.lower())
                    or _ch_sec_map.get(_norm(title))
                    or _title_to_id(title)
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
