"""Export exam to PDF (WeasyPrint) and DOCX (python-docx) formats.

G12: include_answers param — False = bản học sinh, True = bản giáo viên
     include_blueprint param (PDF) — thêm bảng phân bổ Bloom ở đầu file
"""

from io import BytesIO
from typing import Any
from uuid import UUID
import html
import re

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

# WeasyPrint requires GTK (libgobject) — not available on plain Windows.
# Import lazily inside export_pdf() so the server can start without GTK installed.
# On Linux / Docker the import will succeed normally at call-time.


# ── Constants ─────────────────────────────────────────────────────────────────

MAX_PDF_SIZE_MB = 10
MAX_DOCX_SIZE_MB = 10
VIETNAMESE_FONT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;700&display=swap');
body {
    font-family: 'Noto Sans', 'DejaVu Sans', 'Arial Unicode MS', sans-serif;
    font-size: 12pt;
    line-height: 1.7;
}
"""


# ── ExamExporter ────────────────────────────────────────────────────────────────

class ExamExporter:
    """
    Export exam to PDF and DOCX with optional answer key and blueprint table.

    G12: include_answers=False → bản học sinh (không đáp án)
         include_answers=True  → bản giáo viên (có đáp án)
    include_blueprint (PDF only) → thêm bảng phân bổ Bloom ở đầu file
    """

    def __init__(self, exam_service):
        """
        Args:
            exam_service: ExamService instance with get_exam() method.
        """
        self.exam_service = exam_service

    async def export_pdf(
        self,
        exam_id: UUID,
        include_answers: bool = False,
        include_blueprint: bool = False,
    ) -> bytes:
        """
        Export exam as PDF using WeasyPrint.

        Args:
            exam_id: UUID of the exam to export.
            include_answers: True → thêm đáp án ở cuối file (bản giáo viên)
            include_blueprint: True → thêm bảng phân bổ Bloom ở đầu file

        Returns:
            PDF bytes (max 10MB enforced by caller).

        Raises:
            ExamServiceError: if exam not found.
        """
        try:
            exam = await self.exam_service.get_exam(exam_id, user_id=None)
            if not exam:
                from app.services.exam_service import ExamServiceError
                raise ExamServiceError("Exam not found")

            questions = exam.questions or []
            blueprint = exam.blueprint or {}
            html_content = self._render_html(exam, questions, blueprint, include_answers, include_blueprint)

            from weasyprint import HTML  # lazy — requires GTK on Linux/Docker
            pdf_buffer = BytesIO()
            HTML(string=html_content).write_pdf(pdf_buffer)
            pdf_buffer.seek(0)
            pdf_bytes = pdf_buffer.read()

            # G12: size guard — reject oversized PDFs before returning
            size_mb = len(pdf_bytes) / (1024 * 1024)
            if size_mb > MAX_PDF_SIZE_MB:
                from app.services.exam_service import ExamServiceError
                raise ExamServiceError(
                    f"PDF exceeds {MAX_PDF_SIZE_MB}MB limit ({size_mb:.1f}MB). "
                    "Try reducing question count or content."
                )

            return pdf_bytes
        except OSError as e:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=501,
                detail=f"PDF export không khả dụng trên Windows (thiếu GTK). Dùng DOCX thay thế."
            )

    async def export_docx(
        self,
        exam_id: UUID,
        include_answers: bool = False,
    ) -> bytes:
        """
        Export exam as DOCX using python-docx.

        Args:
            exam_id: UUID of the exam to export.
            include_answers: True → thêm đáp án ở cuối file (bản giáo viên)

        Returns:
            DOCX bytes (max 10MB enforced by caller).

        Raises:
            ExamServiceError: if exam not found.
        """
        exam = await self.exam_service.get_exam(exam_id, user_id=None)
        if not exam:
            from app.services.exam_service import ExamServiceError
            raise ExamServiceError("Exam not found")

        questions = exam.questions or []
        doc = self._build_docx(exam, questions, include_answers)

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        docx_bytes = buffer.read()

        size_mb = len(docx_bytes) / (1024 * 1024)
        if size_mb > MAX_DOCX_SIZE_MB:
            from app.services.exam_service import ExamServiceError
            raise ExamServiceError(
                f"DOCX exceeds {MAX_DOCX_SIZE_MB}MB limit ({size_mb:.1f}MB). "
                "Try reducing question count or content."
            )

        return docx_bytes

    # ── PDF HTML rendering ─────────────────────────────────────────────────────

    def _render_html(
        self,
        exam,
        questions: list[dict],
        blueprint: dict,
        include_answers: bool,
        include_blueprint: bool,
    ) -> str:
        """
        Render exam to HTML string for WeasyPrint.

        - Vietnamese font: Noto Sans via Google Fonts CDN + DejaVu Sans fallback
        - MCQ and Essay sections separated
        - Answer key appended at end when include_answers=True
        - Blueprint table at top when include_blueprint=True
        """
        title = html.escape(exam.title or "Đề kiểm tra")
        scope = exam.scope or []
        mcq_questions = [q for q in questions if q.get("type") == "mcq" or q.get("question_type") == "mcq"]
        essay_questions = [q for q in questions if q.get("type") == "essay" or q.get("question_type") == "essay"]

        html_parts: list[str] = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "<meta charset='utf-8'>",
            f"<title>{title}</title>",
            self._pdf_css(),
            "</head>",
            "<body>",
            self._render_exam_header(title, scope),
        ]

        if include_blueprint and blueprint:
            html_parts.append(self._render_blueprint_table(blueprint))
            html_parts.append("<hr/>")

        if mcq_questions:
            html_parts.append("<h2>Phần I: Trắc nghiệm</h2>")
            html_parts.append("<p>Hãy chọn đáp án đúng nhất.</p>")
            for i, q in enumerate(mcq_questions, 1):
                html_parts.append(self._render_mcq_html(q, i, include_answers))

        if essay_questions:
            html_parts.append("<h2>Phần II: Tự luận</h2>")
            html_parts.append("<p>Hãy trình bày lời giải chi tiết.</p>")
            for i, q in enumerate(essay_questions, 1):
                html_parts.append(self._render_essay_html(q, i, include_answers))

        if include_answers:
            html_parts.append(self._render_answer_key(questions))

        html_parts.append("</body></html>")
        return "\n".join(html_parts)

    def _pdf_css(self) -> str:
        return f"""
