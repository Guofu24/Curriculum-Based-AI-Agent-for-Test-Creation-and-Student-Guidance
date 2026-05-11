"""Export exam to PDF (WeasyPrint) and DOCX (python-docx) formats.

G12: include_answers param — False = bản học sinh, True = bản giáo viên
     include_blueprint param (PDF) — thêm bảng phân bổ Bloom ở đầu file
"""

from io import BytesIO
from typing import Any
from uuid import UUID
import html
import json
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
body {
    font-family: 'Noto Sans', 'DejaVu Sans', 'Liberation Sans', Arial, sans-serif;
    font-size: 12pt;
    line-height: 1.7;
}
"""


def _normalize_rubric_rows(rubric: Any) -> list[dict[str, str]]:
    """Return rubric rows from list/dict/JSON string/free text without raising."""
    if not rubric:
        return []

    if isinstance(rubric, str):
        try:
            return _normalize_rubric_rows(json.loads(rubric))
        except (json.JSONDecodeError, TypeError, ValueError):
            return [{"score": "", "description": rubric}]

    if isinstance(rubric, list):
        rows: list[dict[str, str]] = []
        for item in rubric:
            if isinstance(item, dict):
                desc = item.get("description", "")
                if desc:
                    rows.append({
                        "score": str(item.get("score", "")),
                        "description": str(desc),
                    })
            elif item:
                rows.append({"score": "", "description": str(item)})
        return rows

    if isinstance(rubric, dict):
        if "description" in rubric or "score" in rubric:
            desc = rubric.get("description", "")
            return [{"score": str(rubric.get("score", "")), "description": str(desc)}] if desc else []
        return [
            {"score": str(score), "description": str(description)}
            for score, description in rubric.items()
            if description
        ]

    return [{"score": "", "description": str(rubric)}]


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
            if not questions and exam.history:
                # Fallback: recover from latest history snapshot if DB column is empty
                latest = sorted(exam.history, key=lambda h: h.created_at, reverse=True)[0]
                snapshot_q = (latest.snapshot or {}).get("questions", [])
                if isinstance(snapshot_q, list) and snapshot_q:
                    questions = snapshot_q
                    import logging as _log
                    _log.getLogger("app.utils.export").warning(
                        "exam.questions empty for %s — recovered %d from history snapshot",
                        exam_id, len(questions),
                    )
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
        if not questions and exam.history:
            latest = sorted(exam.history, key=lambda h: h.created_at, reverse=True)[0]
            snapshot_q = (latest.snapshot or {}).get("questions", [])
            if isinstance(snapshot_q, list) and snapshot_q:
                questions = snapshot_q
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
        # Categorize all questions — never drop a question due to unknown type
        mcq_questions = [q for q in questions if self._get_qtype(q) in ("mcq", "dung_sai", "short_answer")]
        essay_questions = [q for q in questions if self._get_qtype(q) == "essay"]
        # Any uncategorized questions fall into mcq_questions
        categorized_ids = {id(q) for q in mcq_questions + essay_questions}
        mcq_questions = mcq_questions + [q for q in questions if id(q) not in categorized_ids]

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
                if self._get_qtype(q) == "dung_sai":
                    html_parts.append(self._render_dung_sai_html(q, i, include_answers))
                else:
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

    /* Dung-Sai table */
    .dung-sai-table {{
        width: 100%;
        border-collapse: collapse;
        margin: 0.6em 0;
    }}
    .dung-sai-table th, .dung-sai-table td {{
        border: 1px solid #bbb;
        padding: 0.35em 0.6em;
        vertical-align: middle;
    }}
    .dung-sai-table thead th {{
        background-color: #f0f4f8;
        font-weight: bold;
        text-align: center;
    }}
    .dung-sai-table .tick-col {{
        width: 56px;
        text-align: center;
        font-size: 13pt;
    }}
    .tick-correct {{ color: #1a7f1a; font-weight: bold; }}
    .tick-wrong   {{ color: #a31d1d; font-weight: bold; }}

    /* Math rendering */
    .math-inline {{
        font-family: 'DejaVu Sans', 'Noto Sans', serif;
        font-style: italic;
        color: #1a1a1a;
        white-space: nowrap;
    }}
    .math-block {{
        display: block;
        text-align: center;
        font-family: 'DejaVu Sans', 'Noto Sans', serif;
        font-style: italic;
        margin: 0.5em 0;
        color: #1a1a1a;
    }}
    /* Fraction rendering */
    .math-frac {{
        display: inline-block;
        text-align: center;
        vertical-align: middle;
        font-size: 0.92em;
        line-height: 1.1;
    }}
    .math-frac-num {{
        display: block;
        border-bottom: 1px solid currentColor;
        padding: 0 3px 1px;
    }}
    .math-frac-den {{
        display: block;
        padding: 1px 3px 0;
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
        raw_stem = q.get("stem") or q.get("content") or ""
        stem = self._render_latex(html.escape(raw_stem))
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

    def _render_dung_sai_html(self, q: dict, index: int, include_answers: bool) -> str:
        """Render THPT true/false question as a Đúng/Sai tick table."""
        raw_stem = q.get("stem") or q.get("content") or ""
        stem = self._render_latex(html.escape(raw_stem))
        propositions = self._normalize_propositions(q.get("propositions", []))
        explanation = html.escape(q.get("explanation", ""))

        parts = [
            "<div class='question'>",
            f"<div class='question-stem'>Câu {index}. {stem}</div>",
            "<table class='dung-sai-table'>",
            "<thead><tr>"
            "<th>Mệnh đề</th>"
            "<th class='tick-col'>Đúng</th>"
            "<th class='tick-col'>Sai</th>"
            "</tr></thead>",
            "<tbody>",
        ]

        for label, text, is_correct in propositions:
            escaped_text = self._render_latex(html.escape(str(text)))
            if include_answers:
                dung = "<span class='tick-correct'>✓</span>" if is_correct else "□"
                sai  = "□" if is_correct else "<span class='tick-wrong'>✗</span>"
            else:
                dung = "□"
                sai  = "□"
            parts.append(
                f"<tr>"
                f"<td><strong>{label})</strong> {escaped_text}</td>"
                f"<td class='tick-col'>{dung}</td>"
                f"<td class='tick-col'>{sai}</td>"
                f"</tr>"
            )

        parts.append("</tbody></table>")

        if include_answers and explanation:
            parts.append(f"<div class='answer-block'>Giải thích: <span class='explanation'>{explanation}</span></div>")

        parts.append("</div>")
        return "\n".join(parts)

    def _render_essay_html(self, q: dict, index: int, include_answers: bool) -> str:
        """Render essay question with rubric."""
        raw_stem = q.get("stem") or q.get("content") or ""
        stem = self._render_latex(html.escape(raw_stem))
        raw_solution = q.get("solution") or q.get("sample_answer") or q.get("model_answer") or ""
        solution = self._render_latex(html.escape(raw_solution)) if raw_solution else ""
        rubric = _normalize_rubric_rows(q.get("rubric"))
        time_est = q.get("estimated_solve_time_minutes")

        parts = [
            f"<div class='question'>",
            f"<div class='question-stem'>Câu {index}. {stem}</div>",
        ]

        if time_est:
            parts.append(f"<p>Thời gian ước tính: {time_est} phút</p>")

        if include_answers and solution:
            parts.append("<div class='answer-block'>")
            parts.append(f"<strong>Lời giải mẫu:</strong> <span class='explanation'>{solution}</span>")
            parts.append("</div>")

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
        dung_sai_questions = [q for q in questions if self._get_qtype(q) == "dung_sai"]
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

        if dung_sai_questions:
            rows.append("<h3>Đáp án Đúng-Sai</h3>")
            rows.append("<table class='answer-key-table'>")
            rows.append("<tr><th>Câu</th><th>a</th><th>b</th><th>c</th><th>d</th><th>Bloom</th></tr>")
            for i, q in enumerate(dung_sai_questions, 1):
                answer_map = {
                    label.lower(): ("Đ" if is_correct else "S")
                    for label, _, is_correct in self._normalize_propositions(q.get("propositions", []))
                }
                bloom = q.get("bloom_level", "-")
                rows.append(
                    f"<tr><td>{i}</td><td>{answer_map.get('a', '-')}</td><td>{answer_map.get('b', '-')}</td>"
                    f"<td>{answer_map.get('c', '-')}</td><td>{answer_map.get('d', '-')}</td><td>{html.escape(bloom)}</td></tr>"
                )
            rows.append("</table>")

        if essay_questions:
            rows.append("<h3>Đáp án tự luận</h3>")
            rows.append("<table class='answer-key-table'>")
            rows.append("<tr><th>Câu</th><th>Bloom</th><th>Độ khó</th><th>Thang điểm</th></tr>")
            for i, q in enumerate(essay_questions, 1):
                bloom = q.get("bloom_level", "-")
                diff = q.get("difficulty_level", "-")
                rubric = _normalize_rubric_rows(q.get("rubric"))
                rubric_str = "; ".join(f"{r.get('score', '')}đ: {r.get('description', '')[:40]}" for r in rubric)
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

        # Categorize all questions — never drop a question due to unknown type
        mcq_questions = [q for q in questions if self._get_qtype(q) in ("mcq", "dung_sai", "short_answer")]
        essay_questions = [q for q in questions if self._get_qtype(q) == "essay"]
        # Any uncategorized questions fall into mcq_questions
        categorized_ids = {id(q) for q in mcq_questions + essay_questions}
        mcq_questions = mcq_questions + [q for q in questions if id(q) not in categorized_ids]

        if mcq_questions:
            doc.add_heading("Phần I: Trắc nghiệm", level=2)
            p = doc.add_paragraph("Hãy chọn đáp án đúng nhất.")
            p.runs[0].italic = True

            for i, q in enumerate(mcq_questions, 1):
                if self._get_qtype(q) == "dung_sai":
                    self._docx_add_dung_sai(doc, q, i, include_answers)
                else:
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
        from docx.oxml.ns import qn as _qn
        style = doc.styles["Normal"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(12)
        try:
            rPr = style.element.get_or_add_rPr()
            rFonts = rPr.get_or_add_rFonts()
            rFonts.set(_qn("w:ascii"), "Times New Roman")
            rFonts.set(_qn("w:hAnsi"), "Times New Roman")
            rFonts.set(_qn("w:cs"),    "Times New Roman")
        except Exception:
            pass

    def _docx_add_mcq(
        self, doc: Document, q: dict, index: int, include_answers: bool
    ) -> None:
        """Add a single MCQ question to the DOCX document."""
        stem = self._strip_latex(q.get("stem") or q.get("content") or "")
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

    def _docx_add_dung_sai(
        self, doc: Document, q: dict, index: int, include_answers: bool
    ) -> None:
        """Add a single THPT true/false question as a Đúng/Sai tick table."""
        from docx.oxml.ns import qn as _qn  # noqa: F401
        stem = self._strip_latex(q.get("stem") or q.get("content") or "")
        propositions = self._normalize_propositions(q.get("propositions", []))
        explanation = q.get("explanation", "")

        p = doc.add_paragraph()
        run = p.add_run(f"Câu {index}. {stem}")
        run.bold = True
        run.font.size = Pt(12)

        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        for cell, txt in zip(hdr, ["Mệnh đề", "Đúng", "Sai"]):
            cell.text = txt
            run_h = cell.paragraphs[0].runs[0]
            run_h.bold = True
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        for label, text, is_correct in propositions:
            row = table.add_row().cells
            row[0].text = f"{label}) {self._strip_latex(str(text))}"
            if include_answers:
                row[1].text = "✓" if is_correct else "□"
                row[2].text = "□" if is_correct else "✗"
                tick_cell = row[1] if is_correct else row[2]
                tick_run = tick_cell.paragraphs[0].runs[0]
                tick_run.bold = True
                tick_run.font.color.rgb = RGBColor(0x1A, 0x7F, 0x1A) if is_correct else RGBColor(0xA3, 0x1D, 0x1D)
            else:
                row[1].text = "□"
                row[2].text = "□"
            for cell in [row[1], row[2]]:
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

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
        stem = self._strip_latex(q.get("stem") or q.get("content") or "")
        solution = self._strip_latex(q.get("solution") or q.get("sample_answer") or q.get("model_answer") or "")
        rubric = _normalize_rubric_rows(q.get("rubric"))
        time_est = q.get("estimated_solve_time_minutes")

        p = doc.add_paragraph()
        run = p.add_run(f"Câu {index}. {stem}")
        run.bold = True
        run.font.size = Pt(12)

        if time_est:
            p = doc.add_paragraph(f"Thời gian ước tính: {time_est} phút")
            p.runs[0].font.size = Pt(11)
            p.runs[0].italic = True

        if include_answers and solution:
            p = doc.add_paragraph()
            run = p.add_run(f"Lời giải mẫu: {solution}")
            run.font.size = Pt(11)
            run.italic = True

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
        dung_sai_questions = [q for q in questions if self._get_qtype(q) == "dung_sai"]
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

        if dung_sai_questions:
            doc.add_heading("Đúng-Sai", level=3)
            table = doc.add_table(rows=1, cols=6)
            table.style = "Table Grid"
            hdr = table.rows[0].cells
            for cell, text in zip(hdr, ["Câu", "a", "b", "c", "d", "Bloom"]):
                cell.text = text
                cell.paragraphs[0].runs[0].bold = True

            for i, q in enumerate(dung_sai_questions, 1):
                answer_map = {
                    label.lower(): ("Đ" if is_correct else "S")
                    for label, _, is_correct in self._normalize_propositions(q.get("propositions", []))
                }
                row = table.add_row().cells
                row[0].text = str(i)
                row[1].text = answer_map.get("a", "-")
                row[2].text = answer_map.get("b", "-")
                row[3].text = answer_map.get("c", "-")
                row[4].text = answer_map.get("d", "-")
                row[5].text = str(q.get("bloom_level", "-"))

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
                rubric = _normalize_rubric_rows(q.get("rubric"))
                rubric_str = "; ".join(f"{r.get('score', '')}đ" for r in rubric)
                row[3].text = rubric_str or "-"

    def _get_qtype(self, q: dict) -> str:
        """
        Normalize question type from any field variant.
        Returns 'mcq', 'essay', 'dung_sai', 'short_answer', or 'mcq' as default.
        """
        t = q.get("type") or q.get("question_type") or ""
        t = str(t).lower().strip()
        if t in ("essay", "tu_luan"):
            return "essay"
        if t in ("dung_sai",):
            return "dung_sai"
        if t in ("short_answer",):
            return "short_answer"
        # 'mcq' or any unrecognized type → treat as mcq
        return "mcq"

    def _normalize_propositions(self, propositions) -> list[tuple[str, str, bool]]:
        """Normalize THPT true/false propositions to (label, text, is_correct)."""
        result: list[tuple[str, str, bool]] = []
        if isinstance(propositions, list):
            for idx, prop in enumerate(propositions):
                default_label = chr(ord("a") + idx)
                if isinstance(prop, dict):
                    label = str(prop.get("label") or default_label)
                    text = str(prop.get("text") or prop.get("statement") or "")
                    is_correct = bool(prop.get("is_correct", False))
                else:
                    label = default_label
                    text = str(prop)
                    is_correct = False
                result.append((label, text, is_correct))
        elif isinstance(propositions, dict):
            for label, value in propositions.items():
                if isinstance(value, dict):
                    text = str(value.get("text") or value.get("statement") or "")
                    is_correct = bool(value.get("is_correct", False))
                else:
                    text = str(value)
                    is_correct = False
                result.append((str(label), text, is_correct))
        return result

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
        """LaTeX-to-HTML renderer for PDF export."""
        text = re.sub(
            r"\$\$(.+?)\$\$",
            lambda m: f"<div class='math-block'>{self._latex_symbols(m.group(1), html_output=True)}</div>",
            text, flags=re.DOTALL
        )
        text = re.sub(
            r"\\\[(.+?)\\\]",
            lambda m: f"<div class='math-block'>{self._latex_symbols(m.group(1), html_output=True)}</div>",
            text, flags=re.DOTALL
        )
        text = re.sub(
            r"\\\((.+?)\\\)",
            lambda m: f"<span class='math-inline'>{self._latex_symbols(m.group(1), html_output=True)}</span>",
            text, flags=re.DOTALL
        )
        text = re.sub(
            r"(?<!\$)\$([^$\n]+?)\$(?!\$)",
            lambda m: f"<span class='math-inline'>{self._latex_symbols(m.group(1), html_output=True)}</span>",
            text
        )
        return text

    def _latex_symbols(self, text: str, html_output: bool = False) -> str:
        """
        Convert LaTeX symbols to HTML/Unicode.
        html_output=True → render fractions as styled HTML (for WeasyPrint PDF).
        html_output=False → plain Unicode text (for DOCX).
        """
        # \left\right bracket pairs
        text = re.sub(r"\\left\s*\|(.+?)\\right\s*\|", r"|\1|", text, flags=re.DOTALL)
        text = re.sub(r"\\left\s*\((.+?)\\right\s*\)", r"(\1)", text, flags=re.DOTALL)
        text = re.sub(r"\\left\s*\[(.+?)\\right\s*\]", r"[\1]", text, flags=re.DOTALL)
        text = re.sub(r"\\left\s*\{(.+?)\\right\s*\}", r"{\1}", text, flags=re.DOTALL)
        text = re.sub(r"\\(?:left|right)\s*[.|\[\](){}]?", "", text)

        # Fractions: \frac{a}{b} and \dfrac{a}{b}
        if html_output:
            text = re.sub(
                r"\\d?frac\{([^}]+)\}\{([^}]+)\}",
                lambda m: (
                    f"<span class='math-frac'>"
                    f"<span class='math-frac-num'>{m.group(1)}</span>"
                    f"<span class='math-frac-den'>{m.group(2)}</span>"
                    f"</span>"
                ),
                text,
            )
        else:
            text = re.sub(r"\\d?frac\{([^}]+)\}\{([^}]+)\}", r"\1/\2", text)

        # Binomial coefficient: \binom{n}{k}
        text = re.sub(r"\\binom\{([^}]+)\}\{([^}]+)\}", r"C(\1,\2)", text)

        # Vector decorators (Unicode combining chars — best for single-char variables)
        text = re.sub(r"\\vec\{([^}]*)\}", lambda m: m.group(1) + "⃗", text)       # ⃗
        text = re.sub(r"\\hat\{([^}]*)\}", lambda m: m.group(1) + "̂", text)       # ̂
        text = re.sub(r"\\overline\{([^}]*)\}", lambda m: m.group(1) + "̅", text)  # ̄
        text = re.sub(r"\\bar\{([^}]*)\}", lambda m: m.group(1) + "̅", text)       # ̄
        text = re.sub(r"\\tilde\{([^}]*)\}", lambda m: m.group(1) + "̃", text)     # ̃
        text = re.sub(r"\\dot\{([^}]*)\}", lambda m: m.group(1) + "̇", text)       # ̇
        text = re.sub(r"\\ddot\{([^}]*)\}", lambda m: m.group(1) + "̈", text)      # ̈
        text = re.sub(r"\\widehat\{([^}]*)\}", lambda m: m.group(1) + "̂", text)   # ̂

        # Superscript and subscript
        text = re.sub(r"\^\{([^}]+)\}", r"<sup>\1</sup>", text)
        text = re.sub(r"\^([A-Za-z0-9+\-])", r"<sup>\1</sup>", text)
        text = re.sub(r"_\{([^}]+)\}", r"<sub>\1</sub>", text)
        text = re.sub(r"_([A-Za-z0-9+\-])", r"<sub>\1</sub>", text)

        # Sqrt: \sqrt[n]{x} and \sqrt{x}
        text = re.sub(r"\\sqrt\[([^\]]+)\]\{([^}]+)\}", r"ⁿ√(\2)", text)
        text = re.sub(r"\\sqrt\{([^}]+)\}", r"√(\1)", text)
        text = re.sub(r"\\sqrt\b", r"√", text)

        # Greek letters
        greek = {
            r"\\varepsilon": "ε", r"\\varphi": "φ", r"\\vartheta": "θ",
            r"\\alpha": "α", r"\\beta": "β", r"\\gamma": "γ", r"\\delta": "δ",
            r"\\epsilon": "ε", r"\\zeta": "ζ", r"\\eta": "η", r"\\theta": "θ",
            r"\\lambda": "λ", r"\\mu": "μ", r"\\nu": "ν", r"\\xi": "ξ",
            r"\\pi": "π", r"\\rho": "ρ", r"\\sigma": "σ", r"\\tau": "τ",
            r"\\phi": "φ", r"\\chi": "χ", r"\\psi": "ψ", r"\\omega": "ω",
            r"\\Gamma": "Γ", r"\\Delta": "Δ", r"\\Theta": "Θ", r"\\Lambda": "Λ",
            r"\\Xi": "Ξ", r"\\Pi": "Π", r"\\Sigma": "Σ", r"\\Phi": "Φ",
            r"\\Psi": "Ψ", r"\\Omega": "Ω",
        }
        for pat, sym in greek.items():
            text = re.sub(pat, sym, text)

        # Math operators
        ops = {
            r"\\times": "×", r"\\div": "÷", r"\\pm": "±", r"\\mp": "∓",
            r"\\leq": "≤", r"\\geq": "≥", r"\\neq": "≠", r"\\approx": "≈",
            r"\\infty": "∞", r"\\sum": "Σ", r"\\int": "∫", r"\\cdot": "·",
            r"\\cdots": "⋯", r"\\ldots": "…", r"\\rightarrow": "→",
            r"\\leftarrow": "←", r"\\Rightarrow": "⇒", r"\\Leftarrow": "⇐",
            r"\\leftrightarrow": "↔", r"\\Leftrightarrow": "⇔",
            r"\\in": "∈", r"\\notin": "∉", r"\\subset": "⊂", r"\\cup": "∪",
            r"\\cap": "∩", r"\\forall": "∀", r"\\exists": "∃",
            r"\\equiv": "≡", r"\\propto": "∝", r"\\perp": "⊥",
            r"\\parallel": "∥", r"\\angle": "∠", r"\\triangle": "△",
            r"\\nabla": "∇", r"\\partial": "∂", r"\\hbar": "ℏ",
            r"\\circ": "°", r"\\degree": "°",
        }
        for pat, sym in ops.items():
            text = re.sub(pat, sym, text)

        # Remove text/font commands but keep their content
        text = re.sub(
            r"\\(?:text|mathrm|mathbf|mathit|mathbb|operatorname|boldsymbol|mathcal|mathscr)\{([^}]+)\}",
            r"\1", text,
        )
        # Remove sizing/spacing commands
        text = re.sub(r"\\(?:,|;|:|!|quad|qquad|enspace|thinspace)\b", " ", text)
        text = re.sub(r"\\(?:big|Big|bigg|Bigg)[lgr]?\s*", "", text)
        # Generic: \cmd{content} → content (for unknown commands with args)
        text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
        # Remove remaining bare \commands
        text = re.sub(r"\\[a-zA-Z]+\b", "", text)
        # Remove remaining braces
        text = re.sub(r"[{}]", "", text)
        return text

    def _strip_latex(self, text: str) -> str:
        """
        Strip LaTeX math delimiters and commands for DOCX plain-text output.
        Converts math to readable Unicode where possible.
        """
        # Display math blocks: $$...$$ and \[...\]
        text = re.sub(r"\$\$(.+?)\$\$", lambda m: self._latex_to_plain(m.group(1)), text, flags=re.DOTALL)
        text = re.sub(r"\\\[(.+?)\\\]", lambda m: self._latex_to_plain(m.group(1)), text, flags=re.DOTALL)
        # Inline math: \(...\)
        text = re.sub(r"\\\((.+?)\\\)", lambda m: self._latex_to_plain(m.group(1)), text, flags=re.DOTALL)
        # Inline math: $...$
        text = re.sub(r"(?<!\$)\$([^$\n]+?)\$(?!\$)", lambda m: self._latex_to_plain(m.group(1)), text)
        return text

    def _latex_to_plain(self, text: str) -> str:
        """
        Convert LaTeX math expression to plain Unicode text for DOCX.
        Applies the same symbol conversions as _latex_symbols but returns plain text.
        """
        result = self._latex_symbols(text)
        # Remove HTML tags that _latex_symbols might have added
        result = re.sub(r"<[^>]+>", "", result)
        return result


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
    solution = html.escape(q.get("solution") or q.get("sample_answer") or q.get("model_answer") or "")
    rubric = _normalize_rubric_rows(q.get("rubric"))
    time_est = q.get("estimated_solve_time_minutes")

    parts = [
        f"<div class='question'>",
        f"<div class='question-stem'>Câu {index}. {stem}</div>",
    ]

    if time_est:
        parts.append(f"<p>Thời gian ước tính: {time_est} phút</p>")

    if show_answer and solution:
        parts.append("<div class='answer-block'>")
        parts.append(f"<strong>Lời giải mẫu:</strong> {solution}")
        parts.append("</div>")

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
