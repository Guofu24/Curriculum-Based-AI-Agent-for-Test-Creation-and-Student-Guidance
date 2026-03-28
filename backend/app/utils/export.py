"""Export utilities: PDF (WeasyPrint) and DOCX."""

from io import BytesIO
from typing import Any
import html

from weasyprint import HTML, CSS


# ── PDF Export ────────────────────────────────────────────────────────────────

def export_exam_to_pdf(exam_data: dict) -> bytes:
    """
    Export an exam to PDF using WeasyPrint.

    exam_data format:
    {
        "title": "Đề kiểm tra Vật lý 11",
        "scope": ["Chương 1", "Chương 2"],
        "questions": [...],
        "show_answers": bool,
        "include_rubric": bool,
    }
    """
    html_content = _build_exam_html(exam_data)

    pdf_buffer = BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    return pdf_buffer.read()


def _build_exam_html(exam_data: dict) -> str:
    """Build HTML for exam export."""
    title = html.escape(exam_data.get("title", "Đề kiểm tra"))
    questions = exam_data.get("questions", [])
    show_answers = exam_data.get("show_answers", False)
    include_rubric = exam_data.get("include_rubric", False)
    scope = exam_data.get("scope", [])

    # Separate MCQ and Essay
    mcq_questions = [q for q in questions if q.get("type") == "mcq"]
    essay_questions = [q for q in questions if q.get("type") == "essay"]

    # Build HTML
    html_parts = [
        _pdf_header(title, scope),
        _pdf_css(),
        "<body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='scope'>Phạm vi: {', '.join(html.escape(str(s)) for s in scope)}</p>",
    ]

    # MCQ Section
    if mcq_questions:
        html_parts.append("<h2>Phần I: Trắc nghiệm</h2>")
        html_parts.append("<p>Hãy chọn đáp án đúng nhất.</p>")
        for i, q in enumerate(mcq_questions, 1):
            html_parts.append(_render_mcq_html(q, i, show_answers))

    # Essay Section
    if essay_questions:
        html_parts.append("<h2>Phần II: Tự luận</h2>")
        html_parts.append("<p>Hãy trình bày lời giải chi tiết.</p>")
        for i, q in enumerate(essay_questions, 1):
            html_parts.append(_render_essay_html(q, i, show_answers, include_rubric))

    html_parts.append("</body></html>")

    return "\n".join(html_parts)


def _pdf_header(title: str, scope: list) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{html.escape(title)}</title>
"""


def _pdf_css() -> str:
    return """
<style>
    @page {{
        size: A4;
        margin: 2cm;
        @top-center {{
            content: "Đề kiểm tra";
        }}
        @bottom-right {{
            content: "Trang " counter(page) " / " counter(pages);
        }}
    }}
    body {{
        font-family: 'Times New Roman', serif;
        font-size: 12pt;
        line-height: 1.6;
    }}
    h1 {{
        text-align: center;
        font-size: 16pt;
        margin-bottom: 0.5em;
    }}
    h2 {{
        font-size: 13pt;
        margin-top: 1.5em;
        border-bottom: 1px solid #333;
        padding-bottom: 0.3em;
    }}
    .scope {{
        text-align: center;
        font-style: italic;
        color: #666;
    }}
    .question {{
        margin: 1em 0;
        padding: 0.5em;
    }}
    .question-stem {{
        font-weight: bold;
        margin-bottom: 0.5em;
    }}
    .options {{
        margin-left: 1.5em;
    }}
    .option {{
        margin: 0.3em 0;
    }}
    .answer {{
        color: green;
        font-weight: bold;
    }}
    .rubric {{
        margin-left: 1.5em;
        font-size: 11pt;
        color: #444;
    }}
    .rubric-row {{
        margin: 0.2em 0;
    }}