<style>
{VIETNAMESE_FONT_CSS}

    @page {{
        size: A4;
        margin: 2cm 1.8cm;
        @top-center {{
            content: "Đề kiểm tra";
            font-size: 10pt;
            color: #666;
        }}
        @bottom-right {{
            content: "Trang " counter(page) " / " counter(pages);
            font-size: 9pt;
            color: #999;
        }}
    }}

    h1 {{
        text-align: center;
        font-size: 16pt;
        font-weight: bold;
        margin-bottom: 0.3em;
        color: #1a1a1a;
    }}
    .exam-meta {{
        text-align: center;
        color: #555;
        font-size: 11pt;
        margin-bottom: 1.5em;
    }}
    h2 {{
        font-size: 13pt;
        font-weight: bold;
        margin-top: 1.5em;
        margin-bottom: 0.5em;
        border-bottom: 1.5px solid #333;
        padding-bottom: 0.3em;
        color: #1a1a1a;
    }}
    .section-instruction {{
        font-style: italic;
        color: #444;
        margin-bottom: 0.8em;
    }}
    .question {{
        margin: 1em 0;
        padding: 0.6em 0.8em;
    }}
    .question-stem {{
        font-weight: bold;
        margin-bottom: 0.5em;
        line-height: 1.5;
    }}
    .options {{
        margin-left: 1.2em;
    }}
    .option {{
        margin: 0.3em 0;
        line-height: 1.4;
    }}
    .option-correct {{
        color: #1a7f1a;
        font-weight: bold;
    }}
    .answer-block {{
        color: #1a7f1a;
        font-weight: bold;
        margin-top: 0.3em;
        font-size: 11pt;
    }}
    .explanation {{
        font-style: italic;
        color: #555;
        font-size: 10.5pt;
        margin-top: 0.2em;
    }}
    .rubric {{
        margin-left: 1.2em;
        font-size: 11pt;
        color: #333;
    }}
    .rubric-row {{
        margin: 0.25em 0;
    }}
    .answer-key {{
        page-break-before: always;
        margin-top: 2em;
    }}
    .answer-key h2 {{
        color: #1a7f1a;
    }}
    .answer-key-table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 1em;
        font-size: 11pt;
    }}
    .answer-key-table th, .answer-key-table td {{
        border: 1px solid #bbb;
        padding: 0.4em 0.7em;
        text-align: center;
    }}
    .answer-key-table th {{
        background-color: #e8f5e9;
        font-weight: bold;
    }}
    .answer-key-table tr:nth-child(even) td {{
        background-color: #f9f9f9;
    }}

    /* Blueprint table */
    .blueprint-table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 1.5em;
        font-size: 10.5pt;
    }}
    .blueprint-table th, .blueprint-table td {{
        border: 1px solid #aaa;
        padding: 0.4em 0.6em;
        text-align: center;
    }}
    .blueprint-table th {{
        background-color: #e3f2fd;
        font-weight: bold;
    }}
    .blueprint-table .chapter-col {{
        text-align: left !important;
    }}
    .blueprint-table tr:nth-child(even) td {{
        background-color: #f5f5f5;
    }}
    .blueprint-table .total-row td {{
        background-color: #e8f5e9;
        font-weight: bold;
    }}
