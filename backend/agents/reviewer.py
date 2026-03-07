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
        # Create a map of question number -> question
        question_map = {q.slot_number: q for q in existing_questions}

        # Determine which questions to regenerate
        to_regenerate = set()
        edit_prompts = {}  # slot_number -> edit prompt

        for edit in edit_requests:
            # By specific IDs (slot numbers in our case)
            if edit.get("question_ids"):
                for qid in edit["question_ids"]:
                    # Find slot number by checking existing questions
                    for q in existing_questions:
                        if str(q.slot_number) == str(qid):
                            to_regenerate.add(q.slot_number)
                            if edit.get("edit_prompt"):
                                edit_prompts[q.slot_number] = edit["edit_prompt"]

            # By range
            if edit.get("range_start") is not None and edit.get("range_end") is not None:
                for num in range(edit["range_start"], edit["range_end"] + 1):
                    if num in question_map:
                        to_regenerate.add(num)
                        if edit.get("edit_prompt"):
                            edit_prompts[num] = edit["edit_prompt"]

        # Regenerate only the targeted questions
        result = list(existing_questions)  # copy

        for slot_num in to_regenerate:
            if slot_num not in question_map:
                continue

            original = question_map[slot_num]

            # Retrieve fresh context for this question
            query = f"chapter {original.bloom_level} {original.question_type}"
            context = await self.retrieval.retrieve_for_single_question(
                query=query,
                textbook_id=textbook_id,
                chapter=0,  # use original context
            )

            # Regenerate with optional edit prompt
            new_question = await self.generator.regenerate_single(
                original_question=original,
                context=context,
                constraints=constraints,
                edit_prompt=edit_prompts.get(slot_num, ""),
            )

            # Replace in result list
            for i, q in enumerate(result):
                if q.slot_number == slot_num:
                    result[i] = new_question
                    break

        return result

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
