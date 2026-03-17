"""
Reviewer Agent (Partial Regeneration)

Responsibilities:
- Handle targeted edits to specific questions
- Regenerate question ranges while preserving others
- Maintain exam consistency after partial edits
- Support surgical question replacement
"""
from agents.state import GeneratedQuestion, RetrievedContext
from agents.question_generator import QuestionGeneratorAgent
from agents.retrieval import RetrievalAgent


class ReviewerAgent:
    """Handles partial exam edits and targeted question regeneration."""

    def __init__(
        self,
        question_generator: QuestionGeneratorAgent,
        retrieval_agent: RetrievalAgent,
    ):
        self.generator = question_generator
        self.retrieval = retrieval_agent

    async def partial_regenerate(
        self,
        existing_questions: list[GeneratedQuestion],
        edit_requests: list[dict],
        textbook_id: str,
        chapters: list[int],
        constraints: dict,
    ) -> list[GeneratedQuestion]:
        """
        Regenerate specific questions while preserving others.

        edit_requests format:
        [
            {
                "question_ids": ["id1", "id2"],  # specific questions
                "range_start": 1,  # or specify a range
                "range_end": 5,
                "edit_prompt": "Make it harder",
                "edit_type": "regenerate"  # regenerate | edit_text
            }
        ]
        """
        question_map = {q.slot_number: q for q in existing_questions}
        result_map = {q.slot_number: q for q in existing_questions}
        chapter_hint = chapters[0] if len(chapters) == 1 else 0
        to_regenerate: set[int] = set()
        to_delete: set[int] = set()
        to_lock: set[int] = set()
        to_unlock: set[int] = set()
        edit_prompts: dict[int, str] = {}
        text_edits: dict[int, str] = {}
        answer_edits: dict[int, str] = {}
        bloom_edits: dict[int, str] = {}

        for edit in edit_requests:
            targets: set[int] = set()
            if edit.get("question_ids"):
                for qid in edit["question_ids"]:
                    try:
                        slot = int(qid)
                    except (TypeError, ValueError):
                        continue
                    if slot in question_map:
                        targets.add(slot)

            if edit.get("range_start") is not None and edit.get("range_end") is not None:
                for num in range(int(edit["range_start"]), int(edit["range_end"]) + 1):
                    if num in question_map:
                        targets.add(num)

            edit_type = str(edit.get("edit_type", "regenerate")).lower()
            if edit_type == "edit_text":
                new_content = (edit.get("new_content") or "").strip()
                if not new_content:
                    continue
                for slot in targets:
                    text_edits[slot] = new_content
                continue
            if edit_type == "edit_answer":
                new_answer = (edit.get("new_correct_answer") or "").strip()
                if not new_answer:
                    continue
                for slot in targets:
                    answer_edits[slot] = new_answer
                continue
            if edit_type == "edit_bloom":
                new_bloom = (edit.get("new_bloom_level") or "").strip().lower()
                if not new_bloom:
                    continue
                for slot in targets:
                    bloom_edits[slot] = new_bloom
                continue
            if edit_type == "lock":
                to_lock.update(targets)
                continue
            if edit_type == "unlock":
                to_unlock.update(targets)
                continue
            if edit_type == "delete":
                to_delete.update(targets)
                continue

            for slot in targets:
                to_regenerate.add(slot)
                if edit.get("edit_prompt"):
                    edit_prompts[slot] = edit["edit_prompt"]

        for slot_num, new_content in text_edits.items():
            if slot_num not in result_map:
                continue
            result_map[slot_num] = await self.edit_question_text(
                question=result_map[slot_num],
                new_content=new_content,
            )

        for slot_num, new_answer in answer_edits.items():
            if slot_num not in result_map:
                continue
            result_map[slot_num] = await self.edit_question_answer(
                question=result_map[slot_num],
                new_answer=new_answer,
            )

        for slot_num, new_bloom in bloom_edits.items():
            if slot_num not in result_map:
                continue
            result_map[slot_num] = await self.edit_question_bloom(
                question=result_map[slot_num],
                new_bloom_level=new_bloom,
            )

        for slot_num in to_lock:
            if slot_num in result_map:
                result_map[slot_num].is_locked = True

        for slot_num in to_unlock:
            if slot_num in result_map:
                result_map[slot_num].is_locked = False

        for slot_num in sorted(to_regenerate):
            if slot_num not in question_map:
                continue

            original = question_map[slot_num]
            if original.is_locked and slot_num not in to_unlock:
                continue
            scoped_chapters = self._extract_scope_chapters(original.scope_tags)
            if not scoped_chapters and chapter_hint:
                scoped_chapters = [chapter_hint]

            query = f"{original.content}\n\n{original.bloom_level} {original.question_type}"
            context = await self.retrieval.retrieve_for_single_question(
                query=query,
                textbook_id=textbook_id,
                chapters=scoped_chapters,
                scope_tags=original.scope_tags,
            )

            new_question = await self.generator.regenerate_single(
                original_question=original,
                context=context,
                constraints=constraints,
                edit_prompt=edit_prompts.get(slot_num, ""),
            )
            if not new_question.scope_tags:
                new_question.scope_tags = list(original.scope_tags or [])
            new_question.is_locked = original.is_locked
            result_map[slot_num] = new_question

        for slot_num in to_delete:
            result_map.pop(slot_num, None)

        return self._renumber_questions(result_map)

    async def edit_question_text(
        self,
        question: GeneratedQuestion,
        new_content: str,
    ) -> GeneratedQuestion:
        """Directly edit a question's text without regeneration."""
        question.content = new_content
        question.is_human_edited = True
        question.verification_status = "pending"
        question.is_validated = False  # needs re-validation
        question.validation_notes = "Manually edited - needs re-validation"
        return question

    async def edit_question_answer(
        self,
        question: GeneratedQuestion,
        new_answer: str,
    ) -> GeneratedQuestion:
        question.correct_answer = new_answer
        return self._mark_for_revalidation(
            question,
            notes="Answer manually edited - needs re-validation",
        )

    async def edit_question_bloom(
        self,
        question: GeneratedQuestion,
        new_bloom_level: str,
    ) -> GeneratedQuestion:
        question.bloom_level = new_bloom_level
        return self._mark_for_revalidation(
            question,
            notes="Bloom level manually edited - needs re-validation",
        )

    def _mark_for_revalidation(
        self,
        question: GeneratedQuestion,
        notes: str,
    ) -> GeneratedQuestion:
        question.is_human_edited = True
        question.verification_status = "pending"
        question.is_validated = False
        question.validation_notes = notes
        return question

    def _renumber_questions(self, result_map: dict[int, GeneratedQuestion]) -> list[GeneratedQuestion]:
        questions = [result_map[key] for key in sorted(result_map)]
        for index, question in enumerate(questions, start=1):
            question.slot_number = index
        return questions

    def _extract_scope_chapters(self, scope_tags: list[str]) -> list[int]:
        chapters: list[int] = []
        for tag in scope_tags or []:
            if not isinstance(tag, str) or not tag.startswith("chapter:"):
                continue
            _, _, raw_number = tag.partition(":")
            if raw_number.isdigit():
                chapter_number = int(raw_number)
                if chapter_number > 0 and chapter_number not in chapters:
                    chapters.append(chapter_number)
        return chapters
