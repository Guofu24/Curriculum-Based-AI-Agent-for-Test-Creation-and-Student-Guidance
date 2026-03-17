"""
Exam Service

Coordinates generation, versioning, and audit-friendly persistence for exams.
"""
import logging
import uuid
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.blueprint import BlueprintAgent
from agents.dedup_filter import DedupFilterAgent
from agents.grounding_checker import GroundingChecker
from agents.llm_router import create_llm
from agents.orchestrator import create_exam_generation_graph
from agents.pruning import PruningAgent
from agents.quality_judge import QualityJudgeAgent
from agents.question_generator import QuestionGeneratorAgent
from agents.retrieval import RetrievalAgent
from agents.reviewer import ReviewerAgent
from agents.state import AgentState, GeneratedQuestion
from agents.validator import ValidatorAgent
from models.exam import (
    BloomLevel,
    BlueprintCellRecord,
    DifficultyLevel,
    EditOperation,
    Exam,
    ExamQuestion,
    ExamSpecRecord,
    ExamStatus,
    ExamType,
    ExamVersion,
    QuestionType,
)
from models.course import CourseMembership
from schemas.exam import ExamGenerationRequest, ExamPartialRegenerateRequest
from services.rag_service import RAGService
from services.textbook_service import TextbookService

logger = logging.getLogger(__name__)


