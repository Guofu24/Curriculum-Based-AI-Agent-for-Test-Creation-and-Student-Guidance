"""Document parser: Marker (PDF), python-docx, python-pptx."""

import io
from typing import Literal

from fastapi import UploadFile


class DocumentParseError(Exception):
    """Raised when document parsing fails."""
    pass


async def parse_document(file_bytes: bytes, file_type: str) -> dict:
    """
    Parse document and extract text with heading structure.
    Returns dict: {"content": markdown_str, "page_count": int}.
    """
    if file_type == "pdf":
        return await _parse_pdf(file_bytes)
    elif file_type == "docx":
        return _parse_docx(file_bytes)
    elif file_type == "pptx":
        return _parse_pptx(file_bytes)
    else:
        raise DocumentParseError(f"Unsupported file type: {file_type}")


async def _parse_pdf(file_bytes: bytes) -> dict:
    """
    Parse PDF using Marker (GPU-accelerated).
    Falls back to PyMuPDF (CPU-only) on failure.
    Returns dict: {"content": markdown_str, "page_count": int}.
    """
    import logging
    _log = logging.getLogger("document.parser")

    if not file_bytes:
        _log.error("PDF bytes are empty or None — cannot parse")
        raise DocumentParseError("PDF file bytes are empty")

    # Try marker first (requires GPU for best quality)
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import load_all_models

        _log.info("Parsing PDF with marker-pdf (%d bytes)", len(file_bytes))
        models = load_all_models()
        converter = PdfConverter(artifact_dict=models, batch_idx=0)
        rendered = converter(file_bytes)
        content = rendered.markdown
        page_count = (
            rendered.page_count
            if hasattr(rendered, "page_count") and rendered.page_count
            else _count_pdf_pages(file_bytes)
        )
        _log.info("Marker parsed %d pages, content length=%d", page_count, len(content))
        return {"content": content, "page_count": page_count}

    except Exception as marker_err:
        _log.warning("Marker failed (%s), falling back to PyMuPDF", marker_err)
        # Ensure we pass a FRESH bytes object — not a consumed stream
        fresh_bytes = bytes(file_bytes)
        return _parse_pdf_pymupdf(fresh_bytes)


def _parse_pdf_pymupdf(file_bytes: bytes) -> dict:
    """Fallback PDF parser using PyMuPDF (CPU-only)."""
    import fitz  # PyMuPDF

    if not file_bytes:
        raise DocumentParseError("PDF bytes are empty — cannot parse")

    # Wrap in BytesIO to ensure a seekable, stable buffer.
    # Some PyMuPDF versions behave better with BytesIO than raw bytes.
    try:
        doc = fitz.open(stream=io.BytesIO(file_bytes), filetype="pdf")
    except Exception as e:
        raise DocumentParseError(f"PyMuPDF could not open PDF stream: {e}")

    lines: list[str] = []
    prev_heading_level = 0
    page_count = len(doc)

    # Pre-scan first 3 pages for typical heading font sizes
    # This helps establish baseline for this document
    heading_sizes: dict[float, int] = {}  # size -> count
    for page_num in range(min(3, page_count)):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
        for block in blocks:
            if "lines" not in block:
                continue
            for bline in block["lines"]:
                text = "".join(s["text"] for s in bline.get("spans", [])).strip()
                if not text or len(text) > 200:
                    continue
                for span in bline.get("spans", []):
                    size = span.get("size", 0)
                    if size >= 10:
                        heading_sizes[size] = heading_sizes.get(size, 0) + 1

    # Determine dominant large font sizes = likely heading sizes
    sorted_sizes = sorted(heading_sizes.items(), key=lambda x: -x[0])
    h1_size = sorted_sizes[0][0] if sorted_sizes else 0
    h2_size = sorted_sizes[1][0] if len(sorted_sizes) > 1 else 0
    h3_size = sorted_sizes[2][0] if len(sorted_sizes) > 2 else 0

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text("text")
        page_lines = text.split("\n")

        # Build a lookup: text -> (font_size, is_bold) using dict spans
        span_info: dict[str, list[tuple[float, bool]]] = {}
        try:
            block_dict = page.get_text("dict").get("blocks", [])
            for block in block_dict:
                if "lines" not in block:
                    continue
                for bline in block["lines"]:
                    line_text = "".join(s["text"] for s in bline.get("spans", [])).strip()
                    if not line_text:
                        continue
                    for span in bline.get("spans", []):
                        span_text = span.get("text", "").strip()
                        if span_text:
                            info_list = span_info.setdefault(line_text, [])
                            is_b = _is_bold(span)
                            size = span.get("size", 0)
                            if (size, is_b) not in info_list:
                                info_list.append((size, is_b))
        except Exception:
            pass

        for line in page_lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Look up formatting info
            font_size: float | None = None
            is_bold = False
            for lt, infos in span_info.items():
                if line_stripped in lt or lt in line_stripped:
                    for s, b in infos:
                        if s > 0:
                            font_size = s
                            is_bold = is_bold or b

            # Use document-specific heading sizes if available, otherwise fall back to defaults
            h1 = max(h1_size, 20)
            h2 = max(h2_size, 16)
            h3 = max(h3_size, 14)

            # Estimate heading level
            level = 0
            if font_size:
                if font_size >= h1:
                    level = 1
                elif font_size >= h2:
                    level = 2
                elif font_size >= h3:
                    level = 3
                elif is_bold and font_size >= 12:
                    level = 3

            if level > 0:
                heading_mark = "#" * min(level, 6)
                lines.append(f"{heading_mark} {line_stripped}")
                prev_heading_level = level
            else:
                lines.append(line_stripped)

        lines.append(f"\n<!-- Page {page_num + 1} -->\n")

    doc.close()
    return {"content": "\n".join(lines), "page_count": page_count}


