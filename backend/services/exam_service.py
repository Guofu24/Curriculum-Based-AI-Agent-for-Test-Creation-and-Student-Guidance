"""
Exam Service

Manages exam generation workflow, exam CRUD, and coordinates with the LangGraph
multi-agent orchestrator.
"""
import uuid
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from config import settings
from models.exam import Exam, ExamQuestion, ExamStatus, ExamType, DifficultyLevel, QuestionType, BloomLevel
from schemas.exam import ExamGenerationRequest, ExamPartialRegenerateRequest
from agents.orchestrator import create_exam_generation_graph
from agents.state import AgentState
from agents.retrieval import RetrievalAgent
from agents.blueprint import BlueprintAgent
from agents.question_generator import QuestionGeneratorAgent
from agents.validator import ValidatorAgent
from agents.reviewer import ReviewerAgent
from agents.pruning import PruningAgent
from services.rag_service import RAGService
from services.textbook_service import TextbookService

logger = logging.getLogger(__name__)


class ExamService:

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_llm(self):
        """Get the configured LLM instance."""
        if settings.LLM_PROVIDER == "groq":
            from langchain_groq import ChatGroq
            return ChatGroq(
                model=settings.GROQ_MODEL,
                api_key=settings.GROQ_API_KEY,
                temperature=0.7,
            )
        elif settings.LLM_PROVIDER == "g4f":
            from agents.llm_g4f import ChatG4F
            return ChatG4F(
                model=settings.G4F_MODEL,
                provider=settings.G4F_PROVIDER or None,
                temperature=0.7,
            )
        elif settings.LLM_PROVIDER == "together":
            # Together AI is OpenAI-compatible — no extra package needed
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=settings.TOGETHER_MODEL,
                api_key=settings.TOGETHER_API_KEY,
                base_url="https://api.together.xyz/v1",
                temperature=0.7,
            )
        elif settings.LLM_PROVIDER == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=settings.GOOGLE_MODEL,
                google_api_key=settings.GOOGLE_API_KEY,
                temperature=0.7,
            )
        elif settings.LLM_PROVIDER == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=settings.OPENAI_MODEL,
                api_key=settings.OPENAI_API_KEY,
                temperature=0.7,
            )
        else:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=settings.ANTHROPIC_MODEL,
                api_key=settings.ANTHROPIC_API_KEY,
            )

    async def generate_exam(
        self,
        user_id: str,
        request: ExamGenerationRequest,
    ) -> Exam:
        """
        Run the full multi-agent exam generation pipeline.
        """
        llm = self._get_llm()
        rag = RAGService.get_instance()
        vector_store = rag.get_vector_store(namespace=request.textbook_id)

        # Initialize agents
        retrieval_agent = RetrievalAgent(vector_store, db_session=self.db)
        blueprint_agent = BlueprintAgent()  # No LLM needed for deterministic blueprint
        question_generator = QuestionGeneratorAgent(llm)
        validator = ValidatorAgent()  # Rule-based, no LLM needed
        reviewer = ReviewerAgent(question_generator, retrieval_agent)
        pruning_agent = PruningAgent()

        # Get textbook metadata
        textbook_svc = TextbookService(self.db)
        textbook_metadata = await textbook_svc.get_textbook_metadata(
            request.textbook_id, user_id
        )

        if not textbook_metadata:
            raise ValueError("Textbook not found or not processed")

        # Create exam record
        exam = Exam(
            id=str(uuid.uuid4()),
            owner_id=user_id,
            textbook_id=request.textbook_id,
            title=f"Exam - {textbook_metadata.get('title', 'Untitled')}",
            exam_type=ExamType(request.exam_type),
            difficulty=DifficultyLevel(request.difficulty),
            status=ExamStatus.GENERATING,
            chapters=request.chapters,
            config=request.model_dump(),
        )
        self.db.add(exam)
        await self.db.flush()

        # Build initial agent state
        initial_state: AgentState = {
            "user_id": user_id,
            "textbook_id": request.textbook_id,
            "chapters": request.chapters,
            "prompt": request.prompt,
            "exam_type": request.exam_type,
            "difficulty": request.difficulty,
            "question_distribution": request.question_distribution.model_dump(),
            "num_variants": request.num_variants,
            "gradually_increasing": request.gradually_increasing,
            "constraints": request.constraints.model_dump(),
            "textbook_metadata": textbook_metadata,
            "processing_status": "ready",
            "blueprint": None,
            "retrieved_contexts": [],
            "generated_questions": [],
            "validated_questions": [],
            "validation_summary": {},
            "current_step": "parsing",
            "step_progress": 0.0,
            "error": None,
            # Micro-prompting fields
            "chunk_assignments": [],
            "original_quota": {},
            # Partial edit fields
            "edit_requests": None,
            "is_partial_edit": False,
            # Inject agent instances (not serialized, used by nodes)
            "_retrieval_agent": retrieval_agent,
            "_blueprint_agent": blueprint_agent,
            "_question_generator": question_generator,
            "_validator": validator,
            "_reviewer": reviewer,
            "_pruning_agent": pruning_agent,
            "_db_session": self.db,
            "_retry_attempted": False,
        }

        # Run the LangGraph workflow
        try:
            graph = create_exam_generation_graph()
            final_state = await graph.ainvoke(initial_state)

            # Save generated questions to DB
            validated_questions = final_state.get("validated_questions", [])
            for q in validated_questions:
                db_question = ExamQuestion(
                    id=str(uuid.uuid4()),
                    exam_id=exam.id,
                    question_number=q.slot_number,
                    question_type=QuestionType(q.question_type),
                    bloom_level=BloomLevel(q.bloom_level),
                    difficulty_score=q.difficulty_score,
                    content=q.content,
                    options=q.options,
                    correct_answer=q.correct_answer,
                    explanation=q.explanation,
                    source_chunks=q.source_chunks,
                    is_validated=q.is_validated,
                    validation_notes=q.validation_notes,
                )
                self.db.add(db_question)

            # Update exam status
            exam.status = ExamStatus.GENERATED
            exam.total_questions = len(validated_questions)
            summary = final_state.get("validation_summary", {})
            exam.quality_score = summary.get("pass_rate", 0.0) * 100

            logger.info(
                f"Exam generated: {exam.id}, "
                f"questions={exam.total_questions}, "
                f"quality={exam.quality_score:.1f}%"
            )

        except Exception as e:
            exam.status = ExamStatus.GENERATING  # keep as generating on error
            logger.error(f"Exam generation failed: {e}")
            raise

        return exam

    async def partial_regenerate(
        self,
        user_id: str,
        request: ExamPartialRegenerateRequest,
    ) -> Exam:
        """Regenerate specific questions in an existing exam."""
        # Load the exam with questions
        exam = await self.get_exam(request.exam_id, user_id)
        if not exam:
            raise ValueError("Exam not found")

        llm = self._get_llm()
        rag = RAGService.get_instance()
        vector_store = rag.get_vector_store(namespace=exam.textbook_id)

        retrieval_agent = RetrievalAgent(vector_store, db_session=self.db)
        question_generator = QuestionGeneratorAgent(llm)
        validator = ValidatorAgent()  # Rule-based, no LLM needed
        reviewer = ReviewerAgent(question_generator, retrieval_agent)

        # Convert existing DB questions to GeneratedQuestion objects
        from agents.state import GeneratedQuestion
        existing = []
        for q in exam.questions:
            existing.append(GeneratedQuestion(
                slot_number=q.question_number,
                question_type=q.question_type.value,
                bloom_level=q.bloom_level.value,
                difficulty_score=q.difficulty_score,
                content=q.content,
                options=q.options,
                correct_answer=q.correct_answer,
                explanation=q.explanation or "",
                source_chunks=q.source_chunks or [],
                is_validated=q.is_validated,
            ))

        # Build edit state
        edit_requests = [
            {
                "question_ids": e.question_ids,
                "range_start": e.range_start,
                "range_end": e.range_end,
                "edit_prompt": e.edit_prompt,
                "edit_type": e.edit_type,
            }
            for e in request.edits
        ]

        constraints = exam.config.get("constraints", {})

        initial_state: AgentState = {
            "user_id": user_id,
            "textbook_id": exam.textbook_id,
            "chapters": exam.chapters,
            "prompt": "",
            "exam_type": exam.exam_type.value,
            "difficulty": exam.difficulty.value,
            "question_distribution": {},
            "num_variants": 1,
            "gradually_increasing": False,
            "constraints": constraints,
            "textbook_metadata": {},
            "processing_status": "ready",
            "blueprint": None,
            "retrieved_contexts": [],
            "generated_questions": [],
            "validated_questions": existing,
            "validation_summary": {},
            "current_step": "editing",
            "step_progress": 0.0,
            "error": None,
            # Micro-prompting fields (not used for partial edit)
            "chunk_assignments": [],
            "original_quota": {},
            # Partial edit fields
            "edit_requests": edit_requests,
            "is_partial_edit": True,
            "_retrieval_agent": retrieval_agent,
            "_blueprint_agent": None,
            "_question_generator": question_generator,
            "_validator": validator,
            "_reviewer": reviewer,
            "_pruning_agent": PruningAgent(),
            "_db_session": self.db,
            "_retry_attempted": False,
        }

        graph = create_exam_generation_graph()
        final_state = await graph.ainvoke(initial_state)

        # Update questions in DB
        new_questions = final_state.get("validated_questions", [])
        # Delete old questions and insert new ones
        for old_q in exam.questions:
            await self.db.delete(old_q)

        for q in new_questions:
            db_question = ExamQuestion(
                id=str(uuid.uuid4()),
                exam_id=exam.id,
                question_number=q.slot_number,
                question_type=QuestionType(q.question_type),
                bloom_level=BloomLevel(q.bloom_level),
                difficulty_score=q.difficulty_score,
                content=q.content,
                options=q.options,
                correct_answer=q.correct_answer,
                explanation=q.explanation,
                source_chunks=q.source_chunks,
                is_validated=q.is_validated,
                validation_notes=q.validation_notes,
            )
            self.db.add(db_question)

        exam.status = ExamStatus.GENERATED
        return exam

    async def get_exam(self, exam_id: str, user_id: str) -> Exam | None:
        """Get a specific exam with questions."""
        result = await self.db.execute(
            select(Exam)
            .where(Exam.id == exam_id, Exam.owner_id == user_id)
            .options(selectinload(Exam.questions))
        )
        return result.scalar_one_or_none()

    async def get_exams(self, user_id: str) -> list[Exam]:
        """Get all exams for a user."""
        result = await self.db.execute(
            select(Exam)
            .where(Exam.owner_id == user_id)
            .order_by(Exam.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_exam(self, exam_id: str, user_id: str) -> bool:
        """Delete an exam."""
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return False
        await self.db.delete(exam)
        return True