class ExamService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_llm(self):
        return create_llm()

    def _normalize_question_id_to_slot(
        self,
        raw_id: str,
        id_to_slot: dict[str, int],
    ) -> int | None:
        if raw_id in id_to_slot:
            return id_to_slot[raw_id]
        try:
            slot = int(raw_id)
            return slot if slot > 0 else None
        except (TypeError, ValueError):
            return None

    def _serialize_scope(self, request: ExamGenerationRequest) -> list[dict]:
        if request.scope:
            return [item.model_dump() for item in request.scope]
        return [
            {
                "scope_id": f"chapter:{chapter}",
                "scope_type": "chapter",
                "title": f"Chapter {chapter}",
                "chapter_number": int(chapter),
                "tags": [f"chapter:{int(chapter)}"],
            }
            for chapter in request.chapters
        ]

    def _serialize_dataclass(self, value):
        if value is None:
            return None
        if isinstance(value, list):
            return [self._serialize_dataclass(item) for item in value]
        if isinstance(value, dict):
            return {
                key: self._serialize_dataclass(item)
                for key, item in value.items()
            }
        if isinstance(value, (str, int, float, bool)):
            return value
        return asdict(value)

    def _question_snapshot(self, question: GeneratedQuestion | ExamQuestion) -> dict:
        if isinstance(question, GeneratedQuestion):
            return {
                "question_number": question.slot_number,
                "content": question.content,
                "question_type": question.question_type,
                "bloom_level": question.bloom_level,
                "correct_answer": question.correct_answer,
                "rubric": question.rubric,
                "explanation": question.explanation,
                "source_chunks": list(question.source_chunks or []),
                "source_evidence": list(question.source_evidence or []),
                "scope_tags": list(question.scope_tags or []),
                "is_locked": bool(question.is_locked),
            }
        return {
            "question_number": question.question_number,
            "content": question.content,
            "question_type": question.question_type.value,
            "bloom_level": question.bloom_level.value,
            "correct_answer": question.correct_answer,
            "rubric": question.rubric_json,
            "explanation": question.explanation,
            "source_chunks": list(question.source_chunks or []),
            "source_evidence": list(question.source_evidence_json or []),
            "scope_tags": list(question.scope_tags_json or []),
            "is_locked": bool(question.is_locked),
        }

    def _question_to_db(
        self,
        exam_id: str,
        exam_version_id: str,
        question: GeneratedQuestion,
        quality_by_slot: dict[int, dict],
        grounding_by_slot: dict[int, dict],
    ) -> ExamQuestion:
        return ExamQuestion(
            id=str(uuid.uuid4()),
            exam_id=exam_id,
            exam_version_id=exam_version_id,
            question_number=question.slot_number,
            blueprint_cell_key=question.blueprint_cell_key or None,
            question_type=QuestionType(question.question_type),
            bloom_level=BloomLevel(question.bloom_level),
            difficulty_score=question.difficulty_score,
            content=question.content,
            options=question.options,
            correct_answer=question.correct_answer,
            rubric_json=question.rubric,
            explanation=question.explanation,
            source_chunks=question.source_chunks,
            source_evidence_json=question.source_evidence,
            scope_tags_json=question.scope_tags,
            warnings_json=question.warnings,
            verification_status=question.verification_status,
            is_human_edited=question.is_human_edited,
            is_locked=question.is_locked,
            is_validated=question.is_validated,
            validation_notes=question.validation_notes,
            quality_score_json=quality_by_slot.get(question.slot_number),
            grounding_report_json=grounding_by_slot.get(question.slot_number),
        )

    def _db_question_to_generated(self, question: ExamQuestion) -> GeneratedQuestion:
        source_evidence = list(question.source_evidence_json or [])
        source_texts = [
            (item.get("text_preview") or "")
            for item in source_evidence
            if isinstance(item, dict)
        ]
        return GeneratedQuestion(
            slot_number=question.question_number,
            blueprint_cell_key=question.blueprint_cell_key or "",
            question_type=question.question_type.value,
            bloom_level=question.bloom_level.value,
            difficulty_score=question.difficulty_score,
            content=question.content,
            options=question.options,
            correct_answer=question.correct_answer,
            rubric=question.rubric_json,
            explanation=question.explanation or "",
            source_chunks=list(question.source_chunks or []),
            source_texts=source_texts,
            source_evidence=source_evidence,
            scope_tags=list(question.scope_tags_json or []),
            warnings=list(question.warnings_json or []),
            verification_status=question.verification_status or "pending",
            is_human_edited=bool(question.is_human_edited),
            is_locked=bool(question.is_locked),
            is_validated=bool(question.is_validated),
            validation_notes=question.validation_notes or "",
        )

    async def _resolve_textbook(
        self,
        user_id: str,
        request: ExamGenerationRequest,
    ) -> tuple[str, str | None, dict]:
        textbook_svc = TextbookService(self.db)

        if request.textbook_id:
            metadata = await textbook_svc.get_textbook_metadata(request.textbook_id, user_id)
            if not metadata:
                raise ValueError("Document not found or not processed")
            course_id = request.course_id or metadata.get("course_id")
            return request.textbook_id, course_id, metadata

        if request.course_id:
            documents = await textbook_svc.get_textbooks(user_id=user_id, course_id=request.course_id)
            processed = [
                document for document in documents
                if document.status.value in {"indexed", "processed"}
            ]
            if len(processed) == 1:
                metadata = await textbook_svc.get_textbook_metadata(processed[0].id, user_id)
                return processed[0].id, request.course_id, metadata
            if not processed:
                raise ValueError("No processed documents found for course")
            raise ValueError("Course has multiple documents; provide document_id/textbook_id")

        raise ValueError("Document not found or not processed")

    async def _create_exam_version(
        self,
        exam: Exam,
        user_id: str,
        version_number: int,
        status: str,
        parent_version_id: str | None = None,
        change_summary: str | None = None,
    ) -> ExamVersion:
        version = ExamVersion(
            exam_id=exam.id,
            version_number=version_number,
            status=status,
            created_by=user_id,
            parent_version_id=parent_version_id,
            change_summary=change_summary,
        )
        self.db.add(version)
        await self.db.flush()
        return version

    async def _persist_exam_spec_records(
        self,
        exam: Exam,
        user_id: str,
        course_id: str | None,
        exam_spec,
        blueprint,
    ) -> None:
        if not exam_spec:
            return

        spec_record = ExamSpecRecord(
            exam_id=exam.id,
            course_id=course_id,
            creator_user_id=user_id,
            exam_type=exam_spec.exam_type,
            time_limit_minutes=exam_spec.time_limit_minutes,
            language=exam_spec.output_language,
            instructions=exam_spec.instructions,
            strict_scope_flag=exam_spec.strict_scope_flag,
            bloom_distribution_json=exam_spec.bloom_distribution,
            question_mix_json=exam_spec.question_mix,
            formatting_preferences_json=exam_spec.formatting_preferences,
            total_questions=exam_spec.total_questions,
            selected_scope_json=self._serialize_dataclass(exam_spec.selected_scope),
            source_prompt=exam_spec.source_prompt,
            status="generated",
        )
        self.db.add(spec_record)
        await self.db.flush()

        for cell in blueprint.cells:
            self.db.add(
                BlueprintCellRecord(
                    exam_spec_id=spec_record.id,
                    cell_key=cell.cell_id,
                    scope_unit_json=self._serialize_dataclass(cell.scope_unit),
                    question_type=cell.question_type,
                    bloom_level=cell.bloom_level,
                    target_count=cell.target_count,
                    generated_count=cell.generated_count,
                    priority=cell.priority,
                    overgenerate_count=cell.overgenerate_count,
                )
            )

    async def _persist_edit_operations(
        self,
        exam_version_id: str,
        user_id: str,
        edit_requests: list[dict],
        old_questions: list[ExamQuestion],
        new_questions: list[GeneratedQuestion],
    ) -> None:
        old_by_slot = {question.question_number: question for question in old_questions}
        new_by_slot = {question.slot_number: question for question in new_questions}

        for edit in edit_requests:
            targeted_slots: set[int] = set()
            for raw_id in edit.get("question_ids", []):
                try:
                    targeted_slots.add(int(raw_id))
                except (TypeError, ValueError):
                    continue
            if edit.get("range_start") is not None and edit.get("range_end") is not None:
                for slot in range(int(edit["range_start"]), int(edit["range_end"]) + 1):
                    targeted_slots.add(slot)

            old_values = [
                self._question_snapshot(old_by_slot[slot])
                for slot in sorted(targeted_slots)
                if slot in old_by_slot
            ]
            new_values = [
                self._question_snapshot(new_by_slot[slot])
                for slot in sorted(targeted_slots)
                if slot in new_by_slot
            ]

            self.db.add(
                EditOperation(
                    exam_version_id=exam_version_id,
                    actor_id=user_id,
                    edit_type=edit.get("edit_type", "regenerate"),
                    target_question_id=",".join(str(slot) for slot in sorted(targeted_slots)) or None,
                    old_value={"questions": old_values} if old_values else None,
                    new_value={"questions": new_values} if new_values else None,
                    prompt_used=edit.get("edit_prompt"),
                )
            )

    def _build_agents(self, textbook_id: str):
        llm = self._get_llm()
        rag = RAGService.get_instance()
        vector_store = rag.get_vector_store(namespace=textbook_id)

        retrieval_agent = RetrievalAgent(vector_store, db_session=self.db)
        blueprint_agent = BlueprintAgent()
        question_generator = QuestionGeneratorAgent(llm)
        grounding_checker = GroundingChecker()
        validator = ValidatorAgent(grounding_checker=grounding_checker)
        reviewer = ReviewerAgent(question_generator, retrieval_agent)
        pruning_agent = PruningAgent()
        quality_judge = QualityJudgeAgent(grounding_checker=grounding_checker)
        dedup_filter = DedupFilterAgent()

        return {
            "_retrieval_agent": retrieval_agent,
            "_blueprint_agent": blueprint_agent,
            "_question_generator": question_generator,
            "_validator": validator,
            "_reviewer": reviewer,
            "_pruning_agent": pruning_agent,
            "_quality_judge": quality_judge,
            "_dedup_filter": dedup_filter,
        }

    async def generate_exam(
        self,
        user_id: str,
        request: ExamGenerationRequest,
    ) -> Exam:
        textbook_id, course_id, textbook_metadata = await self._resolve_textbook(user_id, request)
        serialized_scope = self._serialize_scope(request)
        selected_chapters = request.chapters or [
            int(item.get("chapter_number", 0))
            for item in serialized_scope
            if int(item.get("chapter_number", 0)) > 0
        ]

        exam = Exam(
            id=str(uuid.uuid4()),
            owner_id=user_id,
            course_id=course_id,
            textbook_id=textbook_id,
            title=f"Exam - {textbook_metadata.get('title', 'Untitled')}",
            exam_type=ExamType(request.exam_type),
            difficulty=DifficultyLevel(request.difficulty),
            status=ExamStatus.GENERATING,
            chapters=selected_chapters,
            config=request.model_dump(),
            instructions=request.instructions,
            output_language=request.output_language,
            strict_scope_flag=bool(request.strict_scope),
            selected_scope_json=serialized_scope,
            edit_history_json=[],
        )
        self.db.add(exam)
        await self.db.flush()

        initial_state: AgentState = {
            "user_id": user_id,
            "textbook_id": textbook_id,
            "chapters": selected_chapters,
            "prompt": request.prompt,
            "exam_type": request.exam_type,
            "difficulty": request.difficulty,
            "question_distribution": request.question_distribution.model_dump(),
            "num_variants": request.num_variants,
            "gradually_increasing": request.gradually_increasing,
            "constraints": request.constraints.model_dump(),
            "textbook_metadata": textbook_metadata,
            "processing_status": "ready",
            "exam_spec": None,
            "blueprint": None,
            "retrieved_contexts": [],
            "generated_questions": [],
            "validated_questions": [],
            "validation_summary": {},
            "judged_questions": [],
            "quality_scores": [],
            "grounding_reports": [],
            "duplicate_groups": [],
            "final_questions": [],
            "current_step": "parsing",
            "step_progress": 0.0,
            "error": None,
            "chunk_assignments": [],
            "chunk_assignment_payloads": [],
            "question_chunk_metadata": [],
            "original_quota": {},
            "edit_requests": None,
            "is_partial_edit": False,
            "edit_impact_level": None,
            "refreshed_contexts": [],
            "provider_logs": [],
            "scope": serialized_scope,
            "time_limit_minutes": request.time_limit_minutes,
            "output_language": request.output_language,
            "instructions": request.instructions,
            "bloom_distribution": request.bloom_distribution,
            "formatting_preferences": request.formatting_preferences,
            "strict_scope": request.strict_scope,
            "_db_session": self.db,
            "_retry_attempted": False,
            **self._build_agents(textbook_id),
        }

        try:
            graph = create_exam_generation_graph()
            final_state = await graph.ainvoke(initial_state)

            validated_questions = final_state.get("validated_questions", [])
            quality_scores = final_state.get("quality_scores", [])
            grounding_reports = final_state.get("grounding_reports", [])
            qs_by_slot = {
                item["slot_number"]: item
                for item in quality_scores
                if isinstance(item, dict) and "slot_number" in item
            }
            gr_by_slot = {
                item["slot_number"]: item
                for item in grounding_reports
                if isinstance(item, dict) and "slot_number" in item
            }

            version = await self._create_exam_version(
                exam=exam,
                user_id=user_id,
                version_number=1,
                status="generated",
                change_summary="Initial generation",
            )

            for question in validated_questions:
                self.db.add(
                    self._question_to_db(
                        exam_id=exam.id,
                        exam_version_id=version.id,
                        question=question,
                        quality_by_slot=qs_by_slot,
                        grounding_by_slot=gr_by_slot,
                    )
                )

            await self._persist_exam_spec_records(
                exam=exam,
                user_id=user_id,
                course_id=course_id,
                exam_spec=final_state.get("exam_spec"),
                blueprint=final_state.get("blueprint"),
            )

            exam.current_version_id = version.id
            exam.status = ExamStatus.GENERATED
            exam.total_questions = len(validated_questions)
            exam.exam_spec_json = self._serialize_dataclass(final_state.get("exam_spec"))
            exam.blueprint_json = self._serialize_dataclass(final_state.get("blueprint"))
            exam.quality_score = final_state.get("validation_summary", {}).get("pass_rate", 0.0) * 100
            exam.quality_scores_json = quality_scores or None
            exam.grounding_reports_json = grounding_reports or None
            exam.duplicate_groups_json = final_state.get("duplicate_groups") or None
            exam.provider_logs_json = final_state.get("provider_logs") or None
            exam.edit_impact_level = final_state.get("edit_impact_level")

            logger.info(
                "Exam generated: %s, questions=%s, version=%s",
                exam.id,
                exam.total_questions,
                version.version_number,
            )
        except Exception as exc:
            exam.status = ExamStatus.GENERATING
            logger.error("Exam generation failed: %s", exc)
            raise

        return await self.get_exam(exam.id, user_id)

    async def partial_regenerate(
        self,
        user_id: str,
        request: ExamPartialRegenerateRequest,
    ) -> Exam:
        exam = await self.get_exam(request.exam_id, user_id)
        if not exam:
            raise ValueError("Exam not found")
        if not exam.current_version:
            raise ValueError("Exam has no current version")

        current_questions = list(exam.current_version.questions or [])
        if not current_questions:
            raise ValueError("Exam has no questions to edit")

        existing = [self._db_question_to_generated(question) for question in current_questions]
        id_to_slot = {str(question.id): int(question.question_number) for question in current_questions}

        edit_requests: list[dict] = []
        for edit in request.edits:
            normalized_ids: list[str] = []
            for raw_id in edit.question_ids:
                slot = self._normalize_question_id_to_slot(raw_id, id_to_slot)
                if slot is not None:
                    normalized_ids.append(str(slot))

            range_start = edit.range_start
            range_end = edit.range_end
            if isinstance(range_start, int) and isinstance(range_end, int) and range_start > range_end:
                range_start, range_end = range_end, range_start

            has_target_ids = bool(normalized_ids)
            has_target_range = isinstance(range_start, int) and isinstance(range_end, int)
            if not has_target_ids and not has_target_range:
                continue

            edit_requests.append(
                {
                    "question_ids": normalized_ids,
                    "range_start": range_start,
                    "range_end": range_end,
                    "edit_prompt": edit.edit_prompt,
                    "edit_type": edit.edit_type,
                    "new_content": edit.new_content,
                    "new_correct_answer": edit.new_correct_answer,
                    "new_bloom_level": edit.new_bloom_level,
                }
            )

        if not edit_requests:
            raise ValueError("No valid target questions to edit")

        agents = self._build_agents(exam.textbook_id)
        constraints = dict(exam.config.get("constraints", {}) or {})
        initial_state: AgentState = {
            "user_id": user_id,
            "textbook_id": exam.textbook_id,
            "chapters": list(exam.chapters or []),
            "prompt": "",
            "exam_type": exam.exam_type.value,
            "difficulty": exam.difficulty.value,
            "question_distribution": {},
            "num_variants": 1,
            "gradually_increasing": False,
            "constraints": constraints,
            "textbook_metadata": {},
            "processing_status": "ready",
            "exam_spec": None,
            "blueprint": None,
            "retrieved_contexts": [],
            "generated_questions": [],
            "validated_questions": existing,
            "validation_summary": {},
            "judged_questions": [],
            "quality_scores": [],
            "grounding_reports": [],
            "duplicate_groups": [],
            "final_questions": [],
            "current_step": "editing",
            "step_progress": 0.0,
            "error": None,
            "chunk_assignments": [],
            "chunk_assignment_payloads": [],
            "question_chunk_metadata": [],
            "original_quota": {},
            "edit_requests": edit_requests,
            "is_partial_edit": True,
            "edit_impact_level": None,
            "refreshed_contexts": [],
            "provider_logs": [],
            "_db_session": self.db,
            "_retry_attempted": False,
            **agents,
        }

        graph = create_exam_generation_graph()
        final_state = await graph.ainvoke(initial_state)

        new_questions = final_state.get("validated_questions", [])
        quality_scores = final_state.get("quality_scores", [])
        grounding_reports = final_state.get("grounding_reports", [])
        qs_by_slot = {
            item["slot_number"]: item
            for item in quality_scores
            if isinstance(item, dict) and "slot_number" in item
        }
        gr_by_slot = {
            item["slot_number"]: item
            for item in grounding_reports
            if isinstance(item, dict) and "slot_number" in item
        }

        new_version = await self._create_exam_version(
            exam=exam,
            user_id=user_id,
            version_number=(exam.current_version.version_number or 0) + 1,
            status="generated",
            parent_version_id=exam.current_version.id,
            change_summary="Partial review/edit update",
        )

        for question in new_questions:
            self.db.add(
                self._question_to_db(
                    exam_id=exam.id,
                    exam_version_id=new_version.id,
                    question=question,
                    quality_by_slot=qs_by_slot,
                    grounding_by_slot=gr_by_slot,
                )
            )

        await self._persist_edit_operations(
            exam_version_id=new_version.id,
            user_id=user_id,
            edit_requests=edit_requests,
            old_questions=current_questions,
            new_questions=new_questions,
        )

        edit_log = {
            "timestamp": datetime.utcnow().isoformat(),
            "request": request.model_dump(),
            "parent_version_id": exam.current_version.id,
            "new_version_id": new_version.id,
            "replaced_questions": [self._question_snapshot(question) for question in current_questions],
        }
        history = list(exam.edit_history_json or [])
        history.append(edit_log)
        exam.edit_history_json = history

        exam.current_version_id = new_version.id
        exam.status = ExamStatus.GENERATED
        exam.total_questions = len(new_questions)
        exam.quality_score = final_state.get("validation_summary", {}).get("pass_rate", 0.0) * 100
        exam.quality_scores_json = quality_scores or None
        exam.grounding_reports_json = grounding_reports or None
        exam.duplicate_groups_json = final_state.get("duplicate_groups") or None
        exam.provider_logs_json = final_state.get("provider_logs") or None
        exam.edit_impact_level = final_state.get("edit_impact_level")

        return await self.get_exam(exam.id, user_id)

    def _exam_query(self, user_id: str, include_versions: bool = True):
        membership_subquery = (
            select(CourseMembership.course_id)
            .where(CourseMembership.user_id == user_id)
        )
        options = [
            selectinload(Exam.exam_spec_record).selectinload(ExamSpecRecord.blueprint_cells),
            selectinload(Exam.current_version).selectinload(ExamVersion.questions),
            selectinload(Exam.current_version).selectinload(ExamVersion.edit_operations),
        ]
        if include_versions:
            options.extend(
                [
                    selectinload(Exam.versions).selectinload(ExamVersion.questions),
                    selectinload(Exam.versions).selectinload(ExamVersion.edit_operations),
                ]
            )
        return (
            select(Exam)
            .where(
                or_(
                    Exam.owner_id == user_id,
                    Exam.course_id.in_(membership_subquery),
                )
            )
            .options(*options)
        )

    async def get_exam(self, exam_id: str, user_id: str) -> Exam | None:
        result = await self.db.execute(
            self._exam_query(user_id=user_id, include_versions=True)
            .where(Exam.id == exam_id)
        )
        return result.scalar_one_or_none()

    async def get_exams(self, user_id: str) -> list[Exam]:
        result = await self.db.execute(
            self._exam_query(user_id=user_id, include_versions=False)
            .order_by(Exam.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def delete_exam(self, exam_id: str, user_id: str) -> bool:
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            return False
        await self.db.delete(exam)
        return True

    async def publish_exam(self, exam_id: str, user_id: str) -> Exam:
        exam = await self.get_exam(exam_id, user_id)
        if not exam:
            raise ValueError("Exam not found")
        if not exam.current_version:
            raise ValueError("Exam has no current version")

        questions = list(exam.current_version.questions or [])
        if not questions:
            raise ValueError("Exam has no questions to publish")

        invalid_questions = [
            question for question in questions
            if not question.source_evidence_json
            or (question.verification_status or "").lower() == "failed"
        ]
        if invalid_questions:
            raise ValueError("Exam still has unverified questions or missing evidence")

        exam.status = ExamStatus.PUBLISHED
        exam.published_at = datetime.utcnow()
        exam.current_version.status = "published"
        return exam
