"""
Export Service — DOCX / PDF / JSON export for published or generated exams.

Supports:
  - DOCX exam paper (with/without answers, rubric, explanations)
  - DOCX answer key as separate document
  - JSON internal format for reuse
  - PDF via reportlab (optional fallback)

Spec reference: §6.15
"""
import io
import json
import logging
from typing import Optional

from docx import Document as DocxDocument
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE

logger = logging.getLogger(__name__)


class ExportService:
    """Renders exam data into downloadable file formats."""

    def __init__(self, exam, questions: list, version=None):
        self.exam = exam
        self.questions = sorted(questions, key=lambda q: q.question_number)
        self.version = version

    # ──────────────────────────────────────────
    # DOCX Export
    # ──────────────────────────────────────────

    def export_docx(
        self,
        include_answers: bool = False,
        include_rubric: bool = False,
        include_explanation: bool = False,
    ) -> io.BytesIO:
        """Generate a DOCX file containing the exam."""
        doc = DocxDocument()
        self._setup_styles(doc)

        # ── Header ──
        self._add_exam_header(doc)

        # ── Instructions ──
        instructions = getattr(self.exam, "instructions", None)
        if instructions and instructions.strip():
            doc.add_paragraph("")
            p = doc.add_paragraph()
            run = p.add_run("Lưu ý: ")
            run.bold = True
            run.font.size = Pt(11)
            p.add_run(instructions).font.size = Pt(11)

        # ── Separate MCQ and Essay ──
        mcq_questions = [q for q in self.questions if self._get_value(q, "question_type") == "mcq"]
        essay_questions = [q for q in self.questions if self._get_value(q, "question_type") != "mcq"]

        # ── Part I: MCQ ──
        if mcq_questions:
            doc.add_paragraph("")
            part_heading = doc.add_heading("PHẦN I: TRẮC NGHIỆM", level=2)
            part_heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
            mcq_count = len(mcq_questions)
            doc.add_paragraph(
                f"({mcq_count} câu)",
                style="Normal",
            )

            for q in mcq_questions:
                self._render_mcq_question(doc, q, include_answers)

        # ── Part II: Essay ──
        if essay_questions:
            doc.add_paragraph("")
            part_heading = doc.add_heading("PHẦN II: TỰ LUẬN", level=2)
            part_heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
            essay_count = len(essay_questions)
            doc.add_paragraph(
                f"({essay_count} câu)",
                style="Normal",
            )

            for q in essay_questions:
                self._render_essay_question(doc, q, include_answers, include_rubric)

        # ── Explanations section ──
        if include_explanation:
            explanations = [q for q in self.questions if self._get_attr(q, "explanation")]
            if explanations:
                doc.add_page_break()
                doc.add_heading("GIẢI THÍCH ĐÁP ÁN", level=1)
                for q in explanations:
                    num = self._get_attr(q, "question_number")
                    explanation = self._get_attr(q, "explanation")
                    p = doc.add_paragraph()
                    run = p.add_run(f"Câu {num}: ")
                    run.bold = True
                    p.add_run(explanation)

        # ── Answer Key (if answers included, add a separate page) ──
        if include_answers and mcq_questions:
            doc.add_page_break()
            doc.add_heading("ĐÁP ÁN", level=1)
            self._render_answer_key(doc, mcq_questions)

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    def export_answer_key_docx(self) -> io.BytesIO:
        """Generate a separate DOCX file containing only the answer key."""
        doc = DocxDocument()
        self._setup_styles(doc)
        self._add_exam_header(doc, is_answer_key=True)

        mcq_questions = [q for q in self.questions if self._get_value(q, "question_type") == "mcq"]
        essay_questions = [q for q in self.questions if self._get_value(q, "question_type") != "mcq"]

        if mcq_questions:
            doc.add_heading("PHẦN I: TRẮC NGHIỆM — ĐÁP ÁN", level=2)
            self._render_answer_key(doc, mcq_questions)

        if essay_questions:
            doc.add_heading("PHẦN II: TỰ LUẬN — ĐÁP ÁN VÀ RUBRIC", level=2)
            for q in essay_questions:
                num = self._get_attr(q, "question_number")
                content = self._get_attr(q, "content")
                answer = self._get_attr(q, "correct_answer")
                rubric = self._get_attr(q, "rubric_json") or self._get_attr(q, "rubric")

                p = doc.add_paragraph()
                run = p.add_run(f"Câu {num}: ")
                run.bold = True
                p.add_run(content[:200] + ("..." if len(content) > 200 else ""))

                if answer:
                    p2 = doc.add_paragraph()
                    run2 = p2.add_run("Đáp án: ")
                    run2.bold = True
                    run2.font.color.rgb = RGBColor(0, 100, 0)
                    p2.add_run(answer)

                if rubric:
                    p3 = doc.add_paragraph()
                    run3 = p3.add_run("Rubric: ")
                    run3.bold = True
                    if isinstance(rubric, dict):
                        for key, value in rubric.items():
                            doc.add_paragraph(f"  • {key}: {value}", style="List Bullet")
                    else:
                        p3.add_run(str(rubric))

                doc.add_paragraph("")

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    # ──────────────────────────────────────────
    # JSON Export
    # ──────────────────────────────────────────

    def export_json(
        self,
        include_answers: bool = True,
        include_evidence: bool = False,
    ) -> io.BytesIO:
        """Export exam as JSON for internal reuse."""
        exam_data = {
            "exam_id": self.exam.id,
            "title": self.exam.title,
            "exam_type": self._get_value(self.exam, "exam_type"),
            "difficulty": self._get_value(self.exam, "difficulty"),
            "status": self._get_value(self.exam, "status"),
            "chapters": list(self.exam.chapters or []),
            "total_questions": self.exam.total_questions,
            "instructions": self.exam.instructions,
            "output_language": self.exam.output_language,
            "strict_scope_flag": bool(self.exam.strict_scope_flag),
            "created_at": self.exam.created_at.isoformat() if self.exam.created_at else None,
            "exam_spec": self.exam.exam_spec_json,
            "blueprint": self.exam.blueprint_json,
            "questions": [],
        }

        for q in self.questions:
            q_data = {
                "question_number": q.question_number,
                "question_type": self._get_value(q, "question_type"),
                "bloom_level": self._get_value(q, "bloom_level"),
                "difficulty_score": q.difficulty_score,
                "content": q.content,
                "options": q.options,
                "scope_tags": q.scope_tags_json or [],
                "verification_status": q.verification_status,
            }

            if include_answers:
                q_data["correct_answer"] = q.correct_answer
                q_data["rubric"] = q.rubric_json
                q_data["explanation"] = q.explanation

            if include_evidence:
                q_data["source_evidence"] = q.source_evidence_json
                q_data["source_chunks"] = q.source_chunks

            exam_data["questions"].append(q_data)

        buffer = io.BytesIO()
        buffer.write(json.dumps(exam_data, ensure_ascii=False, indent=2).encode("utf-8"))
        buffer.seek(0)
        return buffer

    # ──────────────────────────────────────────
    # Internal rendering helpers
    # ──────────────────────────────────────────

    def _setup_styles(self, doc: DocxDocument):
        """Configure document styles for Vietnamese academic format."""
        style = doc.styles["Normal"]
        font = style.font
        font.name = "Times New Roman"
        font.size = Pt(12)

        for level in range(1, 4):
            heading_style = doc.styles[f"Heading {level}"]
            heading_style.font.name = "Times New Roman"
            heading_style.font.color.rgb = RGBColor(0, 0, 0)

    def _add_exam_header(self, doc: DocxDocument, is_answer_key: bool = False):
        """Add standard exam header."""
        # School/department placeholder
        p_school = doc.add_paragraph()
        p_school.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_school = p_school.add_run("TRƯỜNG ĐẠI HỌC")
        run_school.font.size = Pt(12)
        run_school.bold = True

        # Title
        title_text = self.exam.title
        if is_answer_key:
            title_text += " — ĐÁP ÁN"

        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_title = p_title.add_run(title_text.upper())
        run_title.bold = True
        run_title.font.size = Pt(14)

        # Metadata line
        time_limit = getattr(self.exam, "time_limit_minutes", None)
        if not time_limit:
            config = getattr(self.exam, "config", {}) or {}
            time_limit = config.get("time_limit_minutes")

        meta_parts = []
        exam_type = self._get_value(self.exam, "exam_type")
        if exam_type:
            type_labels = {"mcq": "Trắc nghiệm", "essay": "Tự luận", "mixed": "Trắc nghiệm + Tự luận"}
            meta_parts.append(f"Hình thức: {type_labels.get(exam_type, exam_type)}")
        if time_limit:
            meta_parts.append(f"Thời gian: {time_limit} phút")
        meta_parts.append(f"Số câu: {len(self.questions)}")

        if meta_parts:
            p_meta = doc.add_paragraph()
            p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run_meta = p_meta.add_run(" | ".join(meta_parts))
            run_meta.font.size = Pt(11)
            run_meta.italic = True

        # Horizontal line
        doc.add_paragraph("─" * 60)

    def _render_mcq_question(self, doc: DocxDocument, q, include_answers: bool):
        """Render a single MCQ question."""
        num = self._get_attr(q, "question_number")
        content = self._get_attr(q, "content")
        correct_answer = self._get_attr(q, "correct_answer")
        options = self._get_attr(q, "options") or []

        # Question text
        p = doc.add_paragraph()
        run = p.add_run(f"Câu {num}. ")
        run.bold = True
        p.add_run(content)

        # Options
        for opt in options:
            if isinstance(opt, dict):
                label = opt.get("label", "")
                text = opt.get("text", "")
            else:
                continue

            p_opt = doc.add_paragraph()
            p_opt.paragraph_format.left_indent = Cm(1)

            is_correct = include_answers and label == correct_answer
            run_label = p_opt.add_run(f"  {label}. ")
            run_label.bold = is_correct
            run_text = p_opt.add_run(text)
            if is_correct:
                run_text.bold = True
                run_text.font.color.rgb = RGBColor(0, 100, 0)

    def _render_essay_question(
        self,
        doc: DocxDocument,
        q,
        include_answers: bool,
        include_rubric: bool,
    ):
        """Render a single essay question."""
        num = self._get_attr(q, "question_number")
        content = self._get_attr(q, "content")
        correct_answer = self._get_attr(q, "correct_answer")
        rubric = self._get_attr(q, "rubric_json") or self._get_attr(q, "rubric")

        p = doc.add_paragraph()
        run = p.add_run(f"Câu {num}. ")
        run.bold = True
        p.add_run(content)

        if include_answers and correct_answer:
            p_ans = doc.add_paragraph()
            run_ans = p_ans.add_run("Đáp án mẫu: ")
            run_ans.bold = True
            run_ans.font.color.rgb = RGBColor(0, 100, 0)
            p_ans.add_run(correct_answer)

        if include_rubric and rubric:
            p_rubric = doc.add_paragraph()
            run_rubric = p_rubric.add_run("Rubric: ")
            run_rubric.bold = True
            run_rubric.italic = True
            if isinstance(rubric, dict):
                for key, value in rubric.items():
                    doc.add_paragraph(f"  • {key}: {value}", style="List Bullet")
            else:
                p_rubric.add_run(str(rubric))

        doc.add_paragraph("")

    def _render_answer_key(self, doc: DocxDocument, mcq_questions: list):
        """Render MCQ answer key as a compact table."""
        cols = 5
        rows_needed = (len(mcq_questions) + cols - 1) // cols

        table = doc.add_table(rows=rows_needed + 1, cols=cols * 2)
        table.style = "Table Grid"

        # Header row
        for col_idx in range(cols):
            cell_num = table.cell(0, col_idx * 2)
            cell_ans = table.cell(0, col_idx * 2 + 1)
            cell_num.text = "Câu"
            cell_ans.text = "Đáp án"
            for cell in (cell_num, cell_ans):
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.size = Pt(10)

        # Data rows
        for idx, q in enumerate(mcq_questions):
            row = idx // cols + 1
            col = idx % cols
            num = self._get_attr(q, "question_number")
            answer = self._get_attr(q, "correct_answer")
            table.cell(row, col * 2).text = str(num)
            table.cell(row, col * 2 + 1).text = str(answer)

    @staticmethod
    def _get_value(obj, attr: str) -> str:
        """Get value handling both enum and plain string."""
        val = getattr(obj, attr, None)
        if val is None:
            return ""
        return val.value if hasattr(val, "value") else str(val)

    @staticmethod
    def _get_attr(obj, attr: str):
        """Get attribute safely."""
        return getattr(obj, attr, None)
