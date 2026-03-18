from __future__ import annotations

from math import floor

from agents.state import ExamSpec
from core.mvp import DEFAULT_OUTPUT_LANGUAGE, DEFAULT_QUESTION_TYPE
from services.curriculum.scope_service import ResolvedScope


class ExamSpecService:
    def build_exam_spec(
        self,
        request,
        course_id: str | None,
        document_id: str,
        resolved_scope: ResolvedScope,
    ) -> ExamSpec:
        total_questions = self.resolve_total_questions(request)
        instructions = (request.instructions or "").strip()
        prompt = (request.prompt or "").strip()

        normalized_instructions_parts = [
            "Mon hoc: Vat ly.",
            "Ngon ngu dau ra: tieng Viet.",
            "Loai cau hoi: trac nghiem 4 lua chon, 1 dap an dung.",
            f"Tong so cau hoi: {total_questions}.",
            "Chi su dung noi dung nam trong scope da chon.",
            "Moi cau hoi phai co bang chung nguon truy vet duoc.",
        ]
        if prompt:
            normalized_instructions_parts.append(f"Yeu cau bo sung tu nguoi dung: {prompt}")
        if instructions:
            normalized_instructions_parts.append(f"Huong dan hien thi tren de: {instructions}")

        return ExamSpec(
            course_id=course_id,
            document_id=document_id,
            exam_type="mcq",
            question_type=DEFAULT_QUESTION_TYPE,
            total_questions=total_questions,
            time_limit_minutes=request.time_limit_minutes,
            output_language=DEFAULT_OUTPUT_LANGUAGE,
            instructions=instructions,
            normalized_instructions=" ".join(normalized_instructions_parts),
            strict_scope_flag=True,
            selected_scope=list(resolved_scope.selected_scope),
            selected_section_ids=list(resolved_scope.selected_section_ids),
            bloom_distribution=self._build_default_bloom_distribution(total_questions),
            question_mix={"mcq": total_questions},
            formatting_preferences=dict(request.formatting_preferences or {}),
            source_prompt=prompt,
        )

    def resolve_total_questions(self, request) -> int:
        if getattr(request, "total_questions", None):
            total_questions = int(request.total_questions)
            if total_questions > 0:
                return total_questions

        distribution = getattr(request, "question_distribution", None)
        if distribution and getattr(distribution, "mcq", None):
            total_questions = (
                int(distribution.mcq.easy)
                + int(distribution.mcq.medium)
                + int(distribution.mcq.hard)
            )
            if total_questions > 0:
                return total_questions

        raise ValueError("total_questions phai lon hon 0")

    def build_question_distribution(self, total_questions: int) -> dict[str, dict[str, int]]:
        easy = max(0, floor(total_questions * 0.3))
        medium = max(0, floor(total_questions * 0.4))
        hard = max(0, total_questions - easy - medium)

        if total_questions == 1:
            easy, medium, hard = 0, 1, 0
        elif total_questions == 2:
            easy, medium, hard = 1, 1, 0

        return {
            "mcq": {
                "easy": easy,
                "medium": medium,
                "hard": hard,
            }
        }

    def _build_default_bloom_distribution(self, total_questions: int) -> dict[str, int]:
        if total_questions <= 0:
            return {}

        buckets = ["remember", "understand", "apply", "analyze"]
        base = total_questions // len(buckets)
        remainder = total_questions % len(buckets)
        distribution: dict[str, int] = {}
        for index, bucket in enumerate(buckets):
            distribution[bucket] = base + (1 if index < remainder else 0)
        return distribution