</style>
"""

    def _render_exam_header(self, title: str, scope: list) -> str:
        scope_str = ", ".join(html.escape(str(s)) for s in scope) if scope else "(không giới hạn)"
        return f"""
<h1>{title}</h1>
<p class='exam-meta'>Phạm vi: {scope_str}</p>
"""

    def _render_mcq_html(self, q: dict, index: int, include_answers: bool) -> str:
        """Render MCQ question. Options may be dict {A: text, B: text, ...} or list [{label, text}, ...]."""
        stem = self._render_latex(html.escape(q.get("stem", "")))
        options = q.get("options", {})
        correct = str(q.get("correct_answer", "")).strip()
        explanation = html.escape(q.get("explanation", ""))

        # Normalize options — support both dict and list-of-dict formats
        opts = self._normalize_options(options)

        parts = [
            f"<div class='question'>",
            f"<div class='question-stem'>Câu {index}. {stem}</div>",
            "<div class='options'>",
        ]

        for label, text in opts:
            escaped_text = self._render_latex(html.escape(str(text)))
            is_correct = label.upper() == correct.upper()
            if include_answers and is_correct:
                parts.append(f"<div class='option option-correct'>○ {label}. {escaped_text} ★</div>")
            else:
                parts.append(f"<div class='option'>○ {label}. {escaped_text}</div>")

        if include_answers:
            if explanation:
                parts.append(f"<div class='answer-block'>Giải thích: <span class='explanation'>{explanation}</span></div>")

        parts.append("</div></div>")
        return "\n".join(parts)

    def _render_essay_html(self, q: dict, index: int, include_answers: bool) -> str:
        """Render essay question with rubric."""
        stem = self._render_latex(html.escape(q.get("stem", "")))
        rubric = q.get("rubric") or []
        time_est = q.get("estimated_solve_time_minutes")

        parts = [
            f"<div class='question'>",
            f"<div class='question-stem'>Câu {index}. {stem}</div>",
        ]

        if time_est:
            parts.append(f"<p>Thời gian ước tính: {time_est} phút</p>")

        if include_answers and rubric:
            parts.append("<div class='rubric'>")
            parts.append("<strong>Đáp án và thang điểm:</strong>")
            for r in rubric:
                score = r.get("score", 0)
                desc = self._render_latex(html.escape(r.get("description", "")))
                parts.append(f"<div class='rubric-row'>{score} điểm: {desc}</div>")
            parts.append("</div>")

        parts.append("</div>")
        return "\n".join(parts)

    def _render_answer_key(self, questions: list[dict]) -> str:
        """Render answer key at end of PDF (teacher version)."""
        mcq_questions = [q for q in questions if q.get("type") == "mcq" or q.get("question_type") == "mcq"]
        essay_questions = [q for q in questions if q.get("type") == "essay" or q.get("question_type") == "essay"]

        rows: list[str] = []
        if mcq_questions:
            rows.append("<h3>Đáp án trắc nghiệm</h3>")
            rows.append("<table class='answer-key-table'>")
            rows.append("<tr><th>Câu</th><th>Đáp án</th><th>Bloom</th><th>Độ khó</th></tr>")
            for i, q in enumerate(mcq_questions, 1):
                ans = q.get("correct_answer", "-")
                bloom = q.get("bloom_level", "-")
                diff = q.get("difficulty_level", "-")
                rows.append(f"<tr><td>{i}</td><td>{html.escape(str(ans))}</td><td>{html.escape(bloom)}</td><td>{html.escape(diff)}</td></tr>")
            rows.append("</table>")

        if essay_questions:
            rows.append("<h3>Đáp án tự luận</h3>")
            rows.append("<table class='answer-key-table'>")
            rows.append("<tr><th>Câu</th><th>Bloom</th><th>Độ khó</th><th>Thang điểm</th></tr>")
            for i, q in enumerate(essay_questions, 1):
                bloom = q.get("bloom_level", "-")
                diff = q.get("difficulty_level", "-")
                rubric = q.get("rubric") or []
                rubric_str = "; ".join(f"{r.get('score', 0)}đ: {r.get('description', '')[:40]}" for r in rubric)
                rows.append(
                    f"<tr><td>{i}</td><td>{html.escape(bloom)}</td><td>{html.escape(diff)}</td>"
                    f"<td style='text-align:left'>{html.escape(rubric_str[:80])}</td></tr>"
                )
            rows.append("</table>")

        return f"""