def _count_pdf_pages(file_bytes: bytes) -> int:
    """Count PDF pages using PyMuPDF."""
    import fitz
    try:
        doc = fitz.open(stream=io.BytesIO(file_bytes), filetype="pdf")
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


def _get_font_size(page, line: str) -> float | None:
    """Get font size of a line in PyMuPDF page."""
    try:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" in block:
                for bline in block["lines"]:
                    text = "".join(span["text"] for span in bline["spans"])
                    if line.strip() in text or text.strip() in line.strip():
                        for span in bline["spans"]:
                            if span["text"].strip():
                                return span["size"]
    except Exception:
        pass
    return None


def _is_bold(span: dict) -> bool:
    """Check if a span has bold font."""
    try:
        font_name = span.get("font", "").lower()
        return "bold" in font_name or "black" in font_name or span.get("flags", 0) & 1
    except Exception:
        return False


def _is_centered(bline: dict) -> bool:
    """Check if a line is centered on the page."""
    try:
        bbox = bline.get("bbox", [])
        if len(bbox) < 4:
            return False
        # Centered lines typically have bbox center near page center
        return True  # heuristic fallback
    except Exception:
        return False


def _estimate_heading_level(font_size: float, text: str, is_bold: bool = False) -> int:
    """Estimate heading level from font size and formatting clues."""
    # If text is bold and large, it's very likely a heading
    if text.isupper() and len(text) < 100:
        # ALL CAPS short text is almost certainly a heading
        if font_size >= 14:
            if font_size >= 22:
                return 1
            return 2
    if is_bold:
        if font_size >= 22:
            return 1
        elif font_size >= 18:
            return 2
        elif font_size >= 14:
            return 3
        return 4
    # Non-bold but large text
    if font_size >= 22:
        return 1
    elif font_size >= 18:
        return 2
    elif font_size >= 14:
        return 3
    return 0  # Not a heading


def _parse_docx(file_bytes: bytes) -> dict:
    """Parse DOCX using python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    lines: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            lines.append("")
            continue

        style_name = para.style.name.lower() if para.style else ""

        if "heading 1" in style_name or "title" in style_name:
            lines.append(f"# {text}")
        elif "heading 2" in style_name:
            lines.append(f"## {text}")
        elif "heading 3" in style_name:
            lines.append(f"### {text}")
        elif "heading 4" in style_name:
            lines.append(f"#### {text}")
        else:
            lines.append(text)

    for table in doc.tables:
        lines.append("\n| " + " | ".join("Column" for _ in table.columns) + " |")
        lines.append("|" + "|".join("---" for _ in table.columns) + "|")
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    return {"content": "\n".join(lines), "page_count": len(doc.sections)}


def _parse_pptx(file_bytes: bytes) -> dict:
    """Parse PPTX using python-pptx."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation(io.BytesIO(file_bytes))
    lines: list[str] = []

    for slide_num, slide in enumerate(prs.slides, start=1):
        title = _get_slide_title(slide)
        if title:
            lines.append(f"## Slide {slide_num}: {title}")
        else:
            lines.append(f"## Slide {slide_num}")

        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                if shape == _get_slide_title_shape(slide):
                    continue
                lines.append(shape.text.strip())

        lines.append("")

    return {"content": "\n".join(lines), "page_count": len(prs.slides)}


def _get_slide_title(slide) -> str | None:
    """Extract slide title."""
    for shape in slide.shapes:
        if shape.has_text_frame:
            if hasattr(shape, "is_placeholder") and shape.is_placeholder:
                pp = shape.placeholder_format
                if pp.type == 1:  # TITLE
                    return shape.text.strip()
    return None


def _get_slide_title_shape(slide):
    """Get the title shape for exclusion."""
    for shape in slide.shapes:
        if hasattr(shape, "is_placeholder") and shape.is_placeholder:
            pp = shape.placeholder_format
            if pp.type == 1:
                return shape
    return None
