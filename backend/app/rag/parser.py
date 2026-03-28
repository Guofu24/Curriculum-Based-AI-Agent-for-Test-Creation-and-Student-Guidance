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
    Parse PDF using Marker.
    Marker preserves heading hierarchy, tables, and formulas.
    Falls back to PyMuPDF if Marker fails.
    Returns dict: {"content": markdown_str, "page_count": int}.
    """
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import load_all_models

        models = load_all_models()
        converter = PdfConverter(artifact_dict=models, batch_idx=0)
        rendered = converter(file_bytes)
        content = rendered.markdown
        page_count = rendered.page_count if hasattr(rendered, 'page_count') else _count_pdf_pages(file_bytes)
        return {"content": content, "page_count": page_count}
    except Exception:
        return _parse_pdf_pymupdf(file_bytes)


def _parse_pdf_pymupdf(file_bytes: bytes) -> dict:
    """Fallback PDF parser using PyMuPDF."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    lines: list[str] = []
    prev_heading_level = 0

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text")
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            font_size = _get_font_size(page, line)

            if font_size and font_size >= 14:
                level = _estimate_heading_level(font_size, line)
                if level > prev_heading_level:
                    heading_mark = "#" * min(level, 6)
                    lines.append(f"{heading_mark} {line}")
                    prev_heading_level = level
                elif level < prev_heading_level:
                    prev_heading_level = level
                    heading_mark = "#" * min(level, 6)
                    lines.append(f"{heading_mark} {line}")
                else:
                    lines.append(f"## {line}")
            else:
                lines.append(line)

        lines.append(f"\n<!-- Page {page_num} -->\n")

    doc.close()
    return {"content": "\n".join(lines), "page_count": len(doc)}


def _count_pdf_pages(file_bytes: bytes) -> int:
    """Count PDF pages using PyMuPDF."""
    import fitz
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
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


def _estimate_heading_level(font_size: float, text: str) -> int:
    """Estimate heading level from font size."""
    if font_size >= 22:
        return 1  # Chapter
    elif font_size >= 18:
        return 2  # Section
    elif font_size >= 14:
        return 3  # Subsection
    return 4


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