<div class='answer-key'>
    <h2>ĐÁP ÁN (Phiên bản giáo viên)</h2>
    {"".join(rows)}
</div>
"""

    def _render_blueprint_table(self, blueprint: dict) -> str:
        """
        Render Bloom distribution blueprint table at the top of the PDF.

        blueprint format:
        {
            "distribution": {"nhan_biet": 20, "thong_hieu": 30, ...},
            "chapters": [{"name": "Chương 1", "nhan_biet": 5, ...}, ...],
            "summary": {...}
        }
        """
        distribution = blueprint.get("distribution", {})
        chapters = blueprint.get("chapters", [])

        headers = ["Chương", "Nhận biết", "Thông hiểu", "Vận dụng", "Vận dụng cao", "Tổng"]
        bloom_keys = ["nhan_biet", "thong_hieu", "van_dung", "van_dung_cao"]

        rows = [
            "<table class='blueprint-table'>",
            "<tr>",
            *[f"<th>{h}</th>" for h in headers],
            "</tr>",
        ]

        for ch in chapters:
            name = html.escape(str(ch.get("name", "")))
            vals = [ch.get(k, 0) for k in bloom_keys]
            total = sum(vals)
            cells = [f"<td class='chapter-col'>{name}</td>"]
            cells += [f"<td>{v}</td>" for v in vals]
            cells.append(f"<td><strong>{total}</strong></td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")

        # Total row
        dist_vals = [distribution.get(k, 0) for k in bloom_keys]
        dist_total = sum(dist_vals)
        total_cells = [f"<td class='chapter-col'><strong>Tổng</strong></td>"]
        total_cells += [f"<td><strong>{v}</strong></td>" for v in dist_vals]
        total_cells.append(f"<td><strong>{dist_total}</strong></td>")
        rows.append(f"<tr class='total-row'>{''.join(total_cells)}</tr>")
        rows.append("</table>")

        return f"""
