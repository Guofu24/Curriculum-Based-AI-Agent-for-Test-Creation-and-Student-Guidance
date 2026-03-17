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
        edit_prompts: dict[int, str] = {}
        text_edits: dict[int, str] = {}

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

        for slot_num in sorted(to_regenerate):
            if slot_num not in question_map:
                continue

            original = question_map[slot_num]

            query = f"{original.content}\n\n{original.bloom_level} {original.question_type}"
            context = await self.retrieval.retrieve_for_single_question(
                query=query,
                textbook_id=textbook_id,
                chapter=chapter_hint,
            )

            new_question = await self.generator.regenerate_single(
                original_question=original,
                context=context,
                constraints=constraints,
                edit_prompt=edit_prompts.get(slot_num, ""),
            )
            result_map[slot_num] = new_question

        return [result_map[q.slot_number] for q in existing_questions]

    async def edit_question_text(
        self,
        question: GeneratedQuestion,
        new_content: str,
    ) -> GeneratedQuestion:
        """Directly edit a question's text without regeneration."""
        question.content = new_content
        question.is_validated = False  # needs re-validation
        question.validation_notes = "Manually edited - needs re-validation"
        return question
