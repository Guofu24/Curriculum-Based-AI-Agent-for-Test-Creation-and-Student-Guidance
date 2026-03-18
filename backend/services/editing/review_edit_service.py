from __future__ import annotations

from copy import deepcopy

from agents.state import GeneratedQuestion


class ReviewEditService:
    def apply_edits(
        self,
        existing_questions: list[GeneratedQuestion],
        edit_requests: list[dict],
    ) -> tuple[dict[int, GeneratedQuestion], list[tuple[int, str]]]:
        question_map = {
            int(question.slot_number): deepcopy(question)
            for question in existing_questions
        }
        regenerate_targets: list[tuple[int, str]] = []

        for edit in edit_requests:
            targets = self._resolve_targets(question_map, edit)
            edit_type = str(edit.get("edit_type", "regenerate")).strip().lower()
            if edit_type == "regenerate":
                for slot_number in targets:
                    regenerate_targets.append((slot_number, str(edit.get("edit_prompt") or "").strip()))
                continue
            if edit_type == "delete":
                for slot_number in targets:
                    question_map.pop(slot_number, None)
                continue
            if edit_type == "lock":
                for slot_number in targets:
                    if slot_number in question_map:
                        question_map[slot_number].is_locked = True
                continue
            if edit_type == "unlock":
                for slot_number in targets:
                    if slot_number in question_map:
                        question_map[slot_number].is_locked = False
                continue
            if edit_type == "edit_text":
                for slot_number in targets:
                    if slot_number in question_map:
                        question_map[slot_number].content = str(edit.get("new_content") or "").strip()
                        self._mark_for_revalidation(question_map[slot_number])
                continue
            if edit_type == "edit_options":
                for slot_number in targets:
                    if slot_number in question_map:
                        question_map[slot_number].options = [
                            {"label": option["label"], "text": option["text"]}
                            for option in (edit.get("new_options") or [])
                        ]
                        self._mark_for_revalidation(question_map[slot_number])
                continue
            if edit_type == "edit_answer":
                for slot_number in targets:
                    if slot_number in question_map:
                        question_map[slot_number].correct_answer = str(edit.get("new_correct_answer") or "").strip()
                        self._mark_for_revalidation(question_map[slot_number])
                continue
            if edit_type == "edit_bloom":
                for slot_number in targets:
                    if slot_number in question_map:
                        question_map[slot_number].bloom_level = str(edit.get("new_bloom_level") or "").strip().lower()
                        self._mark_for_revalidation(question_map[slot_number])

        return question_map, regenerate_targets

    def renumber(self, question_map: dict[int, GeneratedQuestion]) -> list[GeneratedQuestion]:
        questions = [question_map[key] for key in sorted(question_map)]
        for index, question in enumerate(questions, start=1):
            question.slot_number = index
        return questions

    def _resolve_targets(
        self,
        question_map: dict[int, GeneratedQuestion],
        edit: dict,
    ) -> list[int]:
        targets: set[int] = set()
        for raw_id in edit.get("question_ids") or []:
            try:
                slot_number = int(raw_id)
            except (TypeError, ValueError):
                continue
            if slot_number in question_map:
                targets.add(slot_number)

        range_start = edit.get("range_start")
        range_end = edit.get("range_end")
        if isinstance(range_start, int) and isinstance(range_end, int):
            if range_start > range_end:
                range_start, range_end = range_end, range_start
            for slot_number in range(range_start, range_end + 1):
                if slot_number in question_map:
                    targets.add(slot_number)

        if not targets and str(edit.get("edit_type", "")).strip().lower() == "regenerate":
            targets = set(question_map)

        return sorted(targets)

    def _mark_for_revalidation(self, question: GeneratedQuestion) -> None:
        question.is_human_edited = True
        question.is_validated = False
        question.verification_status = "pending"
        question.validation_notes = ""