<div class='blueprint-section'>
    <h3>Bảng phân bổ Bloom (Mục tiêu)</h3>
    {"".join(rows)}
</div>
"""

    # ── DOCX building ─────────────────────────────────────────────────────────

    def _build_docx(self, exam, questions: list[dict], include_answers: bool) -> Document:
        """
        Build python-docx Document with exam content.

        G12: include_answers=True → thêm answer key ở cuối DOCX
        """
        doc = Document()
        self._docx_set_default_style(doc)

        title = exam.title or "Đề kiểm tra"
        scope = exam.scope or []

        # Title
        heading = doc.add_heading(title, level=0)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Scope
        if scope:
            p = doc.add_paragraph(f"Phạm vi: {', '.join(str(s) for s in scope)}")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.runs[0].italic = True
            p.runs[0].font.size = Pt(11)

        doc.add_paragraph()  # spacing

        mcq_questions = [q for q in questions if q.get("type") == "mcq" or q.get("question_type") == "mcq"]
        essay_questions = [q for q in questions if q.get("type") == "essay" or q.get("question_type") == "essay"]

        if mcq_questions:
            doc.add_heading("Phần I: Trắc nghiệm", level=2)
            p = doc.add_paragraph("Hãy chọn đáp án đúng nhất.")
            p.runs[0].italic = True

            for i, q in enumerate(mcq_questions, 1):
                self._docx_add_mcq(doc, q, i, include_answers)

        if essay_questions:
            doc.add_heading("Phần II: Tự luận", level=2)
            p = doc.add_paragraph("Hãy trình bày lời giải chi tiết.")
            p.runs[0].italic = True

            for i, q in enumerate(essay_questions, 1):
                self._docx_add_essay(doc, q, i, include_answers)

        if include_answers:
            self._docx_add_answer_key(doc, questions)

        return doc

    def _docx_set_default_style(self, doc: Document) -> None:
        """Set document-wide defaults for Vietnamese text."""
        style = doc.styles["Normal"]
        style.font.name = "Noto Sans"
        style.font.size = Pt(12)
        try:
            style.element.rPr.rFonts.set(
                doc.styles.element.nsmap["w"],
                "Noto Sans"
            )
        except Exception:
            pass

    def _docx_add_mcq(
        self, doc: Document, q: dict, index: int, include_answers: bool
    ) -> None:
        """Add a single MCQ question to the DOCX document."""
        stem = self._strip_latex(q.get("stem", ""))
        options = q.get("options", {})
        correct = str(q.get("correct_answer", "")).strip()
        explanation = q.get("explanation", "")
        opts = self._normalize_options(options)

        # Question stem
        p = doc.add_paragraph()
        run = p.add_run(f"Câu {index}. {stem}")
        run.bold = True
        run.font.size = Pt(12)

        # Options
        for label, text in opts:
            opt_para = doc.add_paragraph(style="List Bullet")
            opt_para.paragraph_format.left_indent = Inches(0.4)
            opt_text = self._strip_latex(str(text))
            run = opt_para.add_run(f"{label}. {opt_text}")
            is_correct = label.upper() == correct.upper()
            if include_answers and is_correct:
                run.font.color.rgb = RGBColor(0x1A, 0x7F, 0x1A)
                run.bold = True

        # Explanation (teacher version only)
        if include_answers and explanation:
            p = doc.add_paragraph()
            run = p.add_run(f"Giải thích: {self._strip_latex(explanation)}")
            run.font.size = Pt(11)
            run.italic = True
            run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    def _docx_add_essay(
        self, doc: Document, q: dict, index: int, include_answers: bool
    ) -> None:
        """Add a single essay question to the DOCX document."""
        stem = self._strip_latex(q.get("stem", ""))
        rubric = q.get("rubric") or []
        time_est = q.get("estimated_solve_time_minutes")

        p = doc.add_paragraph()
        run = p.add_run(f"Câu {index}. {stem}")
        run.bold = True
        run.font.size = Pt(12)

        if time_est:
            p = doc.add_paragraph(f"Thời gian ước tính: {time_est} phút")
            p.runs[0].font.size = Pt(11)
            p.runs[0].italic = True

        if include_answers and rubric:
            doc.add_paragraph("Đáp án và thang điểm:")
            for r in rubric:
                score = r.get("score", 0)
                desc = self._strip_latex(r.get("description", ""))
                doc.add_paragraph(f"  {score} điểm: {desc}", style="List Bullet")

    def _docx_add_answer_key(self, doc: Document, questions: list[dict]) -> None:
        """Add answer key section to end of DOCX (teacher version)."""
        doc.add_page_break()
        doc.add_heading("ĐÁP ÁN (Phiên bản giáo viên)", level=2)

        mcq_questions = [q for q in questions if q.get("type") == "mcq" or q.get("question_type") == "mcq"]
        essay_questions = [q for q in questions if q.get("type") == "essay" or q.get("question_type") == "essay"]

        if mcq_questions:
            doc.add_heading("Trắc nghiệm", level=3)
            table = doc.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            hdr = table.rows[0].cells
            for cell, text in zip(hdr, ["Câu", "Đáp án", "Bloom", "Độ khó"]):
                cell.text = text
                cell.paragraphs[0].runs[0].bold = True

            for i, q in enumerate(mcq_questions, 1):
                row = table.add_row().cells
                row[0].text = str(i)
                row[1].text = str(q.get("correct_answer", "-"))
                row[2].text = str(q.get("bloom_level", "-"))
                row[3].text = str(q.get("difficulty_level", "-"))

        if essay_questions:
            doc.add_heading("Tự luận", level=3)
            table = doc.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            hdr = table.rows[0].cells
            for cell, text in zip(hdr, ["Câu", "Bloom", "Độ khó", "Thang điểm"]):
                cell.text = text
                cell.paragraphs[0].runs[0].bold = True

            for i, q in enumerate(essay_questions, 1):
                row = table.add_row().cells
                row[0].text = str(i)
                row[1].text = str(q.get("bloom_level", "-"))
                row[2].text = str(q.get("difficulty_level", "-"))
                rubric = q.get("rubric") or []
                rubric_str = "; ".join(f"{r.get('score', 0)}đ" for r in rubric)
                row[3].text = rubric_str or "-"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _normalize_options(self, options) -> list[tuple[str, str]]:
        """
        Normalize question options to list of (label, text) tuples.
        Supports:
          - dict: {"A": "text", "B": "text", ...}
          - list of dict: [{"label": "A", "text": "..."}, ...]
        """
        if isinstance(options, dict):
            return [(k, str(v)) for k, v in options.items()]
        if isinstance(options, list):
            result = []
            for opt in options:
                if isinstance(opt, dict):
                    label = str(opt.get("label", ""))
                    text = str(opt.get("text", ""))
                else:
                    label = ""
                    text = str(opt)
                result.append((label, text))
            return result
        return []

    def _render_latex(self, text: str) -> str:
        """
        Basic LaTeX-to-HTML renderer for inline math in PDF.
        Converts $...$ → <em>...</em> (simple fallback for WeasyPrint).
        For full LaTeX rendering use WeasyPrint's MathML support or
        a proper converter like MathJax/KaTeX in post-processing.
        """
        # Inline math: $...$
        text = re.sub(r"\$([^$]+)\$", r"<em>\1</em>", text)
        return text

    def _strip_latex(self, text: str) -> str:
        """
        Strip LaTeX math delimiters for DOCX output.
        $x^2$ → x^2
        """
        return re.sub(r"\$([^$]+)\$", r"\1", text)


# ── Legacy standalone functions (backwards-compatible) ───────────────────────

def export_exam_to_pdf(exam_data: dict) -> bytes:
    """
    Legacy synchronous PDF export.
    Wraps ExamExporter for backwards compatibility.
    """
    title = exam_data.get("title", "Đề kiểm tra")
    scope = exam_data.get("scope", [])
    questions = exam_data.get("questions", [])
    show_answers = exam_data.get("show_answers", False)
    include_rubric = exam_data.get("include_rubric", False)

    # Build a minimal mock exam object
    class _MockExam:
        def __init__(self):
            self.title = title
            self.scope = scope
            self.questions = questions
            self.blueprint = None
            self.exam_config = {}

    html = _build_exam_html(exam_data)
    from weasyprint import HTML  # lazy — requires GTK on Linux/Docker
    pdf_buffer = BytesIO()
    HTML(string=html).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)
    return pdf_buffer.read()


def export_exam_to_docx(exam_data: dict) -> bytes:
    """Legacy synchronous DOCX export for backwards compatibility."""
    _ = exam_data  # unused in legacy path — kept for API compat
    raise NotImplementedError(
        "Legacy export_exam_to_docx() is deprecated. "
        "Use ExamExporter.export_docx() instead."
    )


# ── Private helpers (keep existing _build_exam_html for legacy export) ─────────

def _build_exam_html(exam_data: dict) -> str:
    """Build HTML for exam export (legacy standalone path)."""
    title = html.escape(exam_data.get("title", "Đề kiểm tra"))
    questions = exam_data.get("questions", [])
    show_answers = exam_data.get("show_answers", False)
    include_rubric = exam_data.get("include_rubric", False)
    scope = exam_data.get("scope", [])

    mcq_questions = [q for q in questions if q.get("type") == "mcq"]
    essay_questions = [q for q in questions if q.get("type") == "essay"]

    html_parts = [
        _pdf_header(title, scope),
        _pdf_css(),
        "<body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='scope'>Phạm vi: {', '.join(html.escape(str(s)) for s in scope)}</p>",
    ]

    if mcq_questions:
        html_parts.append("<h2>Phần I: Trắc nghiệm</h2>")
        html_parts.append("<p>Hãy chọn đáp án đúng nhất.</p>")
        for i, q in enumerate(mcq_questions, 1):
            html_parts.append(_render_mcq_html(q, i, show_answers))

    if essay_questions:
        html_parts.append("<h2>Phần II: Tự luận</h2>")
        html_parts.append("<p>Hãy trình bày lời giải chi tiết.</p>")
        for i, q in enumerate(essay_questions, 1):
            html_parts.append(_render_essay_html(q, i, show_answers, include_rubric))

    html_parts.append("</body></html>")
    return "\n".join(html_parts)


def _pdf_header(title: str, scope: list) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{html.escape(title)}</title>
"""


