from __future__ import annotations

from app.services.generation.question_generator import QuestionGeneratorService
from app.core.runtime_models import ChunkAssignment, GeneratedQuestion, RetrievedContext


class MCQGenerationService:
    def __init__(self, llm):
        self.generator = QuestionGeneratorService(llm)

    async def generate(
        self,
        chunk_assignments: list[ChunkAssignment],
        strict_scope: bool = True,
        playbook_lines: list[str] | None = None,
    ) -> list[GeneratedQuestion]:
        _ = strict_scope
        constraints = {
            "strict_grounding": True,
            "strict_scope": True,
            "allow_applied_questions": False,
            "max_concurrency": 1,
        }
        if playbook_lines:
            constraints["_playbook_lines"] = list(playbook_lines)
        questions = await self.generator.generate_from_chunks_parallel(
            chunk_assignments=chunk_assignments,
            constraints=constraints,
            max_concurrency=1,
        )
        for question in questions:
            question.question_type = "mcq"
        return questions

    async def regenerate_question(
        self,
        original_question: GeneratedQuestion,
        context: RetrievedContext,
        edit_prompt: str = "",
        playbook_lines: list[str] | None = None,
    ) -> GeneratedQuestion:
        constraints = {
            "strict_grounding": True,
            "strict_scope": True,
            "allow_applied_questions": False,
        }
        if playbook_lines:
            constraints["_playbook_lines"] = list(playbook_lines)
        regenerated = await self.generator.regenerate_single(
            original_question=original_question,
            context=context,
            constraints=constraints,
            edit_prompt=edit_prompt,
        )
        regenerated.question_type = "mcq"
        return regenerated