</style>
"""


def _render_mcq_html(q: dict, index: int, show_answer: bool) -> str:
    """Render a single MCQ question as HTML."""
    stem = html.escape(q.get("stem", ""))
    options = q.get("options", {})
    correct = q.get("correct_answer", "")
    explanation = q.get("explanation", "")

    parts = [
        f"<div class='question'>",
        f"<div class='question-stem'>Câu {index}. {stem}</div>",
        "<div class='options'>",
    ]

    for opt_key in ["A", "B", "C", "D"]:
        opt_text = html.escape(str(options.get(opt_key, "")))
        if show_answer and opt_key == correct:
            parts.append(f"<div class='option answer'>□ {opt_key}. {opt_text} ✓</div>")
        else:
            parts.append(f"<div class='option'>□ {opt_key}. {opt_text}</div>")

    parts.append("</div>")  # options

    if show_answer and explanation:
        parts.append(f"<div class='answer'>Giải thích: {html.escape(explanation)}</div>")

    parts.append("</div>")
    return "\n".join(parts)


def _render_essay_html(q: dict, index: int, show_answer: bool, include_rubric: bool) -> str:
    """Render a single essay question as HTML."""
    stem = html.escape(q.get("stem", ""))
    rubric = q.get("rubric", [])
    time_est = q.get("estimated_solve_time_minutes")

    parts = [
        f"<div class='question'>",
        f"<div class='question-stem'>Câu {index}. {stem}</div>",
    ]

    if time_est:
        parts.append(f"<p>Thời gian ước tính: {time_est} phút</p>")

    if include_rubric and rubric:
        parts.append("<div class='rubric'>")
        parts.append("<strong>Đáp án và thang điểm:</strong>")
        for r in rubric:
            score = r.get("score", 0)
            desc = html.escape(r.get("description", ""))
            parts.append(f"<div class='rubric-row'>{score} điểm: {desc}</div>")
        parts.append("</div>")

    # Answer space
    if show_answer:
        parts.append("<div style='margin-top: 1em; border-top: 1px dashed #ccc; padding-top: 1em;'>")
        parts.append("<em>(Đáp án mẫu)</em>")
        parts.append("</div>")

    parts.append("</div>")
    return "\n".join(parts)


# ── DOCX Export ──────────────────────────────────────────────────────────────

def export_exam_to_docx(exam_data: dict) -> bytes:
    """
    Export an exam to DOCX using python-docx.
    """
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.style import WD_STYLE_TYPE

    doc = Document()

    # Title
    title = exam_data.get("title", "Đề kiểm tra")
    heading = doc.add_heading(title, level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Scope
    scope = exam_data.get("scope", [])
    if scope:
        scope_para = doc.add_paragraph(f"Phạm vi: {', '.join(str(s) for s in scope)}")
        scope_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        scope_para.runs[0].italic = True

    questions = exam_data.get("questions", [])
    show_answers = exam_data.get("show_answers", False)
    include_rubric = exam_data.get("include_rubric", False)

    mcq_questions = [q for q in questions if q.get("type") == "mcq"]
    essay_questions = [q for q in questions if q.get("type") == "essay"]

    # MCQ Section
    if mcq_questions:
        doc.add_heading("Phần I: Trắc nghiệm", level=2)
        doc.add_paragraph("Hãy chọn đáp án đúng nhất.")

        for i, q in enumerate(mcq_questions, 1):
            stem = q.get("stem", "")
            options = q.get("options", {})
            correct = q.get("correct_answer", "")
            explanation = q.get("explanation", "")

            # Question stem
            p = doc.add_paragraph()
            run = p.add_run(f"Câu {i}. {stem}")
            run.bold = True

            # Options
            for opt_key in ["A", "B", "C", "D"]:
                opt_text = str(options.get(opt_key, ""))
                opt_para = doc.add_paragraph(f"  {opt_key}. {opt_text}")
                if show_answers and opt_key == correct:
                    opt_para.runs[0].bold = True

            if show_answers and explanation:
                ans_para = doc.add_paragraph()
                run = ans_para.add_run(f"Đáp án: {correct} — {explanation}")
                run.font.color.rgb = RGBColor(0, 128, 0)

    # Essay Section
    if essay_questions:
        doc.add_heading("Phần II: Tự luận", level=2)
        doc.add_paragraph("Hãy trình bày lời giải chi tiết.")

        for i, q in enumerate(essay_questions, 1):
            stem = q.get("stem", "")
            rubric = q.get("rubric", [])
            time_est = q.get("estimated_solve_time_minutes")

            # Question stem
            p = doc.add_paragraph()
            run = p.add_run(f"Câu {i}. {stem}")
            run.bold = True

            if time_est:
                doc.add_paragraph(f"Thời gian ước tính: {time_est} phút")

            if include_rubric and rubric:
                doc.add_paragraph("Đáp án và thang điểm:")
                for r in rubric:
                    score = r.get("score", 0)
                    desc = r.get("description", "")
                    doc.add_paragraph(f"  {score} điểm: {desc}")

    # Save to bytes
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()
