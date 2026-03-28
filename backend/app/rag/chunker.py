"""Semantic chunking using LlamaIndex."""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    """A semantic chunk from document content."""
    chunk_id: str
    content: str
    content_type: str = "text"  # text, formula, image_description
    chapter: str = ""
    chapter_id: str = ""
    section: str = ""
    section_id: str = ""
    page_number: int | None = None
    latex_repr: str | None = None
    metadata: dict = field(default_factory=dict)


def semantic_chunk(
    markdown_content: str,
    heading_tree: dict,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
) -> list[Chunk]:
    """
    Split document into semantic chunks using LlamaIndex SemanticSplitterNodeParser.
    Each chunk preserves heading metadata and content type information.
    """
    try:
        from llama_index.core.node_parser import SemanticSplitterNodeParser
        from llama_index.core.schema import Document as LLDocument

        # Build heading map for metadata
        heading_map = _build_heading_map(heading_tree)

        # Create LlamaIndex document
        ll_doc = LLDocument(text=markdown_content, metadata=heading_map)

        # Use semantic splitter
        parser = SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=None,  # Will use default
        )

        nodes = parser.get_nodes_from_documents([ll_doc])

        chunks = []
        for i, node in enumerate(nodes):
            metadata = node.metadata

            chunk = Chunk(
                chunk_id=f"chunk_{metadata.get('chapter_id', 'doc')}_{i:04d}",
                content=node.text.strip(),
                content_type=_detect_content_type(node.text),
                chapter=metadata.get("chapter", ""),
                chapter_id=metadata.get("chapter_id", ""),
                section=metadata.get("section", ""),
                section_id=metadata.get("section_id", ""),
                page_number=metadata.get("page_number"),
                latex_repr=_extract_latex_from_content(node.text),
                metadata={
                    "heading_level": metadata.get("heading_level", 0),
                    "prev_heading": metadata.get("prev_heading", ""),
                },
            )
            chunks.append(chunk)

        return chunks

    except ImportError:
        # Fallback to simple regex-based chunking
        return _simple_chunk(markdown_content, heading_tree, chunk_size, chunk_overlap)


def _simple_chunk(
    markdown_content: str,
    heading_tree: dict,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
) -> list[Chunk]:
    """
    Fallback simple chunking when LlamaIndex is not available.
    Splits by paragraphs while preserving heading context.
    """
    lines = markdown_content.split("\n")
    chunks: list[Chunk] = []
    current_chunks: list[str] = []
    current_size = 0
    current_chapter = ""
    current_chapter_id = ""
    current_section = ""
    current_section_id = ""
    chunk_index = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if this is a heading
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            # Update current chapter/section context
            if level == 1:
                current_chapter = title
                current_chapter_id = _title_to_id(title)
            elif level == 2:
                current_section = title
                current_section_id = _title_to_id(title)
            elif level == 3:
                current_section = f"{current_section} > {title}" if current_section else title
                current_section_id = _title_to_id(title)

            current_chunks.append(line)
            current_size += len(line)

        elif current_size + len(line) > chunk_size and current_chunks:
            # Flush current chunk
            content = "\n".join(current_chunks)
            chunk = Chunk(
                chunk_id=f"chunk_{current_chapter_id}_{chunk_index:04d}" if current_chapter_id else f"chunk_{chunk_index:04d}",
                content=content,
                content_type=_detect_content_type(content),
                chapter=current_chapter,
                chapter_id=current_chapter_id,
                section=current_section,
                section_id=current_section_id,
                latex_repr=_extract_latex_from_content(content),
            )
            chunks.append(chunk)

            # Keep overlap
            overlap_lines = current_chunks[-3:] if len(current_chunks) >= 3 else current_chunks
            current_chunks = overlap_lines + [line]
            current_size = sum(len(l) for l in current_chunks)
            chunk_index += 1

        else:
            current_chunks.append(line)
            current_size += len(line)

    # Flush remaining
    if current_chunks:
        content = "\n".join(current_chunks)
        chunk = Chunk(
            chunk_id=f"chunk_{current_chapter_id}_{chunk_index:04d}" if current_chapter_id else f"chunk_{chunk_index:04d}",
            content=content,
            content_type=_detect_content_type(content),
            chapter=current_chapter,
            chapter_id=current_chapter_id,
            section=current_section,
            section_id=current_section_id,
            latex_repr=_extract_latex_from_content(content),
        )
        chunks.append(chunk)

    return chunks


def _build_heading_map(heading_tree: dict) -> dict:
    """Build a map of position to heading metadata for LlamaIndex."""
    # This would traverse the heading tree and build metadata
    # For simplicity, return the tree itself
    return heading_tree


def _detect_content_type(text: str) -> str:
    """Detect the primary content type of a text chunk."""
    # Check for formula indicators
    if "$$" in text or re.search(r"\$.*\$", text):
        return "formula"

    # Check for image description indicators
    if any(kw in text.lower() for kw in ["hình ", "hình ", "sơ đồ", "đồ thị", "minh họa"]):
        if len(text) < 500:  # Short descriptive text
            return "image_description"

    return "text"


def _extract_latex_from_content(text: str) -> str | None:
    """Extract LaTeX formulas from content text."""
    formulas = re.findall(r"\$\$(.+?)\$\$|\$(.+?)\$", text, re.DOTALL)
    if formulas:
        # Return the first formula found
        for f in formulas:
            if f[0]:  # display formula
                return f[0].strip()
            if f[1]:  # inline formula
                return f[1].strip()
    return None


def _title_to_id(title: str) -> str:
    """Convert heading title to URL-safe ID."""
    normalized = re.sub(r"[^\w\s]", "", title)
    normalized = re.sub(r"\s+", "_", normalized.strip().lower())
    return normalized[:50]  # Limit length