def _pdf_css() -> str:
    return f"""
<style>
{VIETNAMESE_FONT_CSS}

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
    font-family: 'Noto Sans', 'DejaVu Sans', 'Arial Unicode MS', sans-serif;
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
    """Render a single MCQ question as HTML (legacy path)."""
    stem = html.escape(q.get("stem", ""))
    options = q.get("options", {})
    correct = q.get("correct_answer", "")
    explanation = q.get("explanation", "")

    # Normalize options
    if isinstance(options, dict):
        opts = [(k, str(v)) for k, v in options.items()]
    else:
        opts = []
        for opt in (options or []):
            if isinstance(opt, dict):
                opts.append((opt.get("label", ""), str(opt.get("text", ""))))
            else:
                opts.append(("", str(opt)))

    parts = [
        f"<div class='question'>",
        f"<div class='question-stem'>Câu {index}. {stem}</div>",
        "<div class='options'>",
    ]

    for label, text in opts:
        opt_text = html.escape(text)
        if show_answer and label == correct:
            parts.append(f"<div class='option answer'>□ {label}. {opt_text} ✓</div>")
        else:
            parts.append(f"<div class='option'>□ {label}. {opt_text}</div>")

    parts.append("</div>")

    if show_answer and explanation:
        parts.append(f"<div class='answer'>Giải thích: {html.escape(explanation)}</div>")

    parts.append("</div>")
    return "\n".join(parts)


def _render_essay_html(q: dict, index: int, show_answer: bool, include_rubric: bool) -> str:
    """Render a single essay question as HTML (legacy path)."""
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

    parts.append("</div>")
    return "\n".join(parts)
