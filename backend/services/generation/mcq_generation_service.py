from __future__ import annotations

from agents.question_generator import QuestionGeneratorAgent
from agents.state import ChunkAssignment, GeneratedQuestion, RetrievedContext


class MCQGenerationService:
    def __init__(self, llm):
        self.generator = QuestionGeneratorAgent(llm)

    async def generate(
        self,
        chunk_assignments: list[ChunkAssignment],
        strict_scope: bool = True,
    ) -> list[GeneratedQuestion]:
        constraints = {
            "strict_grounding": True,
            "strict_scope": strict_scope,
            "allow_applied_questions": False,
            "max_concurrency": 1,
        }
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
    ) -> GeneratedQuestion:
        constraints = {
            "strict_grounding": True,
            "strict_scope": True,
            "allow_applied_questions": False,
        }
        regenerated = await self.generator.regenerate_single(
            original_question=original_question,
            context=context,
            constraints=constraints,
            edit_prompt=edit_prompt,
        )
        regenerated.question_type = "mcq"
        return regenerated
