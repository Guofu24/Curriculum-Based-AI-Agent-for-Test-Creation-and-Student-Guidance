from __future__ import annotations

import json
import re

from agents.state import ExamBlueprint, GeneratedQuestion
from agents.validator import ValidatorAgent
from services.curriculum.scope_service import ResolvedScope


class MCQVerifierService:
    def __init__(self, validator: ValidatorAgent):
        self.validator = validator

    async def verify(
        self,
        questions: list[GeneratedQuestion],
        blueprint: ExamBlueprint,
        resolved_scope: ResolvedScope,
    ) -> tuple[list[GeneratedQuestion], dict, list[dict], list[dict], list[dict]]:
        validated_questions, summary = await self.validator.validate_questions(
            questions,
            strict_grounding=True,
        )

        duplicates = self._find_duplicates(validated_questions)
        duplicate_slots = {
            slot
            for group in duplicates
            for slot in group["member_slots"][1:]
        }
        cell_by_key = {cell.cell_id: cell for cell in blueprint.cells}
        quality_scores: list[dict] = []
        grounding_reports: list[dict] = []

        for question in validated_questions:
            issues = list(question.warnings or [])
            scope_ok = self._check_scope(question, cell_by_key, resolved_scope)
            mcq_ok = self._check_mcq_validity(question)
            answerability_ok = self._check_answerability(question)
            duplicate_ok = question.slot_number not in duplicate_slots

            if not scope_ok:
                issues.append("Question evidence is outside the selected section scope")
            if not mcq_ok:
                issues.append("Question is not a valid single-answer MCQ")
            if not answerability_ok:
                issues.append("Question is not sufficiently answerable from its evidence")
            if not duplicate_ok:
                issues.append("Question duplicates another item in this version")

            validation_payload = self._parse_validation_payload(question.validation_notes)
            validation_payload["scope_check"] = scope_ok
            validation_payload["mcq_validity_check"] = mcq_ok
            validation_payload["answerability_check"] = answerability_ok
            validation_payload["duplication_check"] = duplicate_ok
            validation_payload["validation_errors"] = issues
            validation_payload["warnings"] = issues

            question.warnings = issues
            question.is_validated = all((scope_ok, mcq_ok, answerability_ok, duplicate_ok)) and bool(question.is_validated)
            question.verification_status = "passed" if question.is_validated else "failed"
            validation_payload["verification_status"] = question.verification_status
            validation_payload["overall_quality"] = self._quality_score(question)
            question.validation_notes = json.dumps(validation_payload, ensure_ascii=False)

            quality_scores.append(
                {
                    "slot_number": question.slot_number,
                    "overall": validation_payload["overall_quality"],
                    "passed": question.is_validated,
                    "scope_check": scope_ok,
                    "mcq_validity": mcq_ok,
                    "answerability": answerability_ok,
                    "duplication": duplicate_ok,
                    "notes": issues,
                }
            )

            grounding_report = validation_payload.get("grounding_report")
            if isinstance(grounding_report, dict):
                grounding_reports.append(grounding_report)

        passed = sum(1 for item in validated_questions if item.is_validated)
        summary.update(
            {
                "passed": passed,
                "failed": len(validated_questions) - passed,
                "pass_rate": passed / len(validated_questions) if validated_questions else 0.0,
            }
        )
        return validated_questions, summary, quality_scores, grounding_reports, duplicates

    def _check_scope(
        self,
        question: GeneratedQuestion,
        cell_by_key: dict,
        resolved_scope: ResolvedScope,
    ) -> bool:
        cell = cell_by_key.get(question.blueprint_cell_key)
        if cell is None:
            return False
        expected_section_id = cell.scope_unit.section_id
        if not expected_section_id:
            return False

        evidence_items = list(question.source_evidence or [])
        if not evidence_items:
            return False

        for item in evidence_items:
            if not isinstance(item, dict):
                return False
            if item.get("section_id") != expected_section_id:
                return False

        return expected_section_id in resolved_scope.selected_section_ids

    def _check_mcq_validity(self, question: GeneratedQuestion) -> bool:
        if question.question_type != "mcq":
            return False
        if not question.options or len(question.options) != 4:
            return False
        labels = [str(option.get("label", "")).strip() for option in question.options]
        texts = [str(option.get("text", "")).strip() for option in question.options]
        if labels != ["A", "B", "C", "D"]:
            return False
        if any(not text for text in texts):
            return False
        return str(question.correct_answer).strip() in {"A", "B", "C", "D"}

    def _check_answerability(self, question: GeneratedQuestion) -> bool:
        explanation = (question.explanation or "").strip()
        if len(explanation) < 10:
            return False
        notes = self._parse_validation_payload(question.validation_notes)
        grounding_report = notes.get("grounding_report") or {}
        if isinstance(grounding_report, dict):
            return bool(grounding_report.get("answer_supported", True))
        return True

    def _find_duplicates(self, questions: list[GeneratedQuestion]) -> list[dict]:
        normalized_questions = [
            (question.slot_number, self._normalize_text(question.content))
            for question in questions
        ]
        groups: list[dict] = []
        visited: set[int] = set()

        for index, (slot_number, content) in enumerate(normalized_questions):
            if slot_number in visited or not content:
                continue
            group = [slot_number]
            for other_slot, other_content in normalized_questions[index + 1 :]:
                if other_slot in visited:
                    continue
                if self._jaccard(content, other_content) >= 0.82:
                    group.append(other_slot)
                    visited.add(other_slot)
            if len(group) > 1:
                groups.append(
                    {
                        "representative_slot": slot_number,
                        "member_slots": group,
                        "max_similarity": 1.0,
                    }
                )

        return groups

    def _quality_score(self, question: GeneratedQuestion) -> float:
        score = 1.0
        score -= 0.18 * len(question.warnings or [])
        if question.source_evidence:
            score += 0.05
        if question.explanation:
            score += 0.05
        return round(max(0.0, min(1.0, score)), 3)

    def _parse_validation_payload(self, payload: str | None) -> dict:
        if not payload:
            return {}
        try:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip().lower())

    def _jaccard(self, left: str, right: str) -> float:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
